"""Best-effort outcome notifications for the table-builder pipeline.

Each verb Lambda emits one "create" notification to the FIFO notifications queue at
its terminal branch: a failure message when it raises TerminalError, a success
message when execute-ddl creates the table. The recipient is always the actor (no
fan-out). A missed notification must never change or fail the pipeline outcome
(already recorded in the Step Function execution): emit_notification catches and
logs all errors, never raises, and is a no-op when NOTIFICATIONS_QUEUE_URL is unset.
A thin per-arc copy of the shared-space helper keeps the two control planes decoupled.

A verb may also fail on an UNEXPECTED (non-terminal) exception — an AWS AccessDenied,
a bug, a transient fault that exhausts its retries. Those escape the handler's own
TerminalError branch, so the @notifies_on_failure wrapper on each handler emits a
generic failure notification for them before the exception propagates to the Step
Function's Catch. Without it, an unexpected failure is silent to the actor (the SFN
records the outcome, but nothing reaches their inbox).
"""

import functools
import json
import logging

from . import config, clients
from .errors import TerminalError, TransientError
from .messages import failure_message, success_message

logger = logging.getLogger()


def _dedup(request_id, step):
    """FIFO dedup id "{requestId}:{step}"; None without a requestId (content dedup)."""
    return f"{request_id}:{step}" if request_id else None


def emit_failure(event, err, step):
    """Emit the actor-addressed failure notification for a verb's TerminalError.

    Best-effort. Reads the actor/table/database/requestId from the validated event.
    An unauthorized failure raised before the actor is bound has no recipient, so
    the emit is a no-op, not a lost message.
    """
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        failure_message(err.reason, event.get("tableName", ""), space.get("database", ""), err.detail),
        dedup_id=_dedup(event.get("requestId"), step),
    )


def emit_unexpected(event, step):
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


def notifies_on_failure(step):
    """Wrap a verb handler so an UNEXPECTED terminal exception notifies the actor
    before it propagates — closing the silent-failure gap for errors the handler
    didn't anticipate (an AccessDenied, a bug, a bad response).

    Two exception kinds pass straight through WITHOUT a second notification:
      - TerminalError — a deterministic failure the handler already notified at its
        raise site (re-notifying would double-send);
      - TransientError — a retryable throttling/5xx the Step Function's Retry re-runs;
        notifying now would be premature (the retry may succeed).
    Every other exception is an unexpected terminal failure: emit one generic
    best-effort notification, then re-raise unchanged for the SFN Catch.
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


def emit_created(event):
    """Emit the actor-addressed success notification for a created table (best-effort)."""
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        success_message(event.get("tableName", ""), space.get("database", "")),
        dedup_id=_dedup(event.get("requestId"), "created"),
    )


def emit_notification(username, message, dedup_id=None):
    """Send a "create" envelope to the FIFO notifications queue, grouped by username.

    No-op (one log line) when NOTIFICATIONS_QUEUE_URL is unset or there is no
    recipient. Catches and logs all errors; never raises.
    """
    if not config.NOTIFICATIONS_QUEUE_URL:
        logger.info("notifications queue unset; skipping notify for %s", username)
        return
    if not username:
        # No actor to address (e.g. an unverifiable token) — nothing to send.
        logger.info("no recipient; skipping notify")
        return
    try:
        body = {"action": "create", "username": username, "message": message}
        kwargs = {
            "QueueUrl": config.NOTIFICATIONS_QUEUE_URL,
            "MessageBody": json.dumps(body),
            "MessageGroupId": username,
        }
        if dedup_id:
            kwargs["MessageDeduplicationId"] = dedup_id
        clients.sqs().send_message(**kwargs)
    except Exception:  # noqa: BLE001 - best-effort; never fail the pipeline outcome
        logger.exception("emit_notification failed for %s", username)
