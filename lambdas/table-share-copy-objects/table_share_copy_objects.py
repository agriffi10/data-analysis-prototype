"""copy-objects — the recipient Map's data copy (SPEC-091).

For one (conflict-cleared) recipient: server-side-copy every planned object from
the source location to {recipient}/shared_tables/{tableName}/{relKey}, layout
preserved (flat files and key=value/ partition dirs land identically), with a
bounded parallel pool and multipart copy for objects over S3's 5 GiB single-copy
limit (tscommon.copy). Idempotent: a Step Function retry re-copies the same keys
harmlessly — check-target-absent already guaranteed the destination held no
foreign data. No object bytes pass through the Lambda.
"""

import logging

from cpcommon import observability
from tscommon import copy as copy_mod
from tscommon import copy_plan, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share is five invocations (plus a
# recipient Map fan-out), and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field.
observability.init(service="table-share")


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("copy-objects")
@notify.notifies_on_failure("copy")
def handler(event, context) -> dict:
    """Recipient-Map entry point: copy the source objects into the recipient's prefix.

    Server-side ``CopyObject`` (multipart >5 GiB, layout-preserving). A terminal copy
    failure notifies the sender before the per-recipient ``Catch`` records it (SPEC-094,
    best-effort); a ``TransientError`` propagates for the SFN ``Retry``.
    """
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    location = request.get("location") or {}
    # Loaded by POINTER — the list is far too large to ride on the Map's state. The inline
    # fallback covers the ROLLING-DEPLOY WINDOW only: the five verbs deploy as parallel
    # matrix jobs, so an execution that cleared InspectSource under the old code carries
    # `objects` and no key, and without this every one of its recipients would fail on a
    # None key. Removable once no pre-pointer execution can still be in flight.
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
    # PER RECIPIENT, never per object. This verb runs inside the SFN's recipient Map, so it is
    # already once per recipient — and a folder can hold thousands of objects, each of which
    # would be an SQS message and a line in a day object the sweep rewrites in full.
    observability.info(
        "objects copied",
        recipient=recipient.get("name"),
        dest_bucket=recipient.get("destBucket"),
        dest_prefix=recipient.get("destPrefix"),
        objects=copied,
    )
    return {"recipient": recipient, "request": request, "copiedObjects": copied}
