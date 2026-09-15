"""archive notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a task
that cannot be invoked. In that window the user is told nothing: no notification, no DLQ
message, and the request simply never completes. This path exists to close that, and a plane
shipping without it leaves "it just never came back" reachable.

Two Step Functions errors never reach it by either door. ``States.DataLimitExceeded`` is caught
only by a catcher that names it, and none in this machine does; ``States.Runtime`` is caught by
nothing, ``States.ALL`` included. Either ends the run FAILED, which the timeout door below does
not match, so a failure no verb had already reported reaches nobody. The machine is built so
that neither is raised.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable ``States.Runtime`` whenever the Cause is absent or is
not JSON, killing the execution on precisely the failures a user most needs to hear about.

**THE ACTOR USUALLY COMES FROM THE REQUEST BODY, NOT FROM THE RECORDED FAILURE.** Every failure
this state exists for happens before a verb produced an actor, so the recorded object carries
``actor: null``; the machine's failure seed reads the Pipe's original body back from
``$$.Execution.Input`` so the actor can be recovered from the verified identity block. Without that this
function would take its no-recipient branch on every single failure — satisfied on paper, silent
in practice.

**IT HAS TWO DOORS, and the second exists because the first cannot reach one
failure.** The ASL door is a state, so it is reached by a ``Catch`` — and Step Functions catchers
cover Task, Parallel and Map states but **not top-level execution failures**. That gave this
machine a Distributed Map, a copy and a ceiling; a run that exhausts that ceiling is terminated
outright, so no state runs, no Catch fires and this function is never invoked. The documented
remedy is the second door: an EventBridge rule on ``Step Functions Execution Status Change`` with
``status: TIMED_OUT`` invokes this same function with an event of a completely different shape.

The two doors cannot double-notify. The ASL door is reached only through a ``Catch``, which a
timeout never fires; the EventBridge rule matches ``TIMED_OUT`` only, never ``FAILED``, so an
execution that reached ``Fail`` normally does not appear on it.

The timeout door has to recover the actor the hard way, and it needs a fallback the way file-send's
does: the execution input is the Pipe's record, which ``ARCHIVE_MAX_ITEM_BYTES`` deliberately
allows to approach 200 KB, while EventBridge caps an event at 256 KB and drops the input rather
than exceed it. So the archives most likely to time out — the big ones — are exactly the ones whose
actor the event alone cannot name, and ``states:DescribeExecution`` reads it back.

**What the timeout message may say is constrained by what a timeout leaves behind.** The copy may
have run and the commit gate may not have, so a timed-out archive can leave a partial copy in the
vault — but never a deleted source, because deletion is downstream of the gate. That is why the
wording promises the source and says nothing about the vault, which the user cannot see anyway.

Attributes:
  _TIMEOUT_DETAIL_TYPE: The EventBridge detail-type the timeout door matches on.
  _TIMEOUT_REASON: Reason code for an ARCHIVE the state machine's own timeout stopped.
  _RESTORE_TIMEOUT_REASON: The same for a RESTORE. Two codes rather than one worded generically,
    because what a timeout may PROMISE differs by arm: an archive's deletion is downstream of the
    commit gate, so a timed-out archive has never deleted anything — a sentence that is true, load
    bearing, and meaningless about a restore. Unreachable until the retrieval wait exists,
    and shipped now because that is the spec that makes the timeout predominantly a restore event.
"""

import json
import logging

from arcommon import messages, notify
from arcommon.config import ARCHIVE_MODES
from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError, failure_reason

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"

_TIMEOUT_REASON = "archive_timed_out"

_RESTORE_TIMEOUT_REASON = "restore_timed_out"


