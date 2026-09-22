"""Server-side S3 copy for one batch of transfer items.

Moved from ``tscommon.copy``, unchanged in what it does to an object — no data
passes through the Lambda, small objects take a single server-side copy and objects over S3's
single-copy limit take a multipart part-copy — and changed in what a batch means. It used to
copy a whole recipient's prefix inside one invocation, which is what made the share caps the
shape of one Lambda's timeout. It now copies whatever items a Distributed Map hands it.

**A destination storage class is per ITEM and optional**. The archive plane is this
engine's third caller and the first that does not want S3's default: it writes at ``GLACIER``.
Absent means the argument is not passed at all, so table share and file send issue byte-identical
``CopyObject`` calls — asserted, not assumed.

**A deterministic fault on one item does not abort its batch.** The batch returns a per-item
outcome list and SUCCEEDS, so one unreadable key never costs its 49 siblings their copy — and
the failure is attributed downstream from the exported result. A transient fault is the
opposite: it raises, because the whole batch retrying is both correct and cheap (copy is
idempotent, and the conflict guard already ran).

**A copy can REFUSE to overwrite, per item, and that is what makes a restore safe.** A line
carrying ``ifAbsent`` conditions the write on the destination not existing, so a file created at
that path after the plan was made is left alone rather than destroyed — the only guard that holds
for the whole length of a Map rather than at the moment it starts. **The condition has two homes,
like the storage class**: ``CopyObject`` takes it directly, and on the multipart path it belongs to
``CompleteMultipartUpload`` alone, because S3 accepts it on neither the create nor the part copies.
A refusal is then resolved rather than reported — ``_already_copied`` says why.

**A copy carries the source object's metadata, and the two paths do that DIFFERENTLY**
. ``CopyObject`` takes ``MetadataDirective: COPY``, which is also its default and is
now passed explicitly. A multipart copy has no such directive: ``UploadPartCopy`` moves bytes
and nothing else, so the destination's content type and user metadata are whatever
``CreateMultipartUpload`` was told — and it was told nothing, so **every object over
``MULTIPART_COPY_THRESHOLD`` silently lost its content type**. That was latent on all three
callers and surfaced here, because an archive round trip is the first operation in this repo
that copies an object twice and hands it back to the user expecting it unchanged.

Attributes:
  MULTIPART_COPY_THRESHOLD: S3's single-request copy ceiling; larger objects must
    multipart-copy.
  MULTIPART_PART_SIZE: Byte range per part copy.
  COPY_CONCURRENCY: Bounded worker pool within one batch. The batch size bounds the work; this
    bounds the parallelism, and with the Map's own concurrency above it the product is what
    reaches S3.
  _CARRIED_HEADERS: The ``HeadObject`` response fields a multipart copy has to re-state on
    ``CreateMultipartUpload``, mapped to that call's argument names. Only the ones S3 accepts
    there, and each is set only when the source actually carries it — passing an empty
    ``ContentType`` would stamp the default over a real value rather than leaving it alone.

    **ONE THING ``MetadataDirective`` CARRIES THAT THIS DOES NOT: the object's TAG SET.**
    ``CopyObject`` copies tags by default (``TaggingDirective`` defaults to ``COPY``);
    ``HeadObject`` does not report them, so matching that would cost a ``GetObjectTagging`` call
    per object over the threshold. **Nothing in this portal tags an object**, so the parity is
    not bought — recorded here rather than left for someone to discover, because the moment a
    plane starts tagging, every object over 5 GiB will start losing them silently.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from .. import cas, clients, errors, observability
from ..errors import TransientError

logger = logging.getLogger(__name__)

MULTIPART_COPY_THRESHOLD = 5 * 1024**3
MULTIPART_PART_SIZE = 1024**3

COPY_CONCURRENCY = 8

_CARRIED_HEADERS = {
    "ContentType": "ContentType",
    "ContentEncoding": "ContentEncoding",
    "ContentDisposition": "ContentDisposition",
    "ContentLanguage": "ContentLanguage",
    "CacheControl": "CacheControl",
    "Expires": "Expires",
    "WebsiteRedirectLocation": "WebsiteRedirectLocation",
    "Metadata": "Metadata",
}


class DestinationOccupied(Exception):
    """A conditional copy was refused and the destination is not this run's own write.

    Distinct from every other deterministic fault because it is attributed differently: the
    caller names a reason for it, and the sentence a user reads about a file that was left
    alone is not the sentence they read about one that could not be copied. It is not a
    ``TerminalError`` — a per-item outcome is reported out of the batch, never raised past it.
    """


def _already_copied(s3, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str) -> bool:
    """Reports whether a refused destination is indistinguishable from this copy's own output.

    **This is the predicate that stops a batch retry reporting the files it just wrote as
    collisions.** A batch re-raises one item's transient fault once every copy has settled, so
    the retry re-copies the items the first attempt already finished, and every one of those
    answers the condition with a refusal. Read as "occupied", each would be a file the user is
    told was left in the way — by the run that put it there.

    True means the destination is this run's own earlier write, or an object identical to it in
    ETag, length, content type and user metadata. Either way nothing is lost by counting it
    copied: the bytes the caller wanted at that key are at that key. **The run's own write
    always matches**, on both copy paths — the single copy carries the source's metadata under
    ``MetadataDirective``, the multipart create re-states it from ``_CARRIED_HEADERS``, and every
    bucket here is ``AES256``, so an ETag is derived from the bytes. A re-part at the same
    ``MULTIPART_PART_SIZE`` over the same length gives the same part boundaries and so the same
    composite tag.

    **The comparison is narrower than "everything a copy carries", deliberately.** The multipart
    create also re-states content encoding, disposition, language, cache control, expiry and a
    website redirect, and those are not compared. Comparing them would tighten this against a
    user's file that matched on all four — unreachable today, since nothing in this portal sets
    any of them — at the cost of a false collision whenever S3 renders one of them back
    differently from the way it was supplied, and a false collision here is a file the user is
    wrongly told to move. The residual runs the other way: a destination matching on all four
    and differing on one of the six is counted copied, and the archived copy's header is lost
    when the vault is swept, while the bytes survive.

    **Every failed head resolves to occupied**, which is why a ``403`` and a ``404`` may give
    the same answer: the caller's next move on False is to leave the destination alone and keep
    the archive, so an ambiguous read costs a file that is not restored and never an overwrite.
    A transient fault is the one exception — it raises, so the batch retries rather than
    reporting a collision it cannot substantiate. The source is not headed when the destination
    could not be.

    Args:
      s3: The S3 client.
      src_bucket: Source bucket.
      src_key: Source key.
      dest_bucket: Destination bucket.
      dest_key: Destination key.

    Returns:
      True when the destination may be counted as copied.

    Raises:
      TransientError: When either head failed retryably.
    """
    try:
        destination = s3.head_object(Bucket=dest_bucket, Key=dest_key)
    except Exception as exc:  # noqa: BLE001 - any answer but a transient one means leave it alone
        errors.raise_if_transient(exc, f"head {dest_bucket}/{dest_key}")
        logger.warning("could not head the refused destination %s/%s: %s", dest_bucket, dest_key, exc)
        return False
    try:
        source = s3.head_object(Bucket=src_bucket, Key=src_key)
    except Exception as exc:  # noqa: BLE001 - same rule, and it cannot be reached without the head above
        errors.raise_if_transient(exc, f"head {src_bucket}/{src_key}")
        logger.warning("could not head the copy source %s/%s: %s", src_bucket, src_key, exc)
        return False

    tag, length = destination.get("ETag"), destination.get("ContentLength")
    if not tag or length is None:
        return False
    return (
        source.get("ETag") == tag
        and source.get("ContentLength") == length
        and source.get("ContentType") == destination.get("ContentType")
        and (source.get("Metadata") or {}) == (destination.get("Metadata") or {})
    )


def _settle_refused_copy(
    s3, exc: Exception, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str
) -> None:
    """Decides what a refused conditional write means, and returns only when it means "copied".

    The two codes S3 answers a conditional write with are different questions, which is why
    ``cas`` tells them apart rather than collapsing them here. A ``412`` is an answer about the
    object — something is at the key — and is settled by comparing it. A ``409`` is an answer
    about the race: S3 documents both conditioned operations as retryable on it, and says
    nothing is known about what is at the key, so comparing would be comparing against whatever
    the other writer happened to have finished.

    Reading a ``409`` as occupied is the mistake that looks correct, and one plane makes the
    opposite call for a sound reason: a conversion writes one object once, so for it a conflict
    IS the collision. A batch copy retries, and after the retry the comparison decides, so here
    a conflict is a fault to retry and never a verdict.

    Args:
      s3: The S3 client.
      exc: The write fault, already known to be a precondition failure of one kind or the other.
      src_bucket: Source bucket.
      src_key: Source key.
      dest_bucket: Destination bucket.
      dest_key: Destination key.

    Returns:
      None, when the destination may be counted as copied.

    Raises:
      TransientError: On a conflict, or when a head could not settle the comparison.
      DestinationOccupied: When something that is not this copy's own output holds the key.
    """
    if cas.is_conditional_conflict(exc):
        raise TransientError(
            f"a concurrent write interrupted the copy to {dest_bucket}/{dest_key}"
        ) from exc
    if _already_copied(s3, src_bucket, src_key, dest_bucket, dest_key):
        return
    raise DestinationOccupied(
        f"{dest_bucket}/{dest_key} already holds something this copy did not write"
    ) from exc


def _source_headers(s3, src_bucket: str, src_key: str) -> dict:
    """Reads the headers a multipart copy has to re-state, for the destination's create call.

    Only the multipart path needs this: ``CopyObject`` has ``MetadataDirective``, and a single
    HEAD per object over 5 GiB is negligible beside the part copies that follow it.

    Args:
      s3: The S3 client.
      src_bucket: Source bucket.
      src_key: Source key.

    Returns:
      The ``CreateMultipartUpload`` arguments the source's own headers imply, with anything the
      source does not carry left out entirely.

    Raises:
      TransientError: On a retryable fault.
      Exception: The raw fault on a deterministic one — a source that cannot be headed cannot
        be copied either, so it fails the item here rather than producing an object stripped of
        its metadata.
    """
    try:
        head = s3.head_object(Bucket=src_bucket, Key=src_key)
    except Exception as exc:
        errors.raise_if_transient(exc, f"head {src_bucket}/{src_key}")
        raise
    return {
        argument: head[field]
        for field, argument in _CARRIED_HEADERS.items()
        if head.get(field)
    }


def copy_one(
    s3,
    src_bucket: str,
    src_key: str,
    dest_bucket: str,
    dest_key: str,
    size: int,
    storage_class: str = "",
    if_absent: bool = False,
) -> None:
    """Copies one object server-side, choosing single or multipart by its size.

    A failed multipart upload is aborted so it never leaves a half-open upload accruing
    storage. The abort itself is best-effort, since an expired upload lifecycles away. The
    create is guarded on its own because a create that failed opened nothing to abort, and it is
    classified like every other call here: a throttle on it must retry the batch, since failing
    the item instead rolls a whole archive back over a fault that would have passed.

    **THE STORAGE CLASS IS SET IN TWO DIFFERENT PLACES, and only one of them is obvious.** On the
    single-copy path it is an argument to ``CopyObject``. On the multipart path it belongs to
    ``CreateMultipartUpload`` — the part copies inherit it, and passing it to ``UploadPartCopy``
    is not merely redundant, it is not a parameter S3 accepts there. An implementation that set
    it on the single path only would archive every object under 5 GiB to ``GLACIER`` and every
    object over it to ``STANDARD``, silently, at roughly 20x the storage cost and with the
    restore path suddenly unnecessary for exactly the biggest objects.

    **THE METADATA HAS THE SAME SHAPE OF SPLIT, and it was wrong the same way**.
    ``MetadataDirective: COPY`` is passed explicitly on the single path — it is S3's default,
    and it is stated rather than assumed because the multipart path proves the default is not
    universal. On the multipart path there is no directive at all: the destination gets the
    content type and user metadata the create call names, so they are read off the source first.
    Without that, every object over 5 GiB came back from an archive as
    ``binary/octet-stream`` with its user metadata gone.

    Args:
      s3: The S3 client.
      src_bucket: Source bucket.
      src_key: Source key.
      dest_bucket: Destination bucket.
      dest_key: Destination key.
      size: The object's byte size, deciding the copy strategy. A missing or zero size takes
        the single-copy path, which is correct for every object S3 will accept there.
      storage_class: The destination storage class. **Empty means the argument is not passed at
        all**, which is S3's own default (``STANDARD``) — deliberately not the literal
        ``"STANDARD"``, so the two existing callers' requests are byte-identical to what they
        issued before this parameter existed.
      if_absent: Whether the copy may overwrite. False means the argument is not passed at all,
        for the storage class's reason: the four callers that do not ask for it issue exactly
        the requests they issued before it existed.

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault, and on a conflict against a conditional write.
      DestinationOccupied: When a conditional write was refused by something this copy did not
        write.
      Exception: The raw fault on a deterministic one, for the caller to attribute.
    """
    source = {"Bucket": src_bucket, "Key": src_key}
    extra = {"StorageClass": storage_class} if storage_class else {}
    condition = {"IfNoneMatch": "*"} if if_absent else {}
    detail = f"copy {src_bucket}/{src_key} -> {dest_bucket}/{dest_key}"
    if size <= MULTIPART_COPY_THRESHOLD:
        try:
            s3.copy_object(
                Bucket=dest_bucket,
                Key=dest_key,
                CopySource=source,
                MetadataDirective="COPY",
                **extra,
                **condition,
            )
        except Exception as exc:
            if if_absent and cas.is_precondition(exc):
                _settle_refused_copy(s3, exc, src_bucket, src_key, dest_bucket, dest_key)
                return
            errors.raise_if_transient(exc, detail)
            raise
        return

    extra.update(_source_headers(s3, src_bucket, src_key))
    try:
        upload_id = s3.create_multipart_upload(Bucket=dest_bucket, Key=dest_key, **extra)[
            "UploadId"
        ]
    except Exception as exc:
        errors.raise_if_transient(exc, detail)
        raise
    try:
        parts = []
        offset = 0
        part_number = 1
        while offset < size:
            end = min(offset + MULTIPART_PART_SIZE, size) - 1
            resp = s3.upload_part_copy(
                Bucket=dest_bucket,
                Key=dest_key,
                UploadId=upload_id,
                PartNumber=part_number,
                CopySource=source,
                CopySourceRange=f"bytes={offset}-{end}",
            )
            parts.append({"ETag": resp["CopyPartResult"]["ETag"], "PartNumber": part_number})
            offset = end + 1
            part_number += 1
        s3.complete_multipart_upload(
            Bucket=dest_bucket,
            Key=dest_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
            **condition,
        )
    except Exception as exc:
        try:
            s3.abort_multipart_upload(Bucket=dest_bucket, Key=dest_key, UploadId=upload_id)
        except Exception:  # noqa: BLE001
            logger.warning("abort_multipart_upload failed for %s/%s", dest_bucket, dest_key)
        if if_absent and cas.is_precondition(exc):
            _settle_refused_copy(s3, exc, src_bucket, src_key, dest_bucket, dest_key)
            return
        errors.raise_if_transient(exc, detail)
        raise


def _copy_item(item: dict) -> None:
    """Copies one manifest item.

    The four location fields are indexed rather than fetched with a default: a manifest line
    missing one is malformed, and a ``KeyError`` here fails that item and attributes it, where
    an empty-string default would issue a copy against a bucket named "".

    The storage class is the one field read with a default rather than indexed: it is optional
    by design, and a manifest written by table share or file send carries none.

    **``ifAbsent`` is optional but not permissive.** A line carrying something that is not a
    boolean fails its own item rather than being copied, because the two ways to be lenient are
    both worse than a reported failure: treating a truthy string as True conditions a copy the
    caller may not have meant to condition, and treating an unrecognised value as False turns a
    line that asked not to overwrite into one that does. A missing key is a different thing from
    a malformed one and stays the unconditional default.

    Args:
      item: A manifest line — source and destination bucket and key, the size the plan measured,
        and optionally the destination storage class and whether the copy may overwrite.

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault.
      DestinationOccupied: When a conditional line met something it did not write.
      KeyError: When the line is missing a location field.
      TypeError: When ``ifAbsent`` is present and is not a boolean.
      Exception: The raw fault on a deterministic one.
    """
    if_absent = item.get("ifAbsent", False)
    if not isinstance(if_absent, bool):
        raise TypeError(f"ifAbsent is a {type(if_absent).__name__}, which is not a boolean")
    copy_one(
        clients.s3(),
        item["srcBucket"],
        item["srcKey"],
        item["destBucket"],
        item["destKey"],
        item.get("size") or 0,
        item.get("storageClass") or "",
        if_absent=if_absent,
    )


@observability.step("copy-batch")
def copy_batch(
    items: list,
    failure_reason: str,
    *,
    echo_fields: tuple,
    occupied_reason: str | None = None,
    concurrency: int = COPY_CONCURRENCY,
) -> dict:
    """Copies every item in a batch, isolating deterministic per-item failures.

    **Call bound: exactly once per invocation**, in each of the four copy verbs that reach it —
    archive, file-ops, file-send and table-share — with no branch above the call in any of them.
    That bound is why a child span belongs here at all: the events are two per invocation rather
    than two per object. **The step must not move inside the pool below.** log-foundry's span
    stack and baggage are ``contextvars``, which do not cross into ``ThreadPoolExecutor``
    workers: a step planted on ``copy_one`` over five items emitted five spans, every
    ``parent_span_id`` null, six distinct trace ids and empty fields — unattributable events, not
    merely more of them.

    Transient faults are collected across the whole batch and re-raised once every in-flight
    copy has settled, so a retry never races copies still running from the previous attempt.
    A batch carrying both kinds raises: the transient item deserves its retry, and the
    deterministic ones will simply be re-reported next time round.

    **THE ATTRIBUTION VOCABULARY IS THE CALLER'S, NOT THIS MODULE'S.** It used to be table-share's
    ``recipient``/``kind`` hardcoded here, which made the engine unusable by a plane that
    attributes to something else: a field placed on a manifest line rode into the child input and
    was dropped on the way out. The file-operations plane attributes to a selected ITEM, so the
    caller now names the fields to echo. ``echo_fields`` has **no default** — a default would hand a
    new caller either table-share's vocabulary or an empty set, and either is wrong without a
    review.

    **The echoed fields must stay BOUNDED**, and that is a rule rather than a convention: this list
    rides the exported result and then the state, where a key list is the unbounded term that
    breaches the 256 KB limit ON the Map and destroys every per-item outcome the export exists to
    preserve. Echo a name, never a key set.

    Args:
      items: The batch's transfer items.
      failure_reason: The domain's reason code for a failed item, carried into each outcome —
        cpcommon owns the algorithm, the calling plane owns the wording.
      echo_fields: The manifest-line fields copied onto each failure record, in the order the
        caller wants them. An EMPTY tuple is meaningful: a caller that needs only the count
        passes it, and echoing fields its manifest never carries writes a null for each onto
        every failure — which is what the archive's records carried when this engine hardcoded
        ``recipient`` and ``kind``. The archive now echoes one boolean, its folder flag.
      occupied_reason: The domain's reason code for an item a conditional copy would have
        overwritten, which is a different outcome from a copy that failed — the file is intact,
        it is simply not this run's. **None means the caller does not tell the two apart** and
        both report as ``failure_reason``, which is what every caller that sets no ``ifAbsent``
        gets, since none of them can reach the outcome at all.
      concurrency: Worker pool size.

    Returns:
      ``{"copied": n, "failures": [{<echoed fields>, "reason": …}, …]}``. Where a caller echoes a
      destination it echoes the ``(kind, name)`` PAIR, because a destination is that pair — nothing
      stops a shared space being named after a user, and attributing on the name alone would deny
      one of them a transfer the other lost.

    Raises:
      TransientError: When any item failed retryably, after every in-flight copy has settled.
    """
    failures = []
    transient = None
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [(item, pool.submit(_copy_item, item)) for item in items]
        for item, future in futures:
            try:
                future.result()
            except TransientError as exc:
                transient = transient or exc
            except DestinationOccupied as exc:
                logger.info(
                    "destination occupied for %s/%s: %s",
                    item.get("destBucket"),
                    item.get("destKey"),
                    exc,
                )
                failures.append(
                    {field: item.get(field) for field in echo_fields}
                    | {"reason": occupied_reason or failure_reason}
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "copy failed for %s/%s: %s", item.get("srcBucket"), item.get("srcKey"), exc
                )
                failures.append(
                    {field: item.get(field) for field in echo_fields}
                    | {"reason": failure_reason}
                )
    if transient is not None:
        raise transient
    return {"copied": len(items) - len(failures), "failures": failures}
