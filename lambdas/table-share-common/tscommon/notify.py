"""Best-effort outcome notifications for the table-share pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the table-share
specifics. The sender hears every outcome — per-recipient successes and failures, plus a
whole-request failure. On a recipient success the target party is also told: a user recipient
directly, a shared-space recipient via the space's owner, never its members. Failures notify
the sender only. The notifications queue has content-based dedup, so no per-message dedup id
is needed.

A missed notification must never change or fail the share outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.
"""

import logging

from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
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
    "emit_recipient_success",
    "emit_unexpected",
    "notifies_on_failure",
]


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
    nested = data.get("request")
    request = nested if isinstance(nested, dict) else data
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


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the sender-addressed failure notification for a verb's terminal error.

    The error's detail — raw Athena text — is deliberately not forwarded to the user message;
    it stays on the exception for logs and the SFN record. Its tokens are the opposite channel
    and are forwarded, because they exist to fill the markers in a body.

    Args:
      event: The verb's event. A Map-verb event names the failed recipient; a whole-request
        event does not.
      err: The terminal error being reported.
      step: The verb name, unused here because this queue deduplicates on content.

    Returns:
      None. An unauthorized failure raised before the actor is bound has no recipient, so the
      emit is a no-op rather than a lost message.

    Raises:
      None.
    """
    actor, source_table, table_name, recipient = _context(event)
    recipient = recipient or {}
    emit_notification(
        actor,
        failure_message(
            err.reason,
            source_table,
            kind=recipient.get("kind") or "",
            name=recipient.get("name") or "",
            table_name=table_name,
            tokens=err.tokens,
        ),
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the sender-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because this queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    actor, source_table, _table_name, recipient = _context(event)
    recipient = recipient or {}
    emit_notification(
        actor,
        failure_message(
            "unexpected_error",
            source_table,
            kind=recipient.get("kind") or "",
            name=recipient.get("name") or "",
        ),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds table-share's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator, so the Map and
        whole-request worker verbs need no ``try/except`` of their own. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because the
        sender is not bound until the token is verified.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def emit_recipient_success(event: dict) -> None:
    """Emits both success notifications for one created recipient table.

    The sender gets the per-recipient outcome. The success target gets its own: a user
    recipient in their inbox, a space recipient via the space's registered owner.

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

    emit_notification(actor, success_message(source_table, kind, name, table_name))

    if kind == "user":
        emit_notification(name, recipient_user_message(actor, table_name, recipient.get("database") or name))
        return
    try:
        owner = (reg.load(name) or {}).get("owner") or ""
    except Exception:
        logger.exception("owner lookup failed for space %s; skipping owner notification", name)
        return
    if not owner:
        logger.info("space %s has no resolvable owner; skipping owner notification", name)
        return
    emit_notification(owner, space_owner_message(actor, table_name, name))
