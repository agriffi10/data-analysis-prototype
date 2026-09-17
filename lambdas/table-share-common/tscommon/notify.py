"""Best-effort outcome notifications for the table-share pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the table-share
specifics. The sender hears every outcome — per-recipient successes and failures, plus a
whole-request failure. On a recipient success the target party is also told: a user recipient
directly, a shared-space recipient via the space's owner, never its members. Failures notify
the sender only.

**Every notice carries a dedup id naming its run**, because a body here names the source, the
recipient and the result table and nothing about the run, and the queue deduplicates an id-less
send on its body: two shares of one table by one user that ended alike inside five minutes were
delivered once. Table-share has no request id, so the run is the execution's name (``run_of``),
and the rest of the id is the outcome and the addressee it concerns. A failure's id carries its
REASON, not just ``failure``: the verb decorator's unexpected-error notice and notify-failure's
engine-error notice are worded differently and both sent today, and an id shared between them would
merge them. Within one run two failure notices therefore collapse only when they share a reason and
a recipient, and a retry composes the same id. A token rather than a payload, because a success's
payload would put the sender's run in a recipient's or a space owner's inbox, and a token never
leaves the queue.

A missed notification must never change or fail the share outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.
"""

import logging

from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from cpcommon.messages import UNEXPECTED_ERROR
from cpcommon.notify import dedup_id, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import (
    failure_message,
    recipient_user_message,
    space_owner_message,
    success_message,
)

logger = logging.getLogger()

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_recipient_failure",
    "emit_recipient_success",
    "emit_unexpected",
    "failure_dedup_id",
    "notifies_on_failure",
    "run_of",
]


def _request(event) -> dict:
    """Returns the share request out of either event shape a notifier holds.

    Whole-request verbs and the recorded failure carry the request at the top level; the Map
    verbs and create-table carry it under ``request``, beside the recipient.

    Args:
      event: The verb's event, of any shape.

    Returns:
      The request, or an empty dict for a non-dict event.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    nested = data.get("request")
    return nested if isinstance(nested, dict) else data


def run_of(event) -> str | None:
    """Reads the name of the execution a table-share notice is about.

    It is the plane's only run identity, since the API body carries no request id. The machine
    stamps it onto the state as ``execution.name`` directly after validate-authorize, so every
    later verb holds it, and the recorded failure copies it from the context object, so the
    notifier holds it even where the error replaced the state. validate-authorize runs before any
    state exists to carry it and passes the SQS message id instead.

    Args:
      event: A verb's event, a Map item, create-table's payload or the recorded failure.

    Returns:
      The execution name, or None when the event carries no usable one, which leaves the notice to
      the queue's content dedup exactly as it was.

    Raises:
      None.
    """
    execution = _request(event).get("execution")
    name = execution.get("name") if isinstance(execution, dict) else None
    return name if isinstance(name, str) and name else None


def failure_dedup_id(run: str | None, reason: str, kind: str = "", name: str = "") -> str | None:
    """Composes the dedup id of a failure notice, for every failure door on this plane.

    The reason is part of the id, which is what keeps two notices one run sends on purpose apart:
    a verb's unexpected fault is told by its decorator as ``unexpected_error`` and again by
    notify-failure under the engine's error name, in different words. The recipient is part of it
    too, so one run's refusals of two recipients stay two notices.

    Args:
      run: The run's identity, from ``run_of`` or validate-authorize's message id.
      reason: The terminal reason the notice reports.
      kind: The recipient kind, for a per-recipient failure.
      name: The recipient's name, for a per-recipient failure.

    Returns:
      ``{run}:failure:{reason}``, with ``:{kind}:{name}`` for a per-recipient failure, or None with
      no run.

    Raises:
      None.
    """
    recipient = f":{kind}:{name}" if kind or name else ""
    return dedup_id(run, f"failure:{reason}{recipient}")


def _context(event) -> tuple[str, str, str, dict | None]:
    """Reads the notification context out of either event shape a verb can receive.

    Whole-request verbs carry the request at the top level; the Map verbs carry the recipient
    alongside it.

    Args:
      event: The verb's event. A non-dict is tolerated — validate-authorize's raw SQS array
        fails before the actor is bound — and yields no actor, so every emit is a no-op rather
        than an error.

    Returns:
      An ``(actor, source table, result table name, recipient or None)`` tuple.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    request = _request(event)
    candidate = data.get("recipient")
    recipient = candidate if isinstance(candidate, dict) else None
    declared = request.get("source")
    source = declared if isinstance(declared, dict) else {}
    return (
        request.get("actor") or "",
        source.get("table") or "",
        request.get("tableName") or "",
        recipient,
    )


