"""copy-objects — the recipient Map's data copy.

For one conflict-cleared recipient: server-side-copies every planned object from the source
location into the recipient's own shared-tables prefix, layout preserved, with a bounded
parallel pool and multipart copy for objects over S3's single-copy limit. Idempotent — a Step
Function retry re-copies the same keys harmlessly, because check-target-absent already
guaranteed the destination held no foreign data. No object bytes pass through the Lambda.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from tscommon import copy as copy_mod
from tscommon import copy_plan, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


@observability.traced("copy-objects")
@notify.notifies_on_failure("copy")
def handler(event, context) -> dict:
    """Recipient-Map entry point: copies the source objects into the recipient's prefix.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    The plan is loaded by pointer, because the object list is far too large to ride on the
    Map's state. The inline fallback covers the rolling-deploy window only: the verbs deploy as
    parallel matrix jobs, so an execution that cleared inspect-source under the old code
    carries the list itself and no key, and without the fallback every one of its recipients
    would fail on a missing key. Removable once no pre-pointer execution can still be in flight.

    The copy is recorded per recipient, never per object. This verb already runs once per
    recipient inside the Map, and a folder can hold thousands of objects, each of which would
    otherwise be an SQS message and a line in a day object the sweep rewrites in full.

    Args:
      event: The Map item, carrying the recipient and the request.
      context: The Lambda context, unused.

    Returns:
      The recipient, the request, and the number of objects copied.

    Raises:
      TerminalError: ``copy_failed`` on a deterministic copy fault, notified to the sender
        before the per-recipient Catch records it.
      TransientError: On a retryable fault, passed through for the SFN Retry.
    """
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    location = request.get("location") or {}
    plan_key = request.get("copyPlanKey")
    objects = copy_plan.load(plan_key) if plan_key else (request.get("objects") or [])

    copied = copy_mod.copy_prefix(
        src_bucket=location.get("bucket"),
        src_prefix=location.get("prefix"),
        objects=objects,
        dest_bucket=recipient.get("destBucket"),
        dest_prefix=recipient.get("destPrefix"),
    )
    logger.info(
        "copied %d objects to %s/%s",
        copied,
        recipient.get("destBucket"),
        recipient.get("destPrefix"),
    )
    observability.info(
        "objects copied",
        recipient=recipient.get("name"),
        dest_bucket=recipient.get("destBucket"),
        dest_prefix=recipient.get("destPrefix"),
        objects=copied,
    )
    return {"recipient": recipient, "request": request, "copiedObjects": copied}
