"""The restore request: its contract, and the archive it names.

A restore is the archive read backwards, and the two questions this module answers
are the ones that must be settled before a single byte of Glacier retrieval is paid for: **is
this request well-formed and authorized, and what would come back where.**

**The space comes from the REQUEST, never from the archive.** The route the user is standing in
names the space and authorization is then a question about *that* space, exactly as the
data-quality report view takes its space from the route rather than deriving it. An
archive belonging to a different space simply is not found — which is also why
``archive_not_found`` says nothing about whether the id ever existed.

**The lookup does not read ``_manifest.json`` to find out what to restore.** The archived key
encodes its own origin (``paths.origin_key``), so one ``ListObjectsV2`` over the archive prefix
yields both the objects and their destinations with no record required. The manifest is a
cross-check only: a restore still works when it is missing, and refuses when it disagrees. That
is the whole reason the manifest is described as a report rather than a record, and
``test_no_restore_verb_requires_the_manifest`` holds it open from the other side.

**And it answers a third question, after the fact: is the archive still all there.** Two restores
of one archive can run at once, and the one that finishes first sweeps the vault — so a run that
stopped short cannot say the archive is intact on the strength of not having deleted it. It counts,
through the same exclusion rule the object list was built with, and fails closed on anything it
cannot count.

Attributes:
  _INTACT_ATTEMPTS: How many times the vault count may ask S3 before it gives up and reports the
    archive unconfirmed. One attempt plus two retries, sized to sit well inside the verb's own
    30-second timeout rather than against the machine's ceiling: the caller is already on a
    failure path, and a verb killed for taking too long loses the report entirely.
  ALLOWED_FIELDS: The complete set of top-level fields a RESTORE request may carry. It is a
    different set from the archive request's — ``space`` and ``archiveId`` in place of
    ``source`` — which is why the unknown-field check is made per mode rather than once: a
    single union would accept a restore carrying a selection and an archive naming an archive
    id, and quietly ignore whichever the mode did not use.
"""

import json
import logging

from cpcommon import clients, errors, events, observability, s3_listing
from cpcommon.errors import TerminalError, TransientError

from . import manifest as _manifest
from . import (
    messages,  # noqa: F401
    paths,
)
from .authz import authorize_source
from .config import archive_bucket

logger = logging.getLogger()

_INTACT_ATTEMPTS = 3

ALLOWED_FIELDS = frozenset(
    {"requestId", "mode", "actor", "space", "archiveId", "identity", "traceparent"}
)


def validate(req: dict, request_id: str, actor: str) -> dict:
    """Validates a restore request and resolves the archive it names.

    The archive id is checked against the strict UUID pattern **before** it is concatenated into
    anything, and the archive root is then built by ``paths.archive_root`` — the same function
    The archive uses the same builder to WRITE it, so the read and the write cannot drift.

    **``requestId`` and ``archiveId`` must be different values** Conflating them was
    the obvious shortcut and is wrong in both directions: a refused restore must be re-submittable
    under a new run id, and a second attempt at one archive is a new request rather than a
    duplicate of the first. It is refused rather than tolerated, because a producer that has
    conflated them will do it on every request and the symptom would surface only under a retry.

    Args:
      req: The parsed request body, already known to be an object carrying a request id, a mode
        and an actor token.
      request_id: The validated request id for THIS run.
      actor: The trusted username, from the API's identity block and nowhere else.

    Returns:
      The validated restore request: the request id, the mode, the actor, the authorized space
      and the archive location. ``source`` carries the SPACE — the same block an archive
      request's does, minus the selection — because both modes flow through one ``Validated``
      Pass and a Pass naming a path the state does not have raises an uncatchable
      ``States.Runtime``. In this mode it is the restore's DESTINATION.

      The ``archive`` block carries the RECEIPT's location alongside the vault's, resolved here
      exactly as validate-authorize resolves it for an archive: it is a pure function of the
      space and the archive id, so it is built once rather than three agreeing times.
      **It is keyed on the ARCHIVE id, not this run's**, because the document it names was
      written by the archive and is being rewritten rather than created.

    Raises:
      TerminalError: ``malformed_event`` when the shape is wrong or the two ids are the same,
        ``invalid_request`` when the archive id is not a UUID v4, and ``forbidden`` when the
        space is unknown or the actor is not entitled to it.
      TransientError: On a retryable S3 fault reading the shared-space registry.
    """
    archive_id = paths.validated_archive_id(req.get("archiveId"))
    if archive_id == request_id:
        raise TerminalError(
            events.MALFORMED, "requestId and archiveId must be different values"
        )

    space = authorize_source(actor, req.get("space"))
    archive_root = paths.archive_root(space["kind"], space["name"], archive_id)

    return {
        "traceparent": observability.run_traceparent(),
        "requestId": request_id,
        "mode": "restore",
        "actor": {"username": actor},
        "source": space,
        "archive": {
            "bucket": archive_bucket(),
            "root": archive_root,
            "archiveId": archive_id,
            "receiptBucket": space["bucket"],
            "receiptKey": paths.receipt_key(space["name"], archive_id),
            "indexKey": paths.index_key(space["name"]),
        },
    }


