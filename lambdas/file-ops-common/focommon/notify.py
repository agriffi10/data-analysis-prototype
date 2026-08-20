"""Best-effort failure notifications for the file-operations pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps what is file-ops': binding
the plane's own wording into the failure-notification skeleton, and choosing the wording by the
OPERATION the user actually asked for.

That last part is the whole reason this module is not two lines. Every other plane has one verb
and so one prefix; this one serves three, and a user who pressed Delete must not be told that a
copy failed. The operation rides on the verb's event, so the emitters read it from there rather
than being bound at import.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.

**No per-message dedup token is passed, and the queue's content-based dedup is load-bearing
rather than incidental.** The rule is one token per OUTCOME, not per verb; each failure here is
emitted from exactly one place, so there is no duplicate-emit pair for a token to collapse —
while the machine's own states carry a ``Retry``, and a re-invocation after a transient Lambda
fault would otherwise send the same message twice. Content dedup is what makes that retry safe.

The cost is real and worth knowing: two requests that render a byte-identical sentence inside the
queue's five-minute window collapse to one message. The reachable case is a user refused for the
same protected folder twice in a row — the second refusal reads identically and is dropped, so
they see no response to their second attempt. Inherited from the neighbouring planes rather than
introduced here.
"""

import json
import logging

from cpcommon.errors import TerminalError
from cpcommon.notify import actor_of, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import failure_message

logger = logging.getLogger()

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
    "operation_of",
]


def operation_of(event) -> object:
    """Returns the operation a request asked for, from wherever on the event it survives.

    Read defensively rather than indexed, because these emitters run on the failure path: an
    event malformed enough to fail validation is exactly the event whose ``operation`` may be
    missing or the wrong type, and the wording resolver falls back on its own for anything it
    does not recognise. Raising here would replace a friendly sentence with an unhandled error
    on the one path whose whole job is reporting a failure.

    The Pipe's raw batch is checked too, because the pre-identity failure path carries the
    original request under ``raw`` and nowhere else.

    Args:
      event: The verb's event, or a recorded failure.

    Returns:
      The operation, or None when it cannot be found.

    Raises:
      None.
    """
    if not isinstance(event, dict):
        return None
    if isinstance(event.get("operation"), str):
        return event["operation"]
    raw = event.get("raw")
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        try:
            body = json.loads(raw[0].get("body") or "{}")
        except Exception:  # noqa: BLE001
            return None
        return body.get("operation") if isinstance(body, dict) else None
    return None


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a folder name the actor supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its TOKENS are the opposite channel and are forwarded, because they exist
    to fill the markers in a body.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None. A failure raised before the actor is bound has no addressee, so the emit is a no-op
      rather than a lost message.

    Raises:
      None.
    """
    emit_notification(actor_of(event), failure_message(operation_of(event), err.reason, err.tokens))


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(actor_of(event), failure_message(operation_of(event), "unexpected_error"))


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds this plane's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because the
        actor is not bound until the token is verified.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)
