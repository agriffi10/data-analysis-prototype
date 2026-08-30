"""table-share notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the sender is told nothing:
no notification, no DLQ message, and the request simply never completes.

It is the whole-request failure only, and that is the design. A per-recipient failure ends its
own Map item and its siblings carry on, so the execution succeeds and never reaches this
function; the sender hears about that recipient from the Map verb's own decorator. What reaches
here is the failure that ended the whole request — the validate or inspect verb, or the Map
state itself, where a payload-size failure on the collected results is the realistic one, which
is why every terminal detail is bounded. The two paths are disjoint by construction, so there
is no double-notification to design around on the recipient path.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable runtime error whenever the Cause is absent or is not
JSON, killing the execution on precisely the failures a user most needs to hear about.

**It has TWO doors, and the second one exists because the first cannot reach one failure.**
The ASL door above is a state, so it is reached by a ``Catch`` — and Step Functions catchers
cover Task, Parallel and Map states but **not top-level execution failures**. A run that
exhausts the machine's own ``TimeoutSeconds`` is terminated outright: no state runs, no Catch
fires, and this function is never invoked. The documented remedy is the second door, and it is
the second door: an EventBridge rule on ``Step Functions Execution Status Change`` with
``status: TIMED_OUT`` invokes this same function with an event of a completely different shape.

The two doors cannot double-notify. The ASL door is reached only through a ``Catch``, which a
timeout never fires; the EventBridge door matches ``TIMED_OUT`` only, never ``FAILED``, so an
execution that reached ``Fail`` normally does not appear on it.

The timeout door has to recover the sender the hard way. The execution input is what the Pipe
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
from tscommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"
_TIMEOUT_REASON = "share_timed_out"


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a message for this failure.

    One name, not a heuristic, and the narrowness is the point. ``TerminalError`` is the only
    error treated as already-reported, because it is the only positive evidence: a verb raised
    it deliberately and the decorator fired on the way out.

    An earlier version inferred this from the absence of a dot — bare class name means a handler
    ran, dotted engine name means it did not. It is wrong in the dangerous direction: both config
    modules call their requirement check at module scope and raise a bare ``RuntimeError``, which
    is not hypothetical but this fleet's own recorded outage, and a dot-free name would have
    suppressed exactly the class of failure this function exists to report.

    The price is paid deliberately. An unexpected in-verb exception notifies through the
    decorator and again here, with the same generic sentence. A duplicate notification is
    preferable to none: a guess that suppresses is unrecoverable, a duplicate is a papercut on a
    path that is already a bug.

    Args:
      error: The raw Step Functions error object.

    Returns:
      True only when a verb raised a terminal error.

    Raises:
      None.
    """
    return isinstance(error, dict) and error.get("Error") == TerminalError.__name__


def _is_execution_timeout(event) -> bool:
    """Reports whether this invocation came through the EventBridge door.

    Matched on the detail-type rather than on the presence of ``detail``, because the ASL door's
    payload is the request object and a request could in principle carry any field name. The
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


def _timed_out_request(detail) -> dict:
    """Recovers the sender and the source from a timed-out execution's own input.

    The input is the Pipe's forwarded SQS batch, so this is the same parse every verb does, then
    the identity block — the ONLY acceptable source of the username. The body's
    ``source``/``tableName`` are display-only, exactly as validate-authorize treats them: they
    reach the message text, and the text goes to an inbox the verified actor chose.

    Args:
      detail: The event's ``detail`` block.

    Returns:
      A request-shaped dict carrying the verified actor, the source and the result name — or
      an empty actor when the input was omitted or cannot be attributed.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op.
      That includes a ``detail`` of the wrong type: the shape check is not defensive padding,
      because a raise here would be an async Lambda failure and EventBridge retries those,
      turning one unattributable event into three.
    """
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
        return {}

    included = (detail.get("inputDetails") or {}).get("included")
    raw = detail.get("input")
    if included is False or not isinstance(raw, str) or not raw:
        logger.info("timed-out execution carries no input; nobody can be attributed")
        return {}

    try:
        body = events.parse_sqs_request(json.loads(raw), reason=_TIMEOUT_REASON)
        actor = cpactor.trusted_actor(body).username
    except Exception as exc:  # noqa: BLE001
        logger.info("could not attribute the timed-out execution: %s", exc)
        return {}

    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    return {
        "actor": actor,
        "source": {"database": source.get("database"), "table": source.get("table")},
        "tableName": body.get("tableName"),
        "error": {"Error": "States.Timeout", "Cause": None},
    }


def _on_execution_timed_out(event) -> dict:
    """Notifies the sender that the whole run was stopped by the machine's own timeout.

    The wording is deliberately not the generic failure sentence. A timeout is the one whole-
    request failure that can leave a recipient holding **part** of a dataset: the guard and the
    copy may both have run, and the create may not have, so "try again" alone would be wrong
    advice. ``share_timed_out`` says so and points at the Administrator.

    Args:
      event: The EventBridge event.

    Returns:
      The recovered request, for the log and for symmetry with the ASL door.

    Raises:
      None.
    """
    request = _timed_out_request(event.get("detail") or {})
    actor = request.get("actor") or ""
    source = request.get("source") or {}

    if not actor:
        logger.info("timed-out execution has no verified sender; nothing to notify")
        observability.warning(
            "no verified actor on a timed-out execution; nothing to notify",
            outcome="no-recipient",
            reason=_TIMEOUT_REASON,
            notified=False,
        )
        return request

    notify.emit_notification(
        actor,
        messages.failure_message(_TIMEOUT_REASON, source.get("table") or ""),
    )
    logger.info("notified %s that their share timed out", actor)
    observability.info(
        "notified the sender that the execution timed out",
        outcome="notified",
        reason=_TIMEOUT_REASON,
        actor=actor,
        notified=True,
    )
    return request


@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notifies the sender that their share failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    The message uses the whole-request phrasing, with no recipient named: naming one would be a
    guess, because the failure ended the request before any recipient outcome existed. No dedup
    id is passed, matching every other emitter on this plane — the queue deduplicates on content
    and an execution reaches this state at most once.

    A failure with no verified sender is a logged no-op rather than a lost message: the body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

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
    actor = request.get("actor") or ""
    source = request.get("source") if isinstance(request.get("source"), dict) else {}

    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: actor=%s reason=%s", actor, reason)

    if _verb_already_notified(request.get("error")):
        logger.info("reason %s came from a verb; the decorator already notified", reason)
        observability.info(
            "suppressed a duplicate of the verb's own failure notification",
            outcome="suppressed",
            reason=reason,
            notified=False,
        )
        return request

    if not actor:
        logger.info("no verified sender on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    notify.emit_notification(
        actor,
        messages.failure_message(reason, source.get("table") or ""),
    )
    observability.info(
        "notified the sender of a failure",
        outcome="notified",
        reason=reason,
        actor=actor,
        notified=True,
    )
    return request
