"""results-conversion notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the actor is told nothing.
This path closes that.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable ``States.Runtime`` whenever the Cause is absent or is
not JSON.

**THE ACTOR USUALLY COMES FROM THE REQUEST BODY, NOT FROM THE RECORDED FAILURE.** Every failure
this state exists for happens before a verb produced a username, so the recorded object carries
``username: null``; the machine's failure seed reads the Pipe's original body back from
``$$.Execution.Input`` so the actor can be recovered from the verified identity block.

**IT HAS TWO DOORS, and the second exists because the first cannot reach one failure.** The ASL
door is reached by a ``Catch``, and catchers do not cover top-level execution failures: a run
that exhausts the machine's own ``TimeoutSeconds`` is terminated outright. An EventBridge rule
on ``TIMED_OUT`` invokes this same function with an event of a different shape. That door reads
the execution's input off the EVENT, as table-share's does — never through
``states:DescribeExecution``, which this plane's role deliberately does not hold: SQS refuses a
message over 256 KB at the send and EventBridge carries an event of that size, so no request
that reached the machine can be missing from the event.

The two doors cannot double-notify: the ASL door is reached only through a ``Catch``, which a
timeout never fires; the EventBridge door matches ``TIMED_OUT`` only, never ``FAILED``.

Attributes:
  _TIMEOUT_DETAIL_TYPE: The EventBridge detail-type the timeout door matches on.
  _TIMEOUT_REASON: Reason code for a run the state machine's own timeout stopped.
"""

import json
import logging

from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError, failure_reason
from rccommon import messages, notify, reasons

logger = logging.getLogger()
logger.setLevel(logging.INFO)
observability.init(service="results-conversion")

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"
_TIMEOUT_REASON = reasons.CONVERSION_TIMED_OUT


def _is_execution_timeout(event) -> bool:
    """Reports whether this invocation came through the EventBridge door.

    Matched on the detail-type rather than on the presence of ``detail``, because the ASL door's
    payload is a request object and a request could in principle carry any field name. The
    status is NOT re-checked here — the rule pattern matches ``TIMED_OUT`` alone, and a second
    check in Python would silently swallow anything a future pattern widening let through.

    Args:
      event: The Lambda event.

    Returns:
      True when this is a Step Functions execution status-change event.

    Raises:
      None.
    """
    return isinstance(event, dict) and event.get("detail-type") == _TIMEOUT_DETAIL_TYPE


def _identity_from_raw(raw) -> dict:
    """Recovers the verified actor and the format from the Pipe's original request body.

    The identity block is the ONLY acceptable source of the username; a flat field beside it
    asserts nothing about who sent it. The format is display-only: it names what was being
    saved in the sentence, and the sentence goes to the inbox the verified actor owns.

    Args:
      raw: The Pipe's forwarded SQS batch, as captured at the top of the machine.

    Returns:
      ``{"username": ..., "format": ...}``, with an empty username when it cannot be recovered.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op — a
      raise here would replace a missing notification with an unhandled error.
    """
    if raw is None:
        return {"username": "", "format": None}
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        username = cpactor.trusted_actor(body).username
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover a verified actor from the request: %s", exc)
        return {"username": "", "format": None}
    fmt = body.get("format") if isinstance(body, dict) else None
    return {"username": username, "format": fmt if isinstance(fmt, str) else None}


def _timed_out_request(detail) -> dict:
    """Recovers the actor and the format from a timed-out execution's own input.

    Args:
      detail: The event's ``detail`` block.

    Returns:
      ``{"username": ..., "format": ...}``, with an empty username when the input was omitted
      or cannot be attributed.

    Raises:
      None. Every failure degrades to no verified actor: a raise here would be an async Lambda
      failure, and EventBridge retries those, turning one unattributable event into three.
    """
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
        return {"username": "", "format": None}
    included = (detail.get("inputDetails") or {}).get("included")
    raw = detail.get("input")
    if included is False or not isinstance(raw, str) or not raw:
        logger.info("timed-out execution carries no input; nobody can be attributed")
        return {"username": "", "format": None}
    try:
        return _identity_from_raw(json.loads(raw))
    except ValueError as exc:
        logger.info("could not attribute the timed-out execution: %s", exc)
        return {"username": "", "format": None}


def _on_execution_timed_out(event) -> dict:
    """Notifies the actor that the whole run was stopped by the machine's own timeout.

    Args:
      event: The EventBridge event.

    Returns:
      The recovered identity, for the log and for symmetry with the ASL door.

    Raises:
      None.
    """
    recovered = _timed_out_request(event.get("detail"))
    username = recovered["username"]
    if not username:
        observability.warning(
            "no verified actor on a timed-out execution; nothing to notify",
            outcome="no-recipient",
            reason=_TIMEOUT_REASON,
            notified=False,
        )
        return {"username": "", "error": {"Error": "States.Timeout", "Cause": None}}
    notify.emit_notification(
        username, messages.failure_message(_TIMEOUT_REASON, {"format": recovered["format"]})
    )
    observability.info(
        "notified the actor that the execution timed out",
        outcome="notified",
        reason=_TIMEOUT_REASON,
        actor=username,
        notified=True,
    )
    return {"username": username, "error": {"Error": "States.Timeout", "Cause": None}}


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a message for this failure.

    One name, not a heuristic: ``TerminalError`` is the only positive evidence that a verb
    raised deliberately and the decorator fired on the way out. An unexpected in-verb exception
    notifies through the decorator and again here, with the same generic sentence — a duplicate
    on a path that is already a bug is the deliberate price of never guessing to suppress.

    Args:
      error: The raw Step Functions error object.

    Returns:
      True only when a verb raised a terminal error.

    Raises:
      None.
    """
    return isinstance(error, dict) and error.get("Error") == TerminalError.__name__


@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notifies the actor that their conversion failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort. Two entry shapes reach this
    one handler, dispatched on the detail-type: the ASL state's request object, and
    EventBridge's status-change event for a run the machine's own ``TimeoutSeconds`` stopped.

    Args:
      event: The failed request carrying the raw Step Functions error, or an EventBridge
        ``Step Functions Execution Status Change`` event.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a
      message, and a crash here would replace a friendly notification with nothing.
    """
    if _is_execution_timeout(event):
        return _on_execution_timed_out(event)
    request = dict(event) if isinstance(event, dict) else {}
    username = request.get("username")
    username = username if isinstance(username, str) else ""
    fmt = request.get("format") if isinstance(request.get("format"), str) else None
    if not username:
        recovered = _identity_from_raw(request.get("raw"))
        username, fmt = recovered["username"], fmt or recovered["format"]
    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: actor=%s reason=%s", username, reason)
    if _verb_already_notified(request.get("error")):
        observability.info(
            "suppressed a duplicate of the verb's own failure notification",
            outcome="suppressed",
            reason=reason,
            notified=False,
        )
        return request
    if not username:
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request
    notify.emit_notification(username, messages.failure_message(reason, {"format": fmt}))
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
