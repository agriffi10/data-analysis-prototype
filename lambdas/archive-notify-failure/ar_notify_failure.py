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

**What the timeout message may say is constrained by what a timeout leaves behind, and the
commit gate does not settle it.** A timed-out archive can leave a partial copy in the vault, which
the wording ignores because the user cannot see it. What it cannot ignore is the source: deletion
is downstream of the gate, but the ceiling can land while delete-source runs, or while the receipt
is written after it — and the ceiling does not stop an invocation already running, so delete-source
can go on to decide and delete up to its own timeout after the door has spoken. So the door does
not merely read delete-source's recorded verdict, it claims it: a create-only ``stopped`` where
there was none, which a late delete-source then follows by deleting nothing. "Nothing was deleted"
is sent only when that claim — or an earlier refusal — makes it true; a verdict to delete, or one
that cannot be read, gets a sentence that is true either way. ``arcommon.plan`` owns the record.

Attributes:
  _TIMEOUT_DETAIL_TYPE: The EventBridge detail-type the timeout door matches on.
  _TIMEOUT_REASON: Reason code for an ARCHIVE the state machine's own timeout stopped with no
    original deleted, which the source verdict proves rather than the commit gate.
  _MAY_HAVE_DELETED_REASON: The same for an archive whose verdict was to delete, or could not be
    read — originals may be partly or wholly gone and the receipt may never have been written, so
    the sentence names the archive id and sends the user to an administrator.
  _RESTORE_TIMEOUT_REASON: The same for a RESTORE, which deletes no original and so has no verdict
    to consult. What a timeout may PROMISE differs by arm, and "nothing was deleted and your files
    are exactly where they were" says nothing true or useful about a restore.
"""

import json
import logging

from arcommon import messages, notify, paths, plan
from arcommon.config import ARCHIVE_MODES
from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError, failure_reason
from cpcommon.notify import is_silent

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"

_TIMEOUT_REASON = "archive_timed_out"

_MAY_HAVE_DELETED_REASON = "archive_timed_out_may_have_deleted"

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


def _execution_name(detail: dict) -> str | None:
    """Reads the timed-out execution's name off its ARN, for the verdict record's diagnosis.

    Args:
      detail: The EventBridge event's detail.

    Returns:
      The name, or None when the ARN is absent or not a string.

    Raises:
      None.
    """
    arn = detail.get("executionArn")
    return arn.rsplit(":", 1)[-1] if isinstance(arn, str) else None


def _archive_timeout_reason(request_id, execution: str | None) -> tuple[str, str | None]:
    """Claims delete-source's verdict as ``stopped`` where it has none, and picks what it allows.

    Keyed on the id validate-authorize produced — a lowercased UUID v4 — and not on the raw
    spelling, which is the browser's and would find no verdict under the other. An id that is
    not a UUID v4 was refused before any verb ran, so no original can have been deleted under it.

    Args:
      request_id: The run's id as the Pipe forwarded it, or None.
      execution: The timed-out execution's name, recorded beside the claim.

    Returns:
      ``(reason, archive_id)`` — the archive id is the validated request id, or None when the
      input carried no valid one.

    Raises:
      None. A claim or read that fails is told as a possible deletion, because "nothing was
      deleted" is the one sentence that can then be false.
    """
    try:
        archive_id = paths.validated_request_id(request_id)
    except Exception as exc:  # noqa: BLE001
        logger.info("no valid request id on the timed-out execution: %s", exc)
        return _TIMEOUT_REASON, None
    try:
        record, _ = plan.record_source_decision(
            {"requestId": archive_id, "execution": {"name": execution}}, "stopped", 0
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not claim or read the source verdict for %s: %s", archive_id, exc)
        return _MAY_HAVE_DELETED_REASON, archive_id
    logger.info("source verdict for %s on timeout: %s", archive_id, record["decision"])
    if record["decision"] == "delete":
        return _MAY_HAVE_DELETED_REASON, archive_id
    return _TIMEOUT_REASON, archive_id


def _on_execution_timed_out(event) -> dict:
    """Notifies the actor that the whole run was stopped by the machine's own timeout.

    The wording is this plane's own rather than the generic failure sentence, and for an archive
    what it can promise is decided by delete-source's verdict record. The claim is taken before
    the no-recipient return, because it protects the originals whether or not anyone can be told
    — though only when the execution's input, and so its id, could be read.

    The request id for the payload comes from the same raw input as the actor, because the event
    carries no state and there is no recorded failure to read it from.

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
    payload = None
    if not isinstance(detail, dict):
        logger.info("timed-out execution event carries no detail object")
        detail = {}
    else:
        raw = events.timed_out_execution_input(detail)
        if not raw:
            logger.info("timed-out execution carries no input; nobody can be attributed")
        else:
            try:
                parsed = json.loads(raw)
                mode = _mode_from_raw_request(parsed)
                username = _actor_from_raw_request(parsed)
                payload = notify.request_payload(parsed)
            except ValueError as exc:
                logger.info("could not attribute the timed-out execution: %s", exc)

    archive_id = None
    if mode == "restore":
        reason = _RESTORE_TIMEOUT_REASON
    else:
        reason, archive_id = _archive_timeout_reason(
            (payload or {}).get("requestId"), _execution_name(detail)
        )

    if not username:
        observability.warning(
            "no verified actor on a timed-out execution; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return {"actor": {"username": ""}, "error": {"Error": "States.Timeout", "Cause": None}}

    tokens = {"requestId": archive_id} if archive_id else None
    notify.emit_notification(
        username, messages.failure_message(reason, tokens=tokens, mode=mode), payload=payload
    )
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
    it deliberately and the decorator fired on the way out. Firing is not always sending — the
    plane's ``emit_failure`` keeps a reason ``cpcommon.notify.is_silent`` names quiet — so this
    is also the half of that silence that runs here: a reused request id stays told by nobody
    only because this suppresses it too.

    The tempting heuristic — a dotted error name means the engine, a bare one means a handler
    ran — is wrong in the dangerous direction, and this fleet has the outage to prove it: a
    config module raising a bare ``RuntimeError`` at import is the shape of a real outage, and that
    rule would have silenced exactly the class of failure this function exists to report.

    The price is paid deliberately: an unexpected in-verb exception notifies through the
    decorator and again here, as two sentences — the decorator's asks the user to try again and
    this one does not — so the queue keeps both. A duplicate is a papercut on a path that is
    already a bug; a guess that suppresses is unrecoverable.

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

    No dedup id is passed, matching every other failure emitter on this plane: the queue
    deduplicates on content and an execution reaches this state at most once. The payload names
    the run, read from ``requestId`` or, where the error replaced the state, from the forwarded
    request under ``raw``; without it two runs failing alike render one body and collapse.

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

    if _verb_already_notified(request.get("error")) and is_silent(reason):
        logger.info("reason %s is told to nobody; nothing was sent for it", reason)
        observability.info(
            "suppressed a silent refusal",
            outcome="suppressed",
            reason=reason,
            notified=False,
        )
        return request

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
        messages.failure_message(reason, mode=_mode(request)),
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
