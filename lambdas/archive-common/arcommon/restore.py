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

Attributes:
  ALLOWED_FIELDS: The complete set of top-level fields a RESTORE request may carry. It is a
    different set from the archive request's — ``space`` and ``archiveId`` in place of
    ``source`` — which is why the unknown-field check is made per mode rather than once: a
    single union would accept a restore carrying a selection and an archive naming an archive
    id, and quietly ignore whichever the mode did not use.
"""

import json
import logging

from cpcommon import clients, errors, events, s3_listing
from cpcommon.errors import TerminalError

from . import manifest as _manifest
from . import (
    messages,  # noqa: F401
    paths,
)
from .authz import authorize_source
from .config import archive_bucket

logger = logging.getLogger()

ALLOWED_FIELDS = frozenset({"requestId", "mode", "actor", "space", "archiveId"})


def validate(req: dict, request_id: str, actor: str) -> dict:
    """Validates a restore request and resolves the archive it names.

    The archive id is checked against the strict UUID pattern **before** it is concatenated into
    anything, and the archive root is then built by ``paths.archive_root`` — the same function
    The archive uses the same builder to WRITE it, so the read and the write cannot drift.

    **``requestId`` and ``archiveId`` must be different values** (FR-001 AC2). Conflating them was
    the obvious shortcut and is wrong in both directions: a refused restore must be re-submittable
    under a new run id, and a second attempt at one archive is a new request rather than a
    duplicate of the first. It is refused rather than tolerated, because a producer that has
    conflated them will do it on every request and the symptom would surface only under a retry.

    Args:
      req: The parsed request body, already known to be an object carrying a request id, a mode
        and an actor token.
      request_id: The validated request id for THIS run.
      actor: The verified username, from the ID token claim and nowhere else.

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
        },
    }


def derive_destinations(bucket: str, archive_root: str, space_root: str) -> tuple:
    """Lists an archive and rebuilds every destination it would write back.

    Pagination is ``cpcommon.s3_listing``'s — the same paginator the expansion and the rollback
    use, and the third listing of this same prefix — with a predicate of this plane's own. The
    DEFAULT predicate is what must not be reused: it drops zero-byte objects, hidden segments and
    folder keys, and every one of those is something this archive deliberately CARRIED (the expansion's
    ``_excluder`` keeps what the others drop, so an archived empty folder comes back). Restoring
    through a filter the archive did not write through would silently return less than was taken.
    That is exactly the split the send plane recorded: the pagination is shared, the exclusions are not.

    ``_manifest.json`` is excluded by its EXACT KEY at the archive root, never by basename: a
    user's own ``reports/_manifest.json`` three folders down was archived like any other file
    and must come back, while the record this plane wrote must not land in the user's space as a
    stray file (FR-003 AC2).

    Args:
      bucket: The archive bucket.
      archive_root: The archive prefix, ending in a slash.
      space_root: The authorized space root the objects are restored into.

    Returns:
      ``(objects, total_bytes)``, each object carrying its archive key, its destination key and
      its size. The size rides so the restore can tell the user how much is coming back and
      SPEC-171 can bound its wait.

    Raises:
      TerminalError: ``forbidden`` from the destination reconstruction.
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb.
    """
    record_key = f"{archive_root}{_manifest.BASENAME}"

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
        return key == record_key

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

    **Absent is not a failure** (FR-003 AC5). The manifest is not load-bearing, and a restore
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

    **It does not distinguish "never existed" from "belongs to someone else"** (FR-003 AC3), the
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
