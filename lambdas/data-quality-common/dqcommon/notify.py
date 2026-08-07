"""Best-effort outcome notifications for the data-quality pipeline.

The shared primitives live in ``cpcommon.notify``; this module holds what is
data-quality-specific. The actor is always the sole recipient, the wording comes from the domain
messages, and the success notification carries a link to the report view.

The link is the point, not a nicety: the reports folder is hidden from the file browser, so a
notification that only names a key leaves the user with no route to their report at all — the
only other way in is typing the URL by hand.

A missed notification must never change or fail the pipeline outcome, so every emit goes through
the shared sender, which catches, logs and never raises.

Attributes:
  FAILURE_STEP: The failure outcome's dedup token.
  SUCCESS_STEP: The success outcome's dedup token.
  _REPORT_ROUTE: The report route's prefix. The space segment is part of the route, not derived.
"""

import logging

from cpcommon.errors import TerminalError
from cpcommon.notify import dedup_id, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import UNEXPECTED_ERROR, failure_message, success_message

logger = logging.getLogger()

__all__ = [
    "FAILURE_STEP",
    "SUCCESS_STEP",
    "emit_completed",
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
    "report_link",
]

FAILURE_STEP = "failure"
SUCCESS_STEP = "completed"

_REPORT_ROUTE = "/data-quality"


def report_link(actor: str, space: dict, request_id: str) -> str | None:
    """Builds the in-app path to this request's report view, when one is safe to mint.

    The space is in the path because the report lives under that space's own prefix. A link
    carrying only the request id could not locate a shared-space report, so it would deep-link
    the user to a permanent not-found — worse than no link, because it looks like a broken
    product rather than a missing feature.

    It mirrors the view's resolution precedence: the reader resolves a segment equal to the
    viewer's own username as personal and only consults shared-space names when the segment
    differs. Both kinds are therefore checked, not just the shared one, because each falls the
    wrong side of that single equality test in a different way — a personal space whose name
    differs from the actor would be looked up among shared spaces and read from the wrong bucket,
    and a shared space whose name equals the actor resolves personal and finds nothing. The
    validate verb already rejects the first, so it is unreachable today; it is guarded anyway
    because this function's correctness must not depend on a check in a different verb continuing
    to exist.

    The segment check is belt and braces on values that reach a user's inbox as a clickable path.
    Usernames, space names and request ids are already constrained, so it rejects nothing the
    pipeline legitimately produces — it is here so a future change to either format cannot
    quietly put a traversal or a query string into a link. The browser re-checks; this is the
    producer half.

    Args:
      actor: The verified username.
      space: The request's space, carrying its kind and prefix.
      request_id: The run's request id.

    Returns:
      The in-app path, or None when no working link can be minted. That is the honest answer: the
      notification still tells them the check finished, it just cannot offer a link.

    Raises:
      None.
    """
    name = (space or {}).get("prefix") or ""
    name = str(name).strip("/")
    if not name or not request_id or not actor:
        return None
    if not _is_plain_segment(name) or not _is_plain_segment(str(request_id)):
        logger.warning("refusing to build a report link from unexpected segments")
        return None
    kind = (space or {}).get("kind")
    if kind == "personal" and name != actor:
        return None
    if kind == "shared" and name == actor:
        return None
    if kind not in ("personal", "shared"):
        return None
    return f"{_REPORT_ROUTE}/{name}/{request_id}"


def _is_plain_segment(value: str) -> bool:
    """Reports whether a value is a single path segment with nothing that could change a URL.

    Args:
      value: The candidate segment.

    Returns:
      True when it is non-empty and alphanumeric with hyphens and underscores only.

    Raises:
      None.
    """
    return bool(value) and all(c.isalnum() or c in "-_" for c in value)


def emit_completed(event: dict) -> None:
    """Emits the actor-addressed success notification, carrying the report link.

    Reads only the location, never the report document, which stays a file. The verdict and
    findings threaded onward are deliberately not read here: the notification says which location
    finished and links to the report, and the report is where the numbers live.

    Args:
      event: The task input, read for the actor, space, location and request id.

    Returns:
      None.

    Raises:
      None.
    """
    space = event.get("space") or {}
    actor = event.get("actor", "")
    emit_notification(
        actor,
        success_message(event.get("location", "")),
        dedup_id=dedup_id(event.get("requestId"), SUCCESS_STEP),
        link=report_link(actor, space, event.get("requestId", "")),
    )


def emit_failure(event: dict, err: TerminalError, step: str = FAILURE_STEP) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — raw Athena or AWS text — is deliberately not forwarded; it stays on the
    exception for the logs and the SFN record. Its tokens are forwarded: those are the
    per-request values the message body's markers need, and they are the reason this emit rather
    than the notify state's is the one the user should receive.

    Args:
      event: The task input, read for the actor, location and request id.
      err: The terminal error being reported.
      step: Accepted for the shared seam and unused — this plane uses one token per outcome.

    Returns:
      None. A failure raised before the actor is bound has no recipient, so the emit is a no-op
      rather than a lost message.

    Raises:
      None.
    """
    del step
    emit_notification(
        event.get("actor", "") if isinstance(event, dict) else "",
        failure_message(err.reason, _location(event), **getattr(err, "tokens", {})),
        dedup_id=dedup_id(_request_id(event), FAILURE_STEP),
    )


def emit_unexpected(event, step: str = FAILURE_STEP) -> None:
    """Emits the actor-addressed failure notification for an unexpected verb exception.

    Generic wording, so no internals leak.

    Args:
      event: The task input. A non-dict is tolerated — the validate verb's input is the raw SQS
        array, and a failure there happens before the actor is bound, so there is no recipient
        and the emit is a no-op.
      step: Accepted for the shared seam and unused.

    Returns:
      None.

    Raises:
      None.
    """
    del step
    data = event if isinstance(event, dict) else {}
    emit_notification(
        data.get("actor", ""),
        failure_message(UNEXPECTED_ERROR, _location(data)),
        dedup_id=dedup_id(_request_id(data), FAILURE_STEP),
    )


def _location(event) -> str:
    """Reads the checked location from an event of any shape.

    Args:
      event: The task input, or anything else.

    Returns:
      The location, or "" when there is none.

    Raises:
      None.
    """
    if not isinstance(event, dict):
        return ""
    return str(event.get("location") or "")


def _request_id(event):
    """Reads the request id from an event of any shape.

    Args:
      event: The task input, or anything else.

    Returns:
      The request id, or None.

    Raises:
      None.
    """
    return event.get("requestId") if isinstance(event, dict) else None


def notifies_on_failure(step: str = FAILURE_STEP, *, notify_terminal: bool = True):
    """Binds data-quality's emitters into the shared failure-notification skeleton.

    Args:
      step: The outcome token carried into the notification.
      notify_terminal: Whether a terminal error also notifies here, so worker verbs need no
        ``try/except`` of their own. False for the validate verb, whose failures happen before
        the actor is bound — notifying from there would address a recipient the token has not yet
        proven.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)
