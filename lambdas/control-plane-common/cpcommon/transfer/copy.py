"""Server-side S3 copy for one batch of transfer items.

Moved from ``tscommon.copy`` by SPEC-160, unchanged in what it does to an object — no data
passes through the Lambda, small objects take a single server-side copy and objects over S3's
single-copy limit take a multipart part-copy — and changed in what a batch means. It used to
copy a whole recipient's prefix inside one invocation, which is what made the share caps the
shape of one Lambda's timeout. It now copies whatever items a Distributed Map hands it.

**A destination storage class is per ITEM and optional** (SPEC-169). The archive plane is this
engine's third caller and the first that does not want S3's default: it writes at ``GLACIER``.
Absent means the argument is not passed at all, so table share and file send issue byte-identical
``CopyObject`` calls — asserted, not assumed.

**A deterministic fault on one item does not abort its batch.** The batch returns a per-item
outcome list and SUCCEEDS, so one unreadable key never costs its 49 siblings their copy — and
the failure is attributed downstream from the exported result. A transient fault is the
opposite: it raises, because the whole batch retrying is both correct and cheap (copy is
idempotent, and the conflict guard already ran).

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

from .. import clients, errors
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
) -> None:
    """Copies one object server-side, choosing single or multipart by its size.

    A failed multipart upload is aborted so it never leaves a half-open upload accruing
    storage. The abort itself is best-effort, since an expired upload lifecycles away.

    **THE STORAGE CLASS IS SET IN TWO DIFFERENT PLACES, and only one of them is obvious.** On the
    single-copy path it is an argument to ``CopyObject``. On the multipart path it belongs to
    ``CreateMultipartUpload`` — the part copies inherit it, and passing it to ``UploadPartCopy``
    is not merely redundant, it is not a parameter S3 accepts there. An implementation that set
    it on the single path only would archive every object under 5 GiB to ``GLACIER`` and every
    object over it to ``STANDARD``, silently, at roughly 20x the storage cost and with the
    restore path suddenly unnecessary for exactly the biggest objects.

    **THE METADATA HAS THE SAME SHAPE OF SPLIT, and it was wrong the same way** (SPEC-171).
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

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault.
      Exception: The raw fault on a deterministic one, for the caller to attribute.
    """
    source = {"Bucket": src_bucket, "Key": src_key}
    extra = {"StorageClass": storage_class} if storage_class else {}
    if size <= MULTIPART_COPY_THRESHOLD:
        try:
            s3.copy_object(
                Bucket=dest_bucket,
                Key=dest_key,
                CopySource=source,
                MetadataDirective="COPY",
                **extra,
            )
        except Exception as exc:
            errors.raise_if_transient(exc, f"copy {src_bucket}/{src_key} -> {dest_bucket}/{dest_key}")
            raise
        return

    extra.update(_source_headers(s3, src_bucket, src_key))
    upload = s3.create_multipart_upload(Bucket=dest_bucket, Key=dest_key, **extra)
    upload_id = upload["UploadId"]
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
        )
    except Exception as exc:
        try:
            s3.abort_multipart_upload(Bucket=dest_bucket, Key=dest_key, UploadId=upload_id)
        except Exception:  # noqa: BLE001
            logger.warning("abort_multipart_upload failed for %s/%s", dest_bucket, dest_key)
        errors.raise_if_transient(exc, f"copy {src_bucket}/{src_key} -> {dest_bucket}/{dest_key}")
        raise


def _copy_item(item: dict) -> None:
    """Copies one manifest item.

    The four location fields are indexed rather than fetched with a default: a manifest line
    missing one is malformed, and a ``KeyError`` here fails that item and attributes it, where
    an empty-string default would issue a copy against a bucket named "".

    The storage class is the one field read with a default rather than indexed: it is optional
    by design, and a manifest written by table share or file send carries none.

    Args:
      item: A manifest line — source and destination bucket and key, the size the plan measured,
        and optionally the destination storage class.

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault.
      KeyError: When the line is missing a location field.
      Exception: The raw fault on a deterministic one.
    """
    copy_one(
        clients.s3(),
        item["srcBucket"],
        item["srcKey"],
        item["destBucket"],
        item["destKey"],
        item.get("size") or 0,
        item.get("storageClass") or "",
    )


def copy_batch(items: list, failure_reason: str, concurrency: int = COPY_CONCURRENCY) -> dict:
    """Copies every item in a batch, isolating deterministic per-item failures.

    Transient faults are collected across the whole batch and re-raised once every in-flight
    copy has settled, so a retry never races copies still running from the previous attempt.
    A batch carrying both kinds raises: the transient item deserves its retry, and the
    deterministic ones will simply be re-reported next time round.

    Args:
      items: The batch's transfer items.
      failure_reason: The domain's reason code for a failed item, carried into each outcome —
        cpcommon owns the algorithm, the calling plane owns the wording.
      concurrency: Worker pool size.

    Returns:
      ``{"copied": n, "failures": [{"recipient": …, "kind": …, "reason": …}, …]}``. Failures name
      the recipient and never the key: the list rides the exported result and then the state, and
      keys are the unbounded term. The ``kind`` travels with the name because a destination is a
      ``(kind, name)`` pair — nothing stops a shared space being named after a user, and attributing
      on the name alone would deny one of them a transfer the other lost.

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
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "copy failed for %s/%s: %s", item.get("srcBucket"), item.get("srcKey"), exc
                )
                failures.append({
                    "recipient": item.get("recipient"),
                    "kind": item.get("kind"),
                    "reason": failure_reason,
                })
    if transient is not None:
        raise transient
    return {"copied": len(items) - len(failures), "failures": failures}