def is_archived_object(key: str, archive_root: str) -> bool:
    """Reports whether a key under an archive prefix is archived DATA rather than this plane's record.

    Lifted out of ``derive_destinations`` so the restore's object list and the vault count that
    checks it cannot disagree about what an archived object is. They answer two different
    questions — what comes back, and how many are still there — and a count taken through a
    different rule would compare a number against a number built from another population, which
    is the one way a "the archive is still complete" claim could be wrong while looking right.

    ``_manifest.json`` is excluded by its EXACT KEY at the archive root, never by basename: a
    user's own ``reports/_manifest.json`` three folders down was archived like any other file and
    is data here, while the record this plane wrote at the root is not.

    Args:
      key: The absolute object key.
      archive_root: The archive prefix, ending in a slash.

    Returns:
      True for archived data, False for the record.

    Raises:
      None.
    """
    return key != f"{archive_root}{_manifest.BASENAME}"


def _ignores_the_record(archive_root: str):
    """Builds the listing predicate both readers of an archive prefix pass.

    ``list_data_objects`` asks what to IGNORE and ``is_archived_object`` answers what to KEEP, so
    the inversion happens here and in one place — a predicate whose polarity is written out at
    each call site is one that is eventually written backwards at one of them, and backwards here
    means listing the record as data and every real object as the record.

    Args:
      archive_root: The archive prefix, ending in a slash.

    Returns:
      A predicate in ``list_data_objects``' ``(key, size, prefix)`` shape.

    Raises:
      None.
    """

    def ignore(key: str, size: int, prefix: str) -> bool:
        """Reports whether a listed key is this plane's own record rather than archived data.

        Args:
          key: The absolute object key.
          size: The object's size, unused — an archived placeholder is data here.
          prefix: The listing prefix, unused — the rule is one exact key.

        Returns:
          True only for the record at the archive root.

        Raises:
          None.
        """
        del size, prefix
        return not is_archived_object(key, archive_root)

    return ignore


def archive_is_intact(bucket: str, archive_root: str, expected) -> bool:
    """Reports whether the vault still holds every object the plan counted, and FAILS CLOSED.

    **The only thing that earns a message the right to call an archive complete.** A second
    restore of the same archive can run beside this one and sweeps the vault when it finishes,
    so "the archive is intact" cannot be asserted from the fact that this run did not delete it.
    Counting is the evidence, and it is evidence about the moment it was taken — which is why the
    sentence it earns is time-scoped rather than a claim about now.

    **Anything short of a full count returns False**, including a listing that keeps failing, an
    empty prefix and a prefix holding only the record. The asymmetry is the whole design: a wrong
    "could not be confirmed" costs a user a conversation with an administrator, and a wrong "still
    complete" can cost them the only copy of their files.

    A transient fault is retried rather than read as a sweep, because a throttle is not evidence
    about the vault. The listing raises a RAW client error — pagination is shared and the
    classification is the caller's job — so the fault is classified here rather than assumed to
    arrive already named; two retries are well inside the verb's own timeout, and a verb killed
    anyway surfaces as a sandbox timeout on the state's ``Catch``, whose generic wording makes no
    claim about the archive at all.

    Args:
      bucket: The archive bucket.
      archive_root: The archive prefix, ending in a slash.
      expected: The object count the restore plan recorded. A value that is not an integer is not
        a count, and answers False rather than raising — this runs on a path that is already
        reporting a failure, and it must not become the reason that report is lost.

    Returns:
      True only when the prefix holds exactly ``expected`` archived objects.

    Raises:
      None.
    """
    if not isinstance(expected, int) or isinstance(expected, bool):
        logger.warning("no usable object count to check %s/%s against", bucket, archive_root)
        return False
    for attempt in range(_INTACT_ATTEMPTS):
        try:
            return _count_archived(bucket, archive_root) == expected
        except TransientError as err:
            logger.info(
                "listing %s/%s was throttled on attempt %d: %s",
                bucket,
                archive_root,
                attempt + 1,
                err,
            )
        except Exception as err:  # noqa: BLE001 - an unreadable vault is an unconfirmed one
            logger.warning("could not count %s/%s: %s", bucket, archive_root, err)
            return False
    logger.warning("gave up counting %s/%s after %d attempts", bucket, archive_root, _INTACT_ATTEMPTS)
    return False


def _count_archived(bucket: str, archive_root: str) -> int:
    """Counts the archived objects under a prefix, through the restore's own exclusion rule.

    Args:
      bucket: The archive bucket.
      archive_root: The archive prefix, ending in a slash.

    Returns:
      How many archived objects the prefix holds.

    Raises:
      TransientError: On a retryable S3 fault, so the caller can retry rather than conclude.
      Exception: The raw fault on a deterministic one.
    """
    try:
        return sum(
            1
            for _ in s3_listing.list_data_objects(
                bucket, archive_root, ignore=_ignores_the_record(archive_root)
            )
        )
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{archive_root}")
        raise


