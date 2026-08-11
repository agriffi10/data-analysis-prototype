"""notify — the plane's only outcome producer.

The last state before ``Succeeded``. It reads the terminal summary SPEC-166 shapes and turns it
into messages: one to the sender per recipient outcome, and one to each recipient who actually
received something — a ``user`` directly, a ``space`` through its registered owner.

**ONE producer, not a decorator on each verb, and that is the difference from table share.** Its
guard, its collector and its create verb each notify from where they are, because they are the
only place their outcome is known. Here every per-recipient outcome reaches one flat list before
anything is said, so saying it once from one place is both possible and the only way to avoid
telling a sender twice about one conflict. It is also why nothing upstream on this plane emits.

**A failed recipient is the sender's business alone.** Somebody who was never reached is not told
that a send was attempted: they have no part in it, nothing to do about it, and being told would
leak that the sender tried.

**Nothing here can fail the request.** By the time this runs the copy has happened and the
execution is otherwise successful; every emit is best-effort and a raise would replace a
delivered send with a failed one. That is why it has no ``@notifies_on_failure`` — the decorator
would report a failure of the notifier as a failure of the send.

The service name is the control plane, not the function, so one send's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from fscommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")


@observability.traced("notify")
def handler(event, context) -> dict:
    """Step Functions entry point: tells the sender and every recipient what happened.

    ``@traced`` is the only decorator, for the reason in the module docstring.

    Args:
      event: The terminal summary — ``{requestId, sender, itemNames, objectCount, recipients}``.
      context: The Lambda context, unused.

    Returns:
      The summary, threaded onward unchanged, so the execution's output is still the terminal
      the machine shaped rather than whatever this verb happened to return.

    Raises:
      None.
    """
    return _notify(event)


def _notify(event) -> dict:
    """Emits one message per outcome, and one per recipient who received something.

    A summary with no recipients is a logged no-op rather than an error: it is not reachable
    through validate-authorize, which refuses an empty recipient list, and inventing a failure
    here would fail a send that had already worked.

    Args:
      event: The terminal summary.

    Returns:
      The summary, unchanged.

    Raises:
      None.
    """
    summary = event if isinstance(event, dict) else {}
    sender = summary.get("sender") or ""
    recipients = [r for r in (summary.get("recipients") or []) if isinstance(r, dict)]
    item_names = summary.get("itemNames") or []
    object_count = summary.get("objectCount") or 0

    if not sender or not recipients:
        logger.info("nothing to notify: sender=%r, %d recipient(s)", sender, len(recipients))
        observability.warning(
            "no outcome to notify",
            outcome="no-recipient",
            actor=sender,
            recipients=len(recipients),
            notified=False,
        )
        return summary

    for outcome in recipients:
        notify.emit_recipient_outcome(sender, outcome, item_names, object_count)

    delivered = sum(1 for outcome in recipients if outcome.get("status") == "ok")
    logger.info(
        "notified %s of %d outcome(s), %d delivered", sender, len(recipients), delivered
    )
    observability.info(
        "send outcomes notified",
        actor=sender,
        recipients=len(recipients),
        delivered=delivered,
        objects=object_count,
        notified=True,
    )
    return summary
