"""Best-effort notification emit — SPEC-061 seam, placed by SPEC-062.

SPEC-062 ships the seam only. ``emit_notification`` builds the SPEC-058 ``create``
envelope and SendMessages it to the FIFO notifications queue — but until SPEC-061
wires ``NOTIFICATIONS_QUEUE_URL`` and grants the orchestrator role ``sqs:SendMessage``,
the queue URL is unset and this is a logged no-op. SPEC-061 adds the inline call
sites + message templating in each verb. Behaviour preserved in SPEC-062: no verb
emits anything yet.

Never raises: a missed notification must not change or fail the surrounding
control-plane action (FR-002 of SPEC-061).
"""

import json
import logging

import config
import clients

logger = logging.getLogger()


def emit_notification(username, message, dedup_id=None):
    """SendMessage a SPEC-058 ``create`` envelope to the FIFO notifications queue with
    MessageGroupId=username. No-op (single log line) when NOTIFICATIONS_QUEUE_URL is
    unset. Catches and logs all errors; never raises."""
    if not config.NOTIFICATIONS_QUEUE_URL:
        logger.info("notifications queue unset; skipping notify for %s", username)
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
    except Exception:  # noqa: BLE001 - best-effort; never fail the action
        logger.exception("emit_notification failed for %s", username)
