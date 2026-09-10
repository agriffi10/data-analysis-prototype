"""file-ops notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the actor is told nothing:
no notification, no DLQ message, and the request simply never completes. This path exists to
close that, and a plane shipping without it leaves "it just never came back" reachable.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable ``States.Runtime`` whenever the Cause is absent or is
not JSON, killing the execution on precisely the failures a user most needs to hear about.

**THE ACTOR USUALLY COMES FROM THE REQUEST BODY, NOT FROM THE RECORDED FAILURE.** Every
failure this state exists for happens before a verb produced an actor, so the recorded object
carries ``actor: null``; the machine's failure seed reads the Pipe's original body back from
``$$.Execution.Input`` so the actor can be recovered from the verified identity block. Without that this
function would take its no-recipient branch on every single failure — satisfied on paper, silent
in practice.

**IT HAS TWO DOORS, and the second exists because the first cannot reach one
failure.** The ASL door above is a state, so it is reached by a ``Catch`` — and Step Functions
catchers cover Task, Parallel and Map states but **not top-level execution failures**. A run
that exhausts the machine's own ``TimeoutSeconds`` is terminated outright: no state runs, no
Catch fires, and this function is never invoked. The documented remedy is the second door: an
EventBridge rule on ``Step Functions Execution Status Change`` with ``status: TIMED_OUT``
invokes this same function with an event of a completely different shape.

The two doors cannot double-notify. The ASL door is reached only through a ``Catch``, which a
timeout never fires; the EventBridge door matches ``TIMED_OUT`` only, never ``FAILED``, so an
execution that reached ``Fail`` normally does not appear on it.

The timeout door has to recover the actor the hard way. The execution input is what the Pipe
forwarded — the raw SQS batch — so the actor is the **identity block the API stamped into that
body**, never the body's own assertion. There is no token here to expire: the API verifies the
bearer at the edge and writes what it verified, and the queue is writable by no one else, so a
timeout firing hours later reads a value that was never time-limited in the first place. The
expiry relaxation this door used to need is gone with the thing it relaxed.

Attributes:
  _TIMEOUT_DETAIL_TYPE: The EventBridge detail-type the timeout door matches on.
  _TIMEOUT_REASON: Reason code for a run the state machine's own timeout stopped.
"""

import json
import logging

from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError, failure_reason
from focommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"

_TIMEOUT_REASON = "operation_timed_out"


def _is_execution_timeout(event) -> bool:
    """Reports whether this invocation came through the EventBridge door.

    Matched on the detail-type rather than on the presence of ``detail``, because the ASL door's
    payload is a request object and a request could in principle carry any field name. The
    status is NOT re-checked here — the rule pattern matches ``TIMED_OUT`` alone, and a second
    check in Python would silently swallow anything a future pattern widening let through
    instead of notifying about it.

    Args:
      event: The Lambda event.

    Returns:
      True when this is a Step Functions execution status-change event.

    Raises:
      None.
    """
    return isinstance(event, dict) and event.get("detail-type") == _TIMEOUT_DETAIL_TYPE


def _on_execution_timed_out(event) -> dict:
    """Notifies the actor that the whole run was stopped by the machine's own timeout.

    The wording is deliberately not the generic failure sentence. A timeout is the one
    whole-request failure that can leave a space PART-CHANGED: on a move, objects may have been
    copied and not yet deleted, or deleted from a folder that is now half gone. "Try again" alone
    would be wrong advice, because a second attempt would meet what the first one left.

    It is also the one failure that can leave the space's LOCK held: the expiry terminates the
    execution outright, so no state runs and no release happens. The stale steal is what frees it,
    and until then that space refuses further operations — which is why the sentence tells the
    user to wait rather than to retry immediately.

    Args:
      event: The EventBridge event.

    Returns:
      The recovered request, for the log and for symmetry with the ASL door.

    Raises:
      None. Every failure degrades to no verified actor, which is logged as a no-op. That
      includes a ``detail`` of the wrong type: a raise here would be an async Lambda failure,
      and EventBridge retries those, turning one unattributable event into three.
    """
    detail = event.get("detail") or {}
    username = ""
    operation = None
    payload = None
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
    else:
        raw = events.timed_out_execution_input(detail)
        if not raw:
            logger.info("timed-out execution carries no input; nobody can be attributed")
        else:
            try:
                parsed = json.loads(raw)
                username = _actor_from_raw_request(parsed)
                operation = notify.operation_of({"raw": parsed})
                payload = notify.request_payload(parsed)
            except ValueError as exc:
                logger.info("could not attribute the timed-out execution: %s", exc)

    if not username:
        observability.warning(
            "no verified actor on a timed-out execution; nothing to notify",
            outcome="no-recipient",
            reason=_TIMEOUT_REASON,
            notified=False,
        )
        return {"actor": {"username": ""}, "error": {"Error": "States.Timeout", "Cause": None}}

    notify.emit_notification(
        username, messages.failure_message(operation, _TIMEOUT_REASON), payload=payload
    )
    logger.info("notified %s that their file operation timed out", username)
    observability.info(
        "notified the actor that the execution timed out",
        outcome="notified",
        reason=_TIMEOUT_REASON,
        actor=username,
        notified=True,
    )
    return {"actor": {"username": username}, "error": {"Error": "States.Timeout", "Cause": None}}


