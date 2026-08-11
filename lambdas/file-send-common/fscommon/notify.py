"""Best-effort outcome notifications for the file-send pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the file-send specifics.
At this stage the only notification is the sender-addressed failure — the success and
per-recipient outcomes arrive with SPEC-166/167, and the SPEC-152 pre-verb path is what the
machine's ``NotifyFailure`` state uses.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.
"""

from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import failure_message

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
]


def _actor(event) -> str:
    """Reads the verified actor out of a verb's event, tolerating the pre-identity shapes.

    Returns an empty actor rather than raising for anything that is not a request object with
    a username on it. That window is real and is not an error: validate-authorize's event is
    the raw SQS array until the token is verified, and an emit with no addressee is a logged
    no-op — never a message sent to whoever the untrusted body named.

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


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the sender-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a key the sender supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its tokens are the opposite channel and ARE forwarded, because they
    exist to fill the markers in a body.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None. A failure raised before the actor is bound has no addressee, so the emit is a
      no-op rather than a lost message.

    Raises:
      None.
    """
    emit_notification(_actor(event), failure_message(err.reason, tokens=err.tokens))


def emit_unexpected(event, step: str) -> None:
    """Emits the sender-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(_actor(event), failure_message("unexpected_error"))


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds file-send's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because
        the sender is not bound until the token is verified.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)
