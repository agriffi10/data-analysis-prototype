"""Best-effort outcome notifications for the archive pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the archive specifics — at
this stage the actor-addressed failure only, because SPEC-168 copies nothing and deletes nothing
and so has no success to report. SPEC-172 owns the outcome notifications.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.

**No per-message dedup token is passed, and the queue's content-based dedup is load-bearing
rather than incidental.** SPEC-114's rule is one token per OUTCOME, not per verb; here every
outcome is emitted from exactly one place, while a verb's state carries a ``Retry`` and a
re-invocation after a transient Lambda fault would otherwise send the message twice. Content
dedup is what makes that retry safe. The cost is inherited from the other planes and is worth
knowing: two archives that render a byte-identical sentence inside the queue's five-minute
window collapse to one message.
"""

import logging

from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import failure_message

logger = logging.getLogger()

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
]


def _actor(event) -> str:
    """Reads the verified actor out of a verb's event, tolerating the pre-identity shapes.

    Returns an empty actor rather than raising for anything that is not a request object with a
    username on it. That window is real and is not an error: validate-authorize's event is the
    raw SQS array until the token is verified, and an emit with no addressee is a logged no-op —
    never a message sent to whoever the untrusted body named.

    Args:
      event: The verb's event.

    Returns:
      The verified username, or an empty string.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    actor = data.get("actor")
    if isinstance(actor, dict):
        actor = actor.get("username")
    return actor if isinstance(actor, str) else ""


def _mode(event) -> str:
    """Reads the request's mode out of a verb's event, for the wording.

    Returns an empty string for anything that is not a request object with a mode on it, which
    renders the archive sentence — the same fallback ``failure_message`` documents. That window
    is real: validate-authorize's event is the raw SQS array until the body is parsed.

    Args:
      event: The verb's event.

    Returns:
      The mode, or an empty string.

    Raises:
      None.
    """
    mode = event.get("mode") if isinstance(event, dict) else None
    return mode if isinstance(mode, str) else ""


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a key the actor supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its tokens are the opposite channel and ARE forwarded, because they exist
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
    emit_notification(
        _actor(event), failure_message(err.reason, tokens=err.tokens, mode=_mode(event))
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(_actor(event), failure_message("unexpected_error", mode=_mode(event)))


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds archive's emitters into the shared failure-notification skeleton.

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