def emit_failure(event, err: TerminalError, step: str, *, run: str | None = None) -> None:
    """Emits the sender-addressed failure notification for a verb's terminal error.

    The error's detail — raw Athena text — is deliberately not forwarded to the user message;
    it stays on the exception for logs and the SFN record. Its tokens are the opposite channel
    and are forwarded, because they exist to fill the markers in a body.

    Args:
      event: The verb's event. A Map-verb event names the failed recipient; a whole-request
        event does not.
      err: The terminal error being reported.
      step: The verb name, unused here because the id names the reason rather than the verb.
      run: The run's identity, for a caller whose event carries no execution name —
        validate-authorize, which passes its SQS message id. Read from the event when omitted.

    Returns:
      None. An unauthorized failure raised before the actor is bound has no recipient, so the
      emit is a no-op rather than a lost message.

    Raises:
      None.
    """
    actor, source_table, table_name, recipient = _context(event)
    recipient = recipient or {}
    kind, name = recipient.get("kind") or "", recipient.get("name") or ""
    emit_notification(
        actor,
        failure_message(
            err.reason,
            source_table,
            kind=kind,
            name=name,
            table_name=table_name,
            tokens=err.tokens,
        ),
        dedup_id=failure_dedup_id(run_of(event) if run is None else run, err.reason, kind, name),
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the sender-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the id names the reason rather than the verb.

    Returns:
      None.

    Raises:
      None.
    """
    actor, source_table, _table_name, recipient = _context(event)
    recipient = recipient or {}
    kind, name = recipient.get("kind") or "", recipient.get("name") or ""
    emit_notification(
        actor,
        failure_message(UNEXPECTED_ERROR, source_table, kind=kind, name=name),
        dedup_id=failure_dedup_id(run_of(event), UNEXPECTED_ERROR, kind, name),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds table-share's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator, so the Map and
        whole-request worker verbs need no ``try/except`` of their own. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because the
        sender is not bound until the identity block is read.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def emit_recipient_failure(request: dict, kind: str, name: str, reason: str) -> None:
    """Emits the sender-addressed failure notification for one recipient, from a collector.

    Every other per-recipient failure notification comes from the failing verb's own decorator,
    which holds both the recipient and the error. A copy failure no longer has such a verb:
    The batch copier runs over a mixed batch of recipients' objects and succeeds while
    reporting them, so the recipient is only known once the Map Run's results are attributed.
    Without this the copy failure would be the one outcome that told the sender nothing.

    Args:
      request: The share request, carrying the actor, source, result name and execution name.
      kind: The recipient kind.
      name: The recipient's name.
      reason: The terminal reason code for this recipient.

    Returns:
      None.

    Raises:
      None.
    """
    source = request.get("source") if isinstance(request.get("source"), dict) else {}
    emit_notification(
        request.get("actor") or "",
        failure_message(
            reason,
            (source or {}).get("table") or "",
            kind=kind,
            name=name,
            table_name=request.get("tableName") or "",
        ),
        dedup_id=failure_dedup_id(run_of(request), reason, kind, name),
    )


def emit_recipient_success(event: dict) -> None:
    """Emits both success notifications for one created recipient table.

    The sender gets the per-recipient outcome. The success target gets its own: a user
    recipient in their inbox, a space recipient via the space's registered owner. Each id names
    the run, the side and the recipient — ``sent:{kind}:{name}`` and ``received:{kind}:{name}`` —
    so a re-share delivered alike is told again, a retry is not, and one owner told of two spaces,
    or a sender who is also the recipient, keeps every notice.

    Args:
      event: The Map verb's event, carrying the request and the recipient.

    Returns:
      None. The owner notification is skipped with one log line when the record or its owner
      cannot be resolved, without affecting the sender's message.

    Raises:
      None.
    """
    actor, source_table, table_name, recipient = _context(event)
    recipient = recipient or {}
    kind, name = recipient.get("kind") or "", recipient.get("name") or ""
    run = run_of(event)
    received = dedup_id(run, f"received:{kind}:{name}")

    emit_notification(
        actor,
        success_message(source_table, kind, name, table_name),
        dedup_id=dedup_id(run, f"sent:{kind}:{name}"),
    )

    if kind == "user":
        emit_notification(
            name,
            recipient_user_message(actor, table_name, recipient.get("database") or name),
            dedup_id=received,
        )
        return
    try:
        owner = (reg.load(name) or {}).get("owner") or ""
    except Exception:
        logger.exception("owner lookup failed for space %s; skipping owner notification", name)
        return
    if not owner:
        logger.info("space %s has no resolvable owner; skipping owner notification", name)
        return
    emit_notification(owner, space_owner_message(actor, table_name, name), dedup_id=received)
