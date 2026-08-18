"""check-destination-clear — the absolute collision guard, and the last state before a bill.

Reads the restore plan back and refuses the whole restore if ANY destination is
already occupied. Read-only: it decides whether a retrieval may start, and never starts one.

**This is the state the restore guard exists for, and its position in the machine is the point.** Glacier
retrieval is billed and irreversible once initiated, so every question that can be answered in
seconds is answered here, before the retrieval spends hours and money on one that cannot be taken
back. A guard on the other side of the retrieval would report the same conflict and charge the
user for the privilege.

**the restore invokes this same verb a SECOND time, immediately before the copy**, and the two are
not redundant. The first is about the bill and the second is about the data: between them sit
three to five hours in which the user has been told a restore is in flight and has every reason
to be working in their own space. Re-creating a file in that window is the ordinary case this
guard exists for, arriving late — and with versioning off, one check at the start would let the
copy-back overwrite it silently and report success. **The ASL seeds which pass this is**, because
the two refusals leave the user in different positions: after the retrieval the objects stay
readable for ``RESTORE_AVAILABILITY_DAYS``, so a prompt second attempt costs neither the wait nor
the bill again.

**The refusal is whole-request, unlike file-send's per-recipient one.** There is one actor, one
archive and one destination space, so there is nothing to refuse partially — which is also why
it raises rather than returning a record: the colliding paths ride as a message TOKEN, which is
the channel that survives to the user, where a per-recipient outcome had to be a return value
because it had to be attributed to one of many.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import guard, notify, plan
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

#: Which pass this invocation is, and the reason code that words its refusal. **The stage is
#: SEEDED BY THE MACHINE, never inferred from what else is on the state** — "the retrieval has not
#: run" and "the retrieval reported nothing" look identical from inside a handler, and getting it
#: wrong here means telling a user their retrieval is still warm when it was never made.
_REASONS = {
    "before": "destination_occupied",
    "after": "destination_occupied_after_retrieval",
}


@observability.traced("check-destination-clear")
@notify.notifies_on_failure("check-destination-clear")
def handler(event, context) -> dict:
    """Step Functions entry point: confirms nothing the restore would write already exists.

    Args:
      event: The validated restore request, carrying the restore plan's key.
      context: The Lambda context, unused.

    Returns:
      The request, threaded onward unchanged apart from the checked count.

    Raises:
      TerminalError: ``destination_occupied`` naming a bounded sample of the collisions,
        ``plan_unreadable`` or ``plan_superseded`` when the plan is not this run's.
      TransientError: On a retryable S3 fault — a guard that cannot see the destination retries
        and then fails, and never falls through to "nothing is there".
    """
    return _check_destination_clear(event)


def _check_destination_clear(event) -> dict:
    """Loads the plan and heads every destination it names.

    Args:
      event: The validated restore request.

    Returns:
      The request with the number of destinations checked.

    Raises:
      TerminalError: ``destination_occupied``, ``plan_unreadable`` or ``plan_superseded``.
      TransientError: On a retryable S3 fault.
    """
    space = event.get("source") or {}
    archive = event.get("archive") or {}
    actor = (event.get("actor") or {}).get("username")
    bucket, root = space.get("bucket"), space.get("root")
    stage = (event.get("guard") or {}).get("stage")

    loaded = plan.load_restore_plan(event.get("planKey"), event)
    dest_keys = [entry["destKey"] for entry in loaded["objects"]]

    guard.assert_clear(bucket, dest_keys, root, _REASONS[stage])

    logger.info(
        "all %d destination(s) under %s are clear for %s (%s the retrieval)",
        len(dest_keys),
        root,
        actor,
        stage,
    )
    observability.info(
        "destinations clear",
        actor=actor,
        archive_id=archive.get("archiveId"),
        space_bucket=bucket,
        space_root=root,
        space_kind=space.get("kind"),
        objects=len(dest_keys),
        bytes=event.get("totalBytes"),
        stage=stage,
        exists=False,
    )
    return {**event, "checkedCount": len(dest_keys)}
