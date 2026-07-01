"""Best-effort outcome notifications for the table-builder pipeline (SPEC-072).

Each verb Lambda emits ONE SPEC-058 ``create`` notification to the FIFO
notifications queue at its terminal branch — a failure message when it raises a
``TerminalError``, and a success message when ``execute-ddl`` creates the table.
The recipient is always the **actor** (no fan-out — unlike shared-spaces, SPEC-061).

``emit_notification`` is a **best-effort** seam: a missed notification must never
change or fail the surrounding pipeline outcome (that outcome is already recorded in
the Step Function execution). It catches + logs all errors, never raises, and is a
no-op (one log line) when ``NOTIFICATIONS_QUEUE_URL`` is unset — so the module stays
independently deployable (``lambdas.md`` §6). Mirrors the shared-space-common helper
(SPEC-061); a thin per-arc copy keeps the two control planes decoupled.
"""

import json
import logging

from . import config, clients
from .messages import failure_message, success_message

logger = logging.getLogger()


def _dedup(request_id, step):
    """FIFO MessageDeduplicationId = ``{requestId}:{step}`` (SPEC-072 Data Model); None
    when the requestId is missing so the queue's content-dedup (if any) still applies."""
    return f"{request_id}:{step}" if request_id else None


def emit_failure(event, err, step):
    """Emit the actor-addressed failure notification for a verb's ``TerminalError`` at
    its terminal branch (best-effort). Reads the actor/table/database/requestId from the
    validated event (SPEC-067 shape). ``unauthorized`` before the actor is bound has no
    recipient (``actor`` empty) — a no-op, not a lost message."""
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        failure_message(err.reason, event.get("tableName", ""), space.get("database", ""), err.detail),
        dedup_id=_dedup(event.get("requestId"), step),
    )


def emit_created(event):
    """Emit the actor-addressed success notification on execute-ddl's terminal
    ``created`` outcome (best-effort)."""
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        success_message(event.get("tableName", ""), space.get("database", "")),
        dedup_id=_dedup(event.get("requestId"), "created"),
    )


def emit_notification(username, message, dedup_id=None):
    """SendMessage a SPEC-058 ``create`` envelope to the FIFO notifications queue with
    ``MessageGroupId=username``. No-op (single log line) when NOTIFICATIONS_QUEUE_URL
    is unset. Catches and logs all errors; never raises."""
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
