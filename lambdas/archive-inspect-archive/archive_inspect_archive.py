"""inspect-archive — what a restore would write back, and where.

the restore arm's counterpart to inspect-source. Lists the archive prefix,
rebuilds each object's destination, cross-checks the count against ``_manifest.json`` when there
is one, and writes the restore plan to the admin bucket. Read-only against both buckets: it
decides what a restore WOULD do and starts nothing.

**It does not read the manifest to find out what to restore.** The archived key encodes its own
origin, so one ``ListObjectsV2`` yields both the objects and their destinations — which is what
makes a restore work when the record is gone and refuse when the record disagrees. Reversing
that dependency would make a convenience document load-bearing, and it is written as a report
precisely so it never would be.

**Nothing it produces rides on the state.** At ``ARCHIVE_MAX_OBJECTS`` the plan is tens of
megabytes against a 256 KB payload limit, and ``States.DataLimitExceeded`` escapes every
``Catch`` — which on this plane is a run that told the user nothing at all. What comes back is
the plan's KEY plus the count and the byte total.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, plan, restore
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("inspect-archive")
@notify.notifies_on_failure("inspect-archive")
def handler(event, context) -> dict:
    """Step Functions entry point: resolves what the restore would write back.

    Args:
      event: The validated restore request.
      context: The Lambda context, unused.

    Returns:
      The request with the restore plan's key, the object count and the byte total.

    Raises:
      TerminalError: ``archive_not_found`` for an empty prefix,
        ``restore_archive_incomplete`` when the record disagrees with the listing, or
        ``forbidden`` when an archived key cannot be reconstructed into a destination.
      TransientError: On a retryable S3 fault.
    """
    return _inspect_archive(event)


def _inspect_archive(event) -> dict:
    """Lists the archive, derives destinations, cross-checks and writes the plan.

    The order is the cheap-refusal order: an archive that is not there costs one listing and no
    manifest read, and the count cross-check happens before the plan is written so a damaged
    archive leaves nothing behind in the admin bucket.

    Args:
      event: The validated restore request.

    Returns:
      The request with the plan key, object count and byte total.

    Raises:
      TerminalError: ``archive_not_found``, ``restore_archive_incomplete`` or ``forbidden``.
      TransientError: On a retryable S3 fault.
    """
    archive = event.get("archive") or {}
    space = event.get("source") or {}
    actor = (event.get("actor") or {}).get("username")
    bucket, archive_root = archive.get("bucket"), archive.get("root")

    objects, total_bytes = restore.derive_destinations(bucket, archive_root, space.get("root"))
    restore.assert_found(objects, archive.get("archiveId"), space.get("name"))

    recorded = restore.read_recorded_count(bucket, archive_root)
    restore.assert_complete(len(objects), recorded, archive.get("archiveId"))

    logger.info(
        "restore plan for %s: %d objects, %d bytes from %s (record %s)",
        actor,
        len(objects),
        total_bytes,
        archive_root,
        "present" if recorded is not None else "absent",
    )
    observability.info(
        "restore plan built",
        actor=actor,
        archive_id=archive.get("archiveId"),
        archive_root=archive_root,
        space_bucket=space.get("bucket"),
        space_root=space.get("root"),
        space_kind=space.get("kind"),
        objects=len(objects),
        bytes=total_bytes,
        manifest_present=recorded is not None,
    )
    return {
        **event,
        "planKey": plan.write_restore_plan(event, actor, objects, total_bytes),
        "objectCount": len(objects),
        "totalBytes": total_bytes,
        "manifestPresent": recorded is not None,
    }
