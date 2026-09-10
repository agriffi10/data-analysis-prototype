"""Best-effort failure notifications for the results-conversion pipeline.

The shared primitives live in ``cpcommon.notify``; this module binds the plane's own wording
into the failure skeleton. A missed notification must never change or fail the outcome, so every
emit goes through ``cpcommon.notify.emit_notification``, which catches, logs and never raises.

**The recipient is ``username`` on the verb's event, never ``actor``.** This plane's validated
state carries the verified username flat, and ``cpcommon.notify.actor_of`` reads only a nested
``actor`` — an emitter built on it would address nobody on every post-validate refusal, log a
no-op, and the failure terminal would then suppress the notification as already sent. A
pre-identity event (the raw SQS array) carries no username and is a logged no-op, which is
correct: there is no trusted addressee yet.

**No per-message dedup token is passed**; the notifications queue's content-based dedup is what
makes a re-invocation after a transient Lambda fault safe, as on every neighbouring plane.

Attributes:
  None.
"""

from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from . import reasons
from .messages import failure_message

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
    "request_payload",
    "username_of",
]


def username_of(event) -> str:
    """Reads the verified username off a verb's event, tolerating the pre-identity shape.

    Args:
      event: The verb's event, of any shape.

    Returns:
      The username, or an empty string when the event carries none.

    Raises:
      None.
    """
    username = event.get("username") if isinstance(event, dict) else None
    return username if isinstance(username, str) else ""


def _format_of(event) -> dict:
    """The format token for the wording, when the event carries one.

    Args:
      event: The verb's event.

    Returns:
      ``{"format": ...}`` or an empty dict.

    Raises:
      None.
    """
    value = event.get("format") if isinstance(event, dict) else None
    return {"format": value} if isinstance(value, str) else {}


def request_payload(event) -> dict | None:
    """The structured payload a notification carries beside its message.

    The request id is what lets a reader tracking this request in flight settle its record;
    the format is what it was saving as. The id is read through the shared walk rather than off a
    top-level key, because the failure terminal's state has ``requestId: null`` wherever the error
    replaced the state, and the forwarded request beside it under ``raw`` still names the run.

    Args:
      event: The verb's event, or the failure terminal's recorded failure.

    Returns:
      The payload, or None when no shape names a usable request id.

    Raises:
      None.
    """
    request_id = observability.request_id_of(event)
    if not request_id:
        return None
    return {"requestId": request_id, **_format_of(event)}


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — operator text — is never forwarded; its tokens are, because they exist
    to fill the markers in a body.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(
        username_of(event),
        failure_message(err.reason, {**_format_of(event), **err.tokens}),
        payload=request_payload(event),
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed notification for an unexpected verb exception.

    Args:
      event: The verb's event.
      step: The verb name, unused for the same reason as above.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(
        username_of(event),
        failure_message(reasons.UNEXPECTED, _format_of(event)),
        payload=request_payload(event),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """The plane's failure-notification decorator, bound to this plane's emitters.

    Args:
      step: The verb name.
      notify_terminal: Whether a ``TerminalError`` is notified here. False for a verb that owns
        its own actor-aware notification, such as validate-authorize, which notifies only once
        the actor is bound.

    Returns:
      A decorator for a verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(
        step, emit_unexpected, emit_failure if notify_terminal else None
    )
