"""Best-effort outcome notifications for the table-builder pipeline (domain side).

The shared primitives (``emit_notification`` + the ``notifies_on_failure`` skeleton)
moved to ``cpcommon.notify`` (SPEC-107). This module keeps the table-builder-specific
emitters: the actor is always the recipient (no fan-out); FIFO dedup id is
``{requestId}:{step}``; failure/success wording comes from ``tbcommon.messages``.

Each verb Lambda emits one "create" notification at its terminal branch — a failure
message when it raises ``TerminalError``, a success message when execute-ddl creates
the table. A missed notification must never change or fail the pipeline outcome, so
every emit goes through ``cpcommon.notify.emit_notification`` (catches and logs, never
raises, no-op when the queue URL is unset).
"""

from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import failure_message, success_message

# Re-exported so verbs (and tests) can keep calling ``notify.emit_notification``.
__all__ = ["emit_created", "emit_failure", "emit_notification", "emit_unexpected", "notifies_on_failure"]


def _dedup(request_id: str, step: str) -> str | None:
    """FIFO dedup id "{requestId}:{step}"; None without a requestId (content dedup)."""
    return f"{request_id}:{step}" if request_id else None


def emit_failure(event: dict, err: TerminalError, step: str) -> None:
    """Emit the actor-addressed failure notification for a verb's TerminalError.

    Best-effort. Reads the actor/table/database/requestId from the validated event.
    An unauthorized failure raised before the actor is bound has no recipient, so the
    emit is a no-op, not a lost message.
    """
    space = event.get("space") or {}
    # err.detail (raw Athena StateChangeReason) is deliberately NOT forwarded to the
    # user message — it stays on the TerminalError for logs + the SFN record (FR-008).
    emit_notification(
        event.get("actor", ""),
        failure_message(err.reason, event.get("tableName", ""), space.get("database", "")),
        dedup_id=_dedup(event.get("requestId"), step),
    )


def emit_unexpected(event, step: str) -> None:
    """Emit the actor-addressed failure notification for an UNEXPECTED verb exception.

    Best-effort. Uses the generic "unexpected_error" reason (no leaked internals) and
    reads the actor/table/database/requestId from the running request. Tolerates a
    non-dict event (e.g. validate-authorize's raw SQS array, whose failures happen
    before the actor is bound): there is no recipient, so the emit is a no-op.
    """
    data = event if isinstance(event, dict) else {}
    space = data.get("space") or {}
    emit_notification(
        data.get("actor", ""),
        failure_message("unexpected_error", data.get("tableName", ""), space.get("database", "")),
        dedup_id=_dedup(data.get("requestId"), step),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """table-builder ``notifies_on_failure`` — binds the domain emitters into the shared
    ``cpcommon.notify`` skeleton (SPEC-107).

    By default it also binds ``emit_failure`` so a verb's ``TerminalError`` notifies the
    actor at the decorator — the worker verbs no longer need their own
    ``try/except TerminalError``. ``notify_terminal=False`` for validate-authorize, which
    notifies inside its own actor-aware orchestration (the actor isn't bound until after
    the token is verified)."""
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def emit_created(event: dict) -> None:
    """Emit the actor-addressed success notification for a created table (best-effort)."""
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        success_message(event.get("tableName", ""), space.get("database", "")),
        dedup_id=_dedup(event.get("requestId"), "created"),
    )
