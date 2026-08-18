"""delete-archived — the vault swept after a restore, and the one deletion that may fail quietly.

Reached on the one arm of the restore's gate where every object came back: the
archive has served its purpose, the user's data is in their space again, and the prefix — its
``_manifest.json`` included — is removed.

**A failed cleanup does NOT fail the restore.** This is the exact inverse of the archive's
delete-source, and the asymmetry is the point of both. There, a half-deleted source meant a user
told their archive completed while their files were still half there, so it is a terminal
failure. Here the outcome the user asked for has already happened: their data is back. Residue in
the vault costs storage and nothing else — it is unreachable by the browser, and the bucket's
7-year expiry sweeps it — so it is reported as a flag on a successful run rather than turned into
a failure the user can do nothing about.

**It lists rather than taking keys from the plan**, the rollback's reason: the prefix is this
archive's alone, so everything under it belongs to this archive, including anything the copy
wrote that no record mentions. A plan-driven deletion would leave exactly those.

**Deleting inside the GLACIER 90-day minimum storage duration is expected and is charged as an
early-deletion fee.** An archive made on Monday and restored on Friday is still billed for 90
days of storage, and deleting it on Friday brings that charge forward rather than avoiding it.
It is recorded here so a later cost investigation does not read the line item as a defect —
The config docstring is where the 90-day minimum itself is reasoned about.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import delete, notify
from cpcommon import observability, s3_listing

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


def _keep_everything(key: str, size: int, prefix: str) -> bool:
    """Ignores nothing, so the sweep lists every object the archive holds.

    The shared paginator's default predicate drops zero-byte objects and hidden segments, and an
    archive deliberately carries both — a folder placeholder is how an empty folder survives, and
    ``_manifest.json`` is hidden by that rule too. A sweep that inherited the default would leave
    exactly the objects this plane wrote.

    Args:
      key: The absolute object key, unused.
      size: The object's byte size, unused.
      prefix: The listing prefix, unused.

    Returns:
      False, always.

    Raises:
      None.
    """
    del key, size, prefix
    return False


@observability.traced("delete-archived")
@notify.notifies_on_failure("cleanup")
def handler(event, context) -> dict:
    """Step Functions entry point: removes the restored archive from the vault.

    ``@notifies_on_failure`` is present for the faults this verb does not swallow — a transient
    S3 error exhausting its Retry, say — and not for the ordinary partial deletion, which is
    reported as a flag rather than raised.

    Args:
      event: The request, carrying the archive location and the restore's verdict.
      context: The Lambda context, unused.

    Returns:
      The request with a ``cleanup`` block: how many objects went, how many did not, and the
      ``cleanupIncomplete`` flag the success terminal carries.

    Raises:
      TerminalError: ``forbidden`` or ``protected_marker`` from the pre-issue check, which on
        this prefix means the listing returned something that is not this archive's — a shape no
        legal run produces.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because deleting an already-absent key is not an error.
    """
    return _delete_archived(event)


def _delete_archived(event) -> dict:
    """Lists the archive prefix, deletes what is under it and reports what it could not.

    Args:
      event: The request with its archive location.

    Returns:
      The request with its ``cleanup`` block.

    Raises:
      TerminalError: ``forbidden`` or ``protected_marker``.
      TransientError: On a retryable S3 fault.
    """
    archive = event.get("archive") or {}
    bucket, root = archive.get("bucket"), archive.get("root")

    keys = [key for key, _ in s3_listing.list_data_objects(bucket, root, ignore=_keep_everything)]
    removed = delete.delete_keys(bucket, keys, root)

    logger.info("swept %d of %d archived object(s) after the restore", removed["deleted"], len(keys))
    observability.info(
        "archive swept",
        actor=(event.get("actor") or {}).get("username"),
        archive_id=archive.get("archiveId"),
        objects=removed["deleted"],
        residue=removed["failed"],
        expected=len(keys),
    )
    return {
        **event,
        "cleanup": {
            "deleted": removed["deleted"],
            "residue": removed["failed"],
            "cleanupIncomplete": bool(removed["failed"]),
        },
    }