def derive_destinations(bucket: str, archive_root: str, space_root: str) -> tuple:
    """Lists an archive and rebuilds every destination it would write back.

    Pagination is ``cpcommon.s3_listing``'s — the same paginator the expansion and the rollback
    use, and the third listing of this same prefix — with a predicate of this plane's own. The
    DEFAULT predicate is what must not be reused: it drops zero-byte objects, hidden segments and
    folder keys, and every one of those is something this archive deliberately CARRIED (the expansion's
    ``_excluder`` keeps what the others drop, so an archived empty folder comes back). Restoring
    through a filter the archive did not write through would silently return less than was taken.
    That is exactly the split the send plane recorded: the pagination is shared, the exclusions are not.

    ``_manifest.json`` is excluded by its EXACT KEY at the archive root — ``is_archived_object``
    holds that rule, and ``archive_is_intact`` counts through the same one, so what comes back and
    what is counted as still there cannot mean two different things.

    Args:
      bucket: The archive bucket.
      archive_root: The archive prefix, ending in a slash.
      space_root: The authorized space root the objects are restored into.

    Returns:
      ``(objects, total_bytes)``, each object carrying its archive key, its destination key and
      its size. The size rides so the restore can tell the user how much is coming back and
      the retrieval can bound its wait.

    Raises:
      TerminalError: ``forbidden`` from the destination reconstruction.
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb.
    """
    ignore = _ignores_the_record(archive_root)

    objects: list = []
    total_bytes = 0
    try:
        for key, size in s3_listing.list_data_objects(bucket, archive_root, ignore=ignore):
            objects.append(
                {
                    "archiveKey": key,
                    "destKey": paths.origin_key(key, archive_root, space_root),
                    "bytes": size,
                }
            )
            total_bytes += size
    except TerminalError:
        raise
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{archive_root}")
        raise
    return objects, total_bytes


def read_recorded_count(bucket: str, archive_root: str) -> int | None:
    """Reads the object count ``_manifest.json`` recorded, or None when there is no record.

    **Absent is not a failure** The manifest is not load-bearing, and a restore
    that refused for want of a convenience record would be exactly the failure mode the
    self-describing key layout exists to prevent. Unreadable and malformed are treated the same
    way as absent and for the same reason — the cross-check can only add confidence, so its own
    fault must not subtract any.

    Args:
      bucket: The archive bucket.
      archive_root: The archive prefix.

    Returns:
      The recorded ``objectCount`` as an int, or None when there is no usable record.

    Raises:
      TransientError: On a retryable S3 fault. A throttled read is retried rather than being
        read as "no manifest", because silently skipping the integrity check on a throttle is
        the one way this tolerance could cost something.
    """
    key = f"{archive_root}{_manifest.BASENAME}"
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:  # noqa: BLE001 - an unreadable record is absent, never a failure
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        logger.info("no readable archive record at %s (%s)", key, err)
        return None
    try:
        recorded = json.loads(body).get("objectCount")
    except (AttributeError, ValueError) as err:
        logger.info("archive record at %s is not readable JSON (%s)", key, err)
        return None
    if not isinstance(recorded, int) or isinstance(recorded, bool):
        return None
    return recorded


def assert_complete(found: int, recorded, archive_id: str) -> None:
    """Cross-checks the listing against the record, when there is a record to check against.

    A disagreement can only fire when something is already wrong — nothing in this arc writes a
    manifest that disagrees with what it copied — which is the point of an integrity check
    rather than an argument against having one. It names both numbers, because "incomplete" with
    no figures gives an administrator nothing to go on.

    Args:
      found: How many objects the listing returned.
      recorded: The count ``_manifest.json`` recorded, or None when there is no record.
      archive_id: The archive id, for the refusal's detail.

    Returns:
      None.

    Raises:
      TerminalError: ``restore_archive_incomplete`` when the two counts disagree.
    """
    if recorded is None or recorded == found:
        return
    raise TerminalError(
        "restore_archive_incomplete",
        f"archive {archive_id} records {recorded} object(s) but holds {found}",
        tokens={"expected": str(recorded), "found": str(found)},
    )


def assert_found(objects: list, archive_id: str, space_name: str) -> None:
    """Refuses an archive prefix that holds nothing, without saying why it is empty.

    **It does not distinguish "never existed" from "belongs to someone else"**, the
    same no-existence-oracle rule the data-quality report view follows: the archive key's
    leading ``personal/``/``shared/`` segment and the space name are both derived from the
    REQUEST, so an id belonging to another space resolves to an empty prefix here and reads
    identically to one that was never used.

    Args:
      objects: The derived object set.
      archive_id: The archive id, named back to the user so they can check what they pasted.
      space_name: The space the request named.

    Returns:
      None.

    Raises:
      TerminalError: ``archive_not_found`` when the set is empty.
    """
    if objects:
        return
    raise TerminalError(
        "archive_not_found",
        f"no archive {archive_id} under {space_name}",
        tokens={"archiveId": archive_id, "spaceName": space_name},
    )
