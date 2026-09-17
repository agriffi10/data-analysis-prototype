"""inspect-source — resolves the validated selection into the copy plan.

Given the validated request: expands each selected item under the authorized source root, lists
folders through their pagination boundary, re-checks containment on every key the listing returns,
collapses overlapping selections, enforces the size caps and writes the plan to the admin bucket.
Read-only — nothing is copied and nothing is deleted here, and every rejection is a whole-request
terminal failure.

**Nothing it produces rides on the state.** At ``ARCHIVE_MAX_OBJECTS`` the object list is tens of
megabytes against a 256 KB payload limit, so the plan goes to S3 and its KEY is threaded onward
with the count and the byte total beside it. ``States.DataLimitExceeded`` escapes every ``Catch``
here (``States.ALL`` does not match it and none names it), which on this plane means a run that
deleted nothing and told nobody.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, plan
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    """Step Functions entry point: expands the selection and writes the copy plan.

    A thin shim; the orchestration lives below so it is testable without a Lambda context.
    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The validated request, carrying the authorized source, its normalised items and the
        resolved archive destination.
      context: The Lambda context, unused.

    Returns:
      The request merged with the copy plan's key, object count and byte total.

    Raises:
      TerminalError: The reused-id refusal, or any expansion or cap rejection — each notified to
        the actor before the Catch records it, except the reused id, which is told to nobody
        because the run that archived under that id reports.
      TransientError: On a retryable S3 fault.
    """
    return _inspect_source(event)


def _inspect_source(event) -> dict:
    """Expands the selection, enforces the caps and writes the plan.

    **The archive prefix is checked for occupancy BEFORE the expansion**, which is the cheapest
    order: the request id is browser-supplied and is the whole identity of an archive, so a reused
    one would mix two archives under one prefix and put the first one inside the second's rollback
    blast radius. One ``ListObjectsV2`` refuses that before a single ``HeadObject`` is spent.

    Args:
      event: The validated request.

    Returns:
      The request with the plan key, object count and byte total.

    Raises:
      TerminalError: ``request_id_reused`` when the archive prefix already holds objects,
        ``source_missing`` for a file that is no longer there, ``nothing_to_archive`` when the
        selection resolves to no objects, ``undeletable_folder`` for an object this plane could
        copy but could not delete, ``too_many_objects``, ``source_too_large`` or
        ``object_too_large`` at the caps, or ``forbidden`` from the containment re-check.
      TransientError: On a retryable S3 fault.
    """
    source = event.get("source") or {}
    actor = (event.get("actor") or {}).get("username")

    plan.assert_archive_unused(event)
    objects, total_bytes = plan.expand(source)

    logger.info(
        "copy plan for %s: %d objects, %d bytes from %d item(s)",
        actor,
        len(objects),
        total_bytes,
        len(source.get("items") or []),
    )
    observability.info(
        "copy plan built",
        actor=actor,
        source_bucket=source.get("bucket"),
        source_root=source.get("root"),
        space_kind=source.get("kind"),
        items=len(source.get("items") or []),
        objects=len(objects),
        bytes=total_bytes,
    )
    return {
        **event,
        "copyPlanKey": plan.write(event, source, actor, objects, total_bytes),
        "objectCount": len(objects),
        "totalBytes": total_bytes,
    }
