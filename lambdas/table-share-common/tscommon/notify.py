"""Best-effort outcome notifications for the table-share pipeline (domain side, SPEC-094).

The shared primitives (``emit_notification`` + the ``notifies_on_failure`` skeleton)
moved to ``cpcommon.notify`` (SPEC-107). This module keeps the table-share-specific
emitters: the SENDER (actor) hears every outcome (per-recipient success/failure + a
whole-request failure); on a recipient SUCCESS the target party is also told — a user
recipient directly, a shared-space recipient via the space's OWNER (from the registry;
owner only, never members). Failures notify the sender only (architecture §8). The
notifications queue has content-based dedup, so no per-message dedup id is needed.

A missed notification must never change or fail the share outcome, so every emit goes
through ``cpcommon.notify.emit_notification`` (catches and logs, never raises, no-op
when the queue URL is unset).
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

# Re-exported so verbs (and tests) can keep calling ``notify.emit_notification``.
__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_recipient_success",
    "emit_unexpected",
    "notifies_on_failure",
]


def _context(event) -> tuple[str, str, str, dict | None]:
    """(actor, source_table, table_name, recipient|None) from either event shape.

    Whole-request verbs carry the request at the top level; the Map verbs carry
    {recipient, request}. Tolerates a non-dict event (validate-authorize's raw SQS
    array) — no actor means every emit is a no-op, never an error.
    """
    data = event if isinstance(event, dict) else {}
    request = data.get("request") if isinstance(data.get("request"), dict) else data
    recipient = data.get("recipient") if isinstance(data.get("recipient"), dict) else None
    source = request.get("source") if isinstance(request.get("source"), dict) else {}
    return (
        request.get("actor") or "",
        source.get("table") or "",
        request.get("tableName") or "",
        recipient,
    )


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emit the sender-addressed failure notification for a verb's TerminalError.

    Best-effort. A Map-verb event names the failed recipient; a whole-request event
    does not. An unauthorized failure raised before the actor is bound has no
    recipient, so the emit is a no-op, not a lost message.
    """
    actor, source_table, table_name, recipient = _context(event)
    recipient = recipient or {}
    # err.detail (raw Athena StateChangeReason) is deliberately NOT forwarded to the
    # user message — it stays on the TerminalError for logs + the SFN record (FR-008).
    emit_notification(
        actor,
        failure_message(
            err.reason,
            source_table,
            kind=recipient.get("kind") or "",
            name=recipient.get("name") or "",
            table_name=table_name,
        ),
    )


def emit_unexpected(event, step: str) -> None:
    """Emit the sender-addressed failure notification for an UNEXPECTED verb exception.

    Best-effort; the generic "unexpected_error" reason (no leaked internals).
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
    """table-share ``notifies_on_failure`` — binds the domain emitters into the shared
    ``cpcommon.notify`` skeleton (SPEC-107).

    By default it also binds ``emit_failure`` so a verb's ``TerminalError`` notifies the
    sender at the decorator — the Map/whole-request worker verbs no longer need their own
    ``try/except TerminalError``. ``notify_terminal=False`` for validate-authorize, which
    notifies inside its own actor-aware orchestration (the sender isn't bound until after
    the token is verified)."""
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def emit_recipient_success(event: dict) -> None:
    """Emit both success notifications for one created recipient table (best-effort).

    Sender: the per-recipient "Shared … as …" outcome. Success target: a user
    recipient in their own inbox; a space recipient via the space's registry
    ``owner`` — skipped (one log line) when the record or its owner can't be resolved,
    without affecting the sender's message (FR-002).
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
    except Exception:  # owner lookup is best-effort (FR-002)
        logger.exception("owner lookup failed for space %s; skipping owner notification", name)
        return
    if not owner:
        logger.info("space %s has no resolvable owner; skipping owner notification", name)
        return
    emit_notification(owner, space_owner_message(actor, table_name, name))
