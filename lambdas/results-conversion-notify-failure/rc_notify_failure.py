"""results-conversion notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a task
that cannot be invoked. In that window the actor is told nothing. This path closes that.

Two Step Functions errors never reach it by either door. ``States.DataLimitExceeded`` is caught
only by a catcher that names it, and none in this machine does; ``States.Runtime`` is caught by
nothing, ``States.ALL`` included. Either ends the run FAILED, which the timeout door below does
not match, so a failure no verb had already reported reaches nobody. The machine is built so
that neither is raised.

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

**A FUNCTION THAT RAN OUT OF TIME OR MEMORY IS NAMED, ON AN EXCEL REQUEST.** Neither can raise,
so this door receives the Lambda error in place of a reason and would otherwise word it as the
fallback. On Excel the cause is almost always the size of the result — its path cannot stream —
so the user is told that and pointed at Parquet. On the streamed formats running out is a fault
the user cannot act on, and pointing them at Parquet from a Parquet request would be wrong, so
the fallback stands. The log keeps the Lambda's own name for the operator.

**Its sends wait rather than being capped** (``bounded=False``). The run has already failed, so a
stall can fail nothing the user was told, and on the timed-out door a send held to this function's
timeout fails the asynchronous invocation, which Lambda retries; a send abandoned at the cap would
be swallowed and never retried.

Attributes:
  _TIMEOUT_DETAIL_TYPE: The EventBridge detail-type the timeout door matches on.
  _TIMEOUT_REASON: Reason code for a run the state machine's own timeout stopped.
  _EXHAUSTION: The Lambda error names for a function stopped by its own timeout or its memory.
    ``Sandbox.Timedout`` is the name production delivered for the converter's timeout.
    ``Runtime.OutOfMemory`` is the name Lambda gives an out-of-memory kill and has not been seen
    in this account; if it is not what arrives, that case keeps the fallback it had before.
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
_EXHAUSTION = frozenset({"Sandbox.Timedout", "Runtime.OutOfMemory"})


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
      raw: The Pipe's forwarded SQS batch, as RecordFailure copied it off the context object.

    Returns:
      ``{"username": ..., "format": ..., "filename": ...}``, with an empty username when it
      cannot be recovered. The file name rides along because this is the one place the request
      body is parsed, and threading it through the machine's three failure seeds instead would
      add a key to each for something already on the state.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op — a
      raise here would replace a missing notification with an unhandled error.
    """
    if raw is None:
        return {"username": "", "format": None, "filename": None}
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        username = cpactor.trusted_actor(body).username
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover a verified actor from the request: %s", exc)
        return {"username": "", "format": None, "filename": None}
    fmt = body.get("format") if isinstance(body, dict) else None
    name = ((body.get("destination") or {}) if isinstance(body, dict) else {}).get("filename")
    return {
        "username": username,
        "format": fmt if isinstance(fmt, str) else None,
        "filename": name if isinstance(name, str) else None,
    }


def _timed_out_request(detail) -> dict:
    """Recovers the actor and the format from a timed-out execution's own input.

    Args:
      detail: The event's ``detail`` block.

    Returns:
      ``{"username": ..., "format": ..., "filename": ..., "raw": ...}``, with an empty username
      when the input was omitted or cannot be attributed. ``raw`` is the parsed batch, carried so
      the notification can name the request id from the same bytes, or None when there is none.

    Raises:
      None. Every failure degrades to no verified actor: a raise here would be an async Lambda
      failure, and EventBridge retries those, turning one unattributable event into three.
    """
    nobody = {"username": "", "format": None, "filename": None, "raw": None}
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
        return nobody
    included = (detail.get("inputDetails") or {}).get("included")
    raw = detail.get("input")
    if included is False or not isinstance(raw, str) or not raw:
        logger.info("timed-out execution carries no input; nobody can be attributed")
        return nobody
    try:
        batch = json.loads(raw)
    except ValueError as exc:
        logger.info("could not attribute the timed-out execution: %s", exc)
        return nobody
    return {**_identity_from_raw(batch), "raw": batch}


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
        username,
        messages.failure_message(_TIMEOUT_REASON, {"format": recovered["format"]}),
        payload=notify.request_payload({"raw": recovered["raw"], "format": recovered["format"]}),
        bounded=False,
    )
    observability.info(
        "notified the actor that the execution timed out",
        outcome="notified",
        reason=_TIMEOUT_REASON,
        actor=username,
        notified=True,
    )
    return {"username": username, "error": {"Error": "States.Timeout", "Cause": None}}


def _wording_tokens(request: dict) -> dict:
    """Collects what a refusal's sentence needs beyond the format, from wherever it survives.

    Only what nothing else can supply. The file NAME is recovered from the request body inside the
    forwarded request, which ``RecordFailure`` carries on every path, so it needs no key of its
    own. A COUNT is not derivable from anything the request said: it is a fact about the RESULT SET,
    discovered by the convert verb, and Excel's two size refusals are the converter's only ones
    whose sentences have to name one — the row ceiling its rows, the cell cap its rows, columns
    and cells. That is the whole reason the machine's refusal seed carries a ``tokens`` object at
    all, and why it carries nothing else.

    Args:
      request: The recorded failure the ASL door received.

    Returns:
      The wording tokens, which may be empty. Only string and integer values are taken, so a
      malformed state cannot put an object into a sentence.

    Raises:
      None.
    """
    collected: dict = {}
    supplied = request.get("tokens")
    if isinstance(supplied, dict):
        collected.update(
            {k: v for k, v in supplied.items() if isinstance(v, (str, int)) and not isinstance(v, bool)}
        )
    return collected


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


def _worded_reason(reason: str, fmt: str | None) -> str:
    """Picks the reason a user's sentence is worded from, which is not always the one that arrived.

    Args:
      reason: The decoded reason: a plane code, or the raw Step Functions or Lambda error name.
      fmt: The request's output format, where it survived.

    Returns:
      ``reasons.EXCEL_EXHAUSTED`` for an Excel request whose function ran out of time or memory,
      and the reason unchanged otherwise.

    Raises:
      None.
    """
    if fmt == "xlsx" and reason in _EXHAUSTION:
        return reasons.EXCEL_EXHAUSTED
    return reason


@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notifies the actor that their conversion failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort. Two entry shapes reach this
    one handler, dispatched on the detail-type: the ASL state's request object, and
    EventBridge's status-change event for a run the machine's own ``TimeoutSeconds`` stopped.

    The request body under ``$.raw`` is parsed UNCONDITIONALLY rather than only when the
    username is missing: the file name a refusal's sentence names lives there whether or not the
    actor had to be recovered from it.

    Both doors carry the request id and the format as the payload, as the plane's other producers
    do. The terminal is where a convert refusal and a converter that ran out of time both land, so
    a payload-less row here would be the one of this plane's own that a reader tracking a
    conversion in flight could never settle.

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
    recovered = _identity_from_raw(request.get("raw"))
    username, fmt = username or recovered["username"], fmt or recovered["format"]
    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: actor=%s reason=%s", username, reason)
    tokens = _wording_tokens(request)
    if recovered["filename"]:
        tokens.setdefault("filename", recovered["filename"])
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
    notify.emit_notification(
        username,
        messages.failure_message(_worded_reason(reason, fmt), {"format": fmt, **tokens}),
        payload=notify.request_payload({**request, "format": fmt}),
        bounded=False,
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