def _mode_from_raw_request(raw) -> str:
    """Recovers the request's mode from the Pipe's original body, for the WORDING.

    The second door is the only path where the mode cannot come off the state — a top-level
    timeout terminates the execution outright, so no state ran and nothing was recorded. It comes
    from the same raw body the actor does, and unlike the actor it is NOT security-relevant: it
    selects between two prefixes and two timeout sentences, so an untrusted value can only make a
    user's own malformed request read as the other operation.

    **The retrieval is what makes this matter.** Nothing on the restore arm waits, so a restore
    cannot time out; that spec adds a 3-5 hour retrieval wait, which makes the timeout
    predominantly a RESTORE event — and the archive sentence promises "nothing was deleted and your
    files are exactly where they were", which says nothing true or useful about a restore.

    Args:
      raw: The Pipe's forwarded SQS batch, as RecordFailure copied it off the context object.

    Returns:
      The mode, or an empty string, which renders the archive wording.

    Raises:
      None. Every failure degrades to the archive wording rather than to no message.
    """
    if raw is None:
        return ""
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        mode = body.get("mode") if isinstance(body, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover the mode from the request: %s", exc)
        return ""
    return mode if events.in_vocabulary(mode, ARCHIVE_MODES) else ""


def _actor_from_raw_request(raw) -> str:
    """Recovers the verified actor from the Pipe's original request body.

    **This is what makes the state more than decorative.** The failures it exists for — a
    cold-start import error, a task that could not be invoked — all happen before any verb
    produced an actor, so the recorded-failure object carries ``actor: null`` every time.
    Without this the notifier would take its no-recipient branch on every single failure, and
    the guarantee would read as satisfied while telling nobody anything.

    The identity block is the ONLY acceptable source of the username; the flat field beside it
    asserts nothing about who sent it, and on this plane it held the raw token until the API
    stopped sending one. Nothing here expires, so a failure surfacing hours later is attributable
    on exactly the same terms as one surfacing at once.

    Args:
      raw: The Pipe's forwarded SQS batch, as RecordFailure copied it off the context object.

    Returns:
      The verified username, or an empty string when it cannot be recovered.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op — a
      raise here would replace a missing notification with an unhandled error.
    """
    if raw is None:
        return ""
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        return cpactor.trusted_actor(body).username
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover a verified actor from the request: %s", exc)
        return ""


def _mode(request: dict) -> str:
    """Reads the failed request's mode, which decides how the failure is worded.

    ``RecordFailure`` carries ``mode`` on every path, including a literal null on the pre-identity
    one — the two modes share one body table under two prefixes, and the codes both of them can
    reach (``forbidden``, ``malformed_event``) are exactly the ones a single prefix gets wrong.

    Args:
      request: The failed request as the ASL door delivers it.

    Returns:
      The mode, or an empty string, which renders the archive wording.

    Raises:
      None.
    """
    mode = request.get("mode")
    return mode if isinstance(mode, str) else ""


def _is_execution_timeout(event) -> bool:
    """Reports whether this invocation came through the EventBridge door.

    Matched on the detail-type rather than on the presence of ``detail``, because the ASL door's
    payload is a request object and a request could in principle carry any field name. The status
    is NOT re-checked here — the rule pattern matches ``TIMED_OUT`` alone, and a second check in
    Python would silently swallow anything a future pattern widening let through instead of
    notifying about it.

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

    The wording is this plane's own rather than the generic failure sentence, and what it can
    promise is decided by where the timeout can land: the source deletion sits downstream of the
    commit gate, so a timed-out archive has never deleted anything — whatever else it did.

    Args:
      event: The EventBridge event.

    Returns:
      The recovered outcome, for the log and for symmetry with the ASL door.

    Raises:
      None. Every failure degrades to no verified actor, which is logged as a no-op. That
      includes a ``detail`` of the wrong type: a raise here would be an async Lambda failure, and
      EventBridge retries those, turning one unattributable event into three.
    """
    detail = event.get("detail") or {}
    username = ""
    mode = ""
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
    else:
        raw = events.timed_out_execution_input(detail)
        if not raw:
            logger.info("timed-out execution carries no input; nobody can be attributed")
        else:
            try:
                mode = _mode_from_raw_request(json.loads(raw))
                username = _actor_from_raw_request(json.loads(raw))
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

    reason = _RESTORE_TIMEOUT_REASON if mode == "restore" else _TIMEOUT_REASON
    notify.emit_notification(username, messages.failure_message(reason, mode=mode))
    logger.info("notified %s that their %s timed out", username, mode or "archive")
    observability.info(
        "notified the actor that the execution timed out",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return {"actor": {"username": username}, "error": {"Error": "States.Timeout", "Cause": None}}


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
    """Notifies the actor that their archive failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    No dedup id is passed, matching every other emitter on this plane: the queue deduplicates on
    content and an execution reaches this state at most once.

    A failure with no verified actor is a logged no-op rather than a lost message. The body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

    Args:
      event: The failed request carrying the raw Step Functions error, or — through the second
        door — an EventBridge execution status-change event for a run the machine's own timeout
        stopped.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a message,
      and a crash here would replace a friendly notification with nothing.
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
        username, messages.failure_message(reason, mode=_mode(request))
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
