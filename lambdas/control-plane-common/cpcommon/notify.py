"""Best-effort notification primitives shared by every control plane (SPEC-107).

Two pieces are genuinely shared; the domain emitters (``emit_failure`` /
``emit_unexpected`` / the per-arc success emitters + event-context extraction) stay in
each domain layer because their signatures and dedup strategy differ.

- ``emit_notification(username, message, dedup_id=None)`` — sends a ``create`` envelope
  to the FIFO notifications queue, grouped by ``username``. No-op (one log line) when
  ``NOTIFICATIONS_QUEUE_URL`` is unset or there is no recipient. Catches and logs all
  errors, never raises — a missed notification must never change or fail a pipeline
  outcome (already recorded in the Step Function execution). ``dedup_id`` is optional:
  table-builder passes ``{requestId}:{step}``; table-share relies on the queue's
  content-based dedup and passes nothing.
- ``notifies_on_failure(step, emit_unexpected)`` — the wrapper skeleton. It takes the
  DOMAIN's unexpected-failure emitter as an explicit seam: a domain calls
  ``cpcommon.notify.notifies_on_failure(step, my_emit_unexpected)`` from its own thin
  ``notifies_on_failure(step)``, so verb handlers keep decorating with the domain helper.
"""

import functools
import json
import logging

from . import clients, config
from .errors import TerminalError, TransientError

logger = logging.getLogger()


def emit_notification(username: str, message: str, dedup_id: str | None = None) -> None:
    """Send a ``create`` envelope to the FIFO notifications queue, grouped by username.

    No-op (one log line) when ``NOTIFICATIONS_QUEUE_URL`` is unset or there is no
    recipient. Catches and logs all errors; never raises.
    """
    if not config.NOTIFICATIONS_QUEUE_URL:
        logger.info("notifications queue unset; skipping notify for %s", username)
        return
    if not username:
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


def notifies_on_failure(step: str, emit_unexpected):
    """Wrap a verb handler so an UNEXPECTED terminal exception notifies the actor before
    it propagates — closing the silent-failure gap for errors the handler didn't
    anticipate (an AccessDenied, a bug, a bad response).

    ``emit_unexpected(event, step)`` is the DOMAIN's generic-failure emitter. Two
    exception kinds pass straight through WITHOUT a second notification:
      - ``TerminalError`` — a deterministic failure the handler already notified at its
        raise site (re-notifying would double-send);
      - ``TransientError`` — a retryable throttling/5xx the SFN Retry re-runs; notifying
        now would be premature.
    Every other exception is an unexpected terminal failure: emit one generic best-effort
    notification, then re-raise unchanged for the SFN Catch.
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