def _actor_from_raw_request(raw) -> str:
    """Recovers the verified actor from the Pipe's original request body.

    **This is what makes the state more than decorative on this plane.** The failures it exists
    for — a cold-start import error, a state timeout, a task that could not be invoked — all
    happen before any verb produced an actor, so the recorded-failure object carries
    ``actor: null`` every time. Without this the notifier would take its no-recipient branch on
    every single failure, and the guarantee would read as satisfied while telling nobody
    anything. The ASL's failure seed reads ``$$.Execution.Input`` — the execution's own input,
    which survives whatever the Catch did to the state — to make this possible.

    The identity block is the ONLY acceptable source of the username; the flat field beside it
    asserts nothing about who sent it, and on this plane it held the raw token until the
    cutover. Nothing here expires, so a failure surfacing hours later is attributable on exactly
    the same terms as one surfacing at once.

    Args:
      raw: The Pipe's forwarded SQS batch, as RecordFailure copied it off the context object.

    Returns:
      The verified username, or an empty string when it cannot be recovered.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op —
      a raise here would replace a missing notification with an unhandled error.
    """
    if raw is None:
        return ""
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        return cpactor.trusted_actor(body).username
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover a verified actor from the request: %s", exc)
        return ""


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a message for this failure.

    One name, not a heuristic, and the narrowness is the point. ``TerminalError`` is the only
    error treated as already-reported, because it is the only positive evidence: a verb raised
    it deliberately and the decorator fired on the way out.

    The tempting heuristic — a dotted error name means the engine, a bare one means a handler
    ran — is wrong in the dangerous direction, and this fleet has the outage to prove it: a
    config module raising a bare ``RuntimeError`` at import is the shape of a real outage, and that
    rule would have silenced exactly the class of failure this function exists to report.

    The price is paid deliberately: an unexpected in-verb exception notifies through the
    decorator and again here, with the same generic sentence. A duplicate is a papercut on a
    path that is already a bug; a guess that suppresses is unrecoverable.

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
    """Notifies the actor that their file operation failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    The message uses the whole-request phrasing with no recipient named — naming one would be a
    guess, because the failure ended the request before any per-recipient outcome existed. No
    dedup id is passed, matching every other emitter on this plane: the queue deduplicates on
    content and an execution reaches this state at most once.

    A failure with no verified actor is a logged no-op rather than a lost message. The body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

    Both doors attach the request id as the payload, read from the forwarded request when the seed
    nulled it: a browser holding an in-flight card for this run settles it by matching that id, and
    no outcome producer will run to settle it instead.

    Two entry shapes reach this one handler, dispatched on the detail-type: the ASL state's
    request object, and EventBridge's status-change event for a run the machine's own
    ``TimeoutSeconds`` stopped. One function rather than two because they end in the same
    place — one verified actor, one sentence, one queue — and a second function would be a
    second copy of the emit with a second chance to drift.

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
    actor = request.get("actor")
    username = actor.get("username") if isinstance(actor, dict) else None
    username = username if isinstance(username, str) else ""
    if not username:
        username = _actor_from_raw_request(request.get("raw"))

    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: actor=%s reason=%s", username, reason)

    if _verb_already_notified(request.get("error")):
        logger.info("reason %s came from a verb; the decorator already notified", reason)
        observability.info(
            "suppressed a duplicate of the verb's own failure notification",
            outcome="suppressed",
            reason=reason,
            notified=False,
        )
        return request

    if not username:
        logger.info("no verified actor on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    notify.emit_notification(
        username,
        messages.failure_message(notify.operation_of(request), reason),
        payload=notify.request_payload(request),
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
