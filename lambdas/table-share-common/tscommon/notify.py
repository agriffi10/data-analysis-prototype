"""Best-effort outcome notifications for the table-share pipeline (SPEC-094).

Each verb emits "create" notifications to the FIFO notifications queue at its
terminal branch. The SENDER (actor) hears every outcome: one message per
recipient (success or the specific failure) plus a single message for a
whole-request failure. On a recipient SUCCESS the target party is also told —
a user recipient directly, a shared-space recipient via the space's OWNER
(resolved from the registry; owner only, never the members). Failures notify
the sender only (architecture §8).

A missed notification must never change or fail the share outcome (already
recorded in the Step Function execution): emit_notification catches and logs all
errors, never raises, and is a no-op when NOTIFICATIONS_QUEUE_URL is unset. The
notifications queue has content-based dedup, so no per-message dedup id is
needed. A thin per-arc sibling of tbcommon.notify keeps the control planes
decoupled.

Unexpected (non-Terminal/non-Transient) verb errors escape the handlers' own
emit branches, so the @notifies_on_failure wrapper emits a generic sender
notification for them before the exception propagates to the Step Function.
"""

import functools
import json
import logging

from . import clients, config
from . import registry as reg
from .errors import TerminalError, TransientError
from .messages import failure_message, recipient_user_message, space_owner_message, success_message

logger = logging.getLogger()


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

    Best-effort. A Map-verb event names the failed recipient; a whole-request
    event does not. An unauthorized failure raised before the actor is bound has
    no recipient, so the emit is a no-op, not a lost message.
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
    actor, source_table, table_name, recipient = _context(event)
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


def notifies_on_failure(step: str):
    """Wrap a verb handler so an UNEXPECTED terminal exception notifies the sender
    before it propagates — closing the silent-failure gap for errors the handler
    didn't anticipate (an AccessDenied, a bug, a bad response).

    Two exception kinds pass straight through WITHOUT a second notification:
      - TerminalError — the handler already notified at its raise site;
      - TransientError — the Step Function's Retry re-runs the verb; notifying
        now would be premature (the retry may succeed).
    """

    def decorate(handler):
        @functools.wraps(handler)
        def wrapper(event, context):
            try:
                return handler(event, context)
            except (TerminalError, TransientError):
                raise
            except Exception:  # noqa: BLE001 - notify then re-raise, never swallow
                logger.exception("unexpected failure in %s step", step)
                emit_unexpected(event, step)
                raise

        return wrapper

    return decorate


def emit_recipient_success(event: dict) -> None:
    """Emit both success notifications for one created recipient table (best-effort).

    Sender: the per-recipient "Shared … as …" outcome. Success target: a user
    recipient in their own inbox; a space recipient via the space's registry
    ``owner`` — skipped (one log line) when the record or its owner can't be
    resolved, without affecting the sender's message (FR-002).
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
    except Exception:  # noqa: BLE001 - owner lookup is best-effort (FR-002)
        logger.exception("owner lookup failed for space %s; skipping owner notification", name)
        return
    if not owner:
        logger.info("space %s has no resolvable owner; skipping owner notification", name)
        return
    emit_notification(owner, space_owner_message(actor, table_name, name))


def emit_notification(username: str, message: str) -> None:
    """Send a "create" envelope to the FIFO notifications queue, grouped by recipient.

    No-op (one log line) when NOTIFICATIONS_QUEUE_URL is unset or there is no
    recipient. The queue's content-based dedup covers accidental duplicates.
    Catches and logs all errors; never raises.
    """
    if not config.NOTIFICATIONS_QUEUE_URL:
        logger.info("notifications queue unset; skipping notify for %s", username)
        return
    if not username:
        logger.info("no recipient; skipping notify")
        return
    try:
        body = {"action": "create", "username": username, "message": message}
        clients.sqs().send_message(
            QueueUrl=config.NOTIFICATIONS_QUEUE_URL,
            MessageBody=json.dumps(body),
            MessageGroupId=username,
        )
    except Exception:  # noqa: BLE001 - best-effort; never fail the share outcome
        logger.exception("emit_notification failed for %s", username)
