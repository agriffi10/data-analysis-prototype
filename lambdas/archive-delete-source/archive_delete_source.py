"""delete-source — the only verb in this portal that deletes a user's data.

It runs on one branch of the commit gate and is unreachable from the other: by the time it is
invoked, every object in the plan has been confirmed present in the vault and the integrity record
has been written. What it deletes is exactly the plan — the same list the manifest was built from
— so an object that was never copied is also never deleted.

**``DeleteObjects`` returns HTTP 200 with a per-item ``Errors`` array**, and a response inspected
only by its status code is the defect the DDL discipline fixed elsewhere in this repo. Here that defect
would report a completed archive over a source that is still half there, and the user would be
told their files had moved when some of them had not. ``arcommon.delete`` reads the array, attempts
every batch before reporting, and returns counts rather than keys.

**A partial deletion is a terminal failure and the archive copy is KEPT.** The user's data then
exists in two places, which is recoverable by hand; the alternative — removing the archive after a
partial source deletion — is not recoverable at all.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import delete, notify, plan
from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("delete-source")
@notify.notifies_on_failure("delete-source")
def handler(event, context) -> dict:
    """Step Functions entry point: deletes the archived originals from the user's space.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the copy plan's key and the authorized source.
      context: The Lambda context, unused.

    Returns:
      The request with how many objects were deleted.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the plan cannot be read
        back or is not this run's — the second is what stops a run deleting a DIFFERENT
        selection after another execution overwrote the plan under a reused request id —
        ``source_delete_incomplete`` when any object survived, or ``forbidden`` /
        ``protected_marker`` from the pre-delete assertion, which fails the run BEFORE issuing
        a delete the bucket policy would refuse mid-batch.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because an already-absent key is not an error and a re-driven execution completes.
    """
    return _delete_source(event)


def _delete_source(event) -> dict:
    """Rebuilds the source keys from the plan and deletes them.

    The keys are rebuilt from the plan's relative keys and the source root rather than stored
    absolute, which keeps the plan half the size it would otherwise be at the object cap — and
    means the root a key is deleted under is the same root the archive destination was built
    from.

    Args:
      event: The request with its copy plan key.

    Returns:
      The request with ``deletedCount``.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded``, ``source_delete_incomplete``,
        ``forbidden`` or ``protected_marker``.
      TransientError: On a retryable S3 fault.
    """
    loaded = plan.load(event.get("copyPlanKey"), event)
    source = loaded["source"]
    root = normalize_root(source["root"])
    keys = [f"{root}{entry['relKey']}" for entry in loaded["objects"]]

    removed = delete.delete_keys(source["bucket"], keys, root)

    logger.info("deleted %d of %d source object(s)", removed["deleted"], len(keys))
    observability.info(
        "source deleted",
        actor=(event.get("actor") or {}).get("username"),
        source_bucket=source["bucket"],
        source_root=root,
        objects=removed["deleted"],
        failed=removed["failed"],
    )

    if removed["failed"]:
        raise TerminalError(
            "source_delete_incomplete",
            f"{removed['failed']} of {len(keys)} source object(s) could not be deleted; the "
            "archive copy was kept",
            tokens={"failed": str(removed["failed"]), "total": str(len(keys))},
        )
    return {**event, "deletedCount": removed["deleted"]}
