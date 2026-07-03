"""Best-effort notification emit to the FIFO notifications queue.

``emit_notification`` builds a ``create`` envelope and sends it with
MessageGroupId=username; when ``NOTIFICATIONS_QUEUE_URL`` is unset it is a logged
no-op. Never raises: a missed notification must not change or fail the surrounding
control-plane action.
"""

import json
import logging

import config
import clients

logger = logging.getLogger()


def emit_notification(username: str, message: str, dedup_id: str | None = None) -> None:
    """Send a ``create`` envelope to the notifications queue for ``username``.

    No-op (single log line) when NOTIFICATIONS_QUEUE_URL is unset. Catches and logs
    all errors; never raises.
    """
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
