"""inspect-source — resolves the validated selection into a copy plan.

Given the validated request: expands each selected item under the authorized source root,
lists folders through their pagination boundary, applies this plane's exclusions, refuses a
selection that cannot be laid out, enforces the size caps, and writes the plan to S3.
Read-only, with no copy side effects. Every rejection is a whole-request terminal failure, so
no recipient runs.

**Nothing it produces rides on the state.** At ``SEND_MAX_OBJECTS`` the object list is tens of
megabytes against a 256 KB payload limit, so the plan goes to the admin bucket and its key is
threaded onward — the same indirection, for the same reason, as table-share's plan and
data-quality's manifest. What stays on the state is the count and the byte total, which is what
an operator needs to tell a send that was too large from one that was mis-scoped.

The service name is the control plane, not the function, so one send's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from fscommon import copy_plan, expand, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    """Step Functions entry point: expands the selection and writes the copy plan.

    A thin shim; the orchestration lives below so it is testable without a Lambda context.
    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The validated request, carrying the authorized source and its normalised items.
      context: The Lambda context, unused.

    Returns:
      The request merged with the copy plan key, object count and byte total.

    Raises:
      TerminalError: Any expansion, layout or cap rejection. It is a whole-request failure, so
        no recipient runs, and the sender is notified before the Catch records it.
      TransientError: On a retryable S3 fault.
    """
    return _inspect_source(event)


def _inspect_source(event) -> dict:
    """Expands the selection, enforces the caps and writes the plan.

    Every cap is enforced inside the expansion, before the write, so a refused send leaves
    nothing behind.

    Args:
      event: The validated request.

    Returns:
      The request merged with the plan key, object count and byte total.

    Raises:
      TerminalError: ``overlapping_items`` or ``colliding_item_names`` for a selection that
        cannot be laid out, ``source_missing`` for a file that is no longer there,
        ``nothing_to_send`` when the selection resolves to no objects, ``too_many_objects`` or
        ``source_too_large`` at the caps, or a containment reason from the listing re-check.
      TransientError: On a retryable S3 fault.
    """
    source = event.get("source") or {}
    sender = (event.get("actor") or {}).get("username")

    objects, total_bytes = expand.expand(source)

    logger.info(
        "copy plan for %s: %d objects, %d bytes from %d item(s)",
        sender,
        len(objects),
        total_bytes,
        len(source.get("items") or []),
    )
    observability.info(
        "copy plan built",
        actor=sender,
        source_bucket=source.get("bucket"),
        source_root=source.get("root"),
        items=len(source.get("items") or []),
        objects=len(objects),
        bytes=total_bytes,
    )
    return {
        **event,
        "copyPlanKey": copy_plan.write(event, source, sender, objects, total_bytes),
        "objectCount": len(objects),
        "totalBytes": total_bytes,
    }
