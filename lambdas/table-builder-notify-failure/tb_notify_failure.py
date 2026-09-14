"""table-builder notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on
the verb handlers: it catches an exception inside a verb and does nothing at all when the
failure happens where no verb code is running — a Lambda that fails at import, a Step
Functions-level error such as a state timeout, or a transient error that exhausts its Retry,
which the decorator passes through un-notified by design because a retry was still pending when
it saw it. None of those is hypothetical for this fleet: three singleton Lambdas once raised
``ModuleNotFoundError`` at cold start for nine days, and a table-builder verb failing the same
way produces the same silence.

Two Step Functions errors never reach it by either door. ``States.DataLimitExceeded`` is caught
only by a catcher that names it, and none in this machine does; ``States.Runtime`` is caught by
nothing, ``States.ALL`` included. Either ends the run FAILED, which the timeout door below does
not match, so a failure no verb had already reported reaches nobody. The machine is built so
that neither is raised.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay
that way — the ASL decode that would produce a reason raises an uncatchable runtime error on
any Cause that is absent or not JSON, killing the execution before it reaches this function,
on precisely the failures a user most needs to hear about.

This is deliberately not data-quality's mechanism. That plane collapses the duplicate pair
with an identical FIFO dedup token because its layer centralises one failure step; this
layer deduplicates per verb step, and unifying it would change notification behaviour on
paths that already work.

Two entry shapes reach the one handler, dispatched on the detail-type. The ASL state passes the
request object; EventBridge passes a status-change event for a run the machine's own
``TimeoutSeconds`` stopped. That second door is not optional here — a top-level timeout terminates
the execution outright and no ``Catch`` covers it, so without the door an hour-long build ends in
silence, which is the one failure a user is least able to diagnose.

Attributes:
  FAILURE_STEP: The dedup token for this emit. One per outcome rather than per verb: an
    execution reaches this state at most once, and the token only has to keep this failure
    message distinct from the run's success message.
  TIMEOUT_STEP: The dedup token for the timeout emit, distinct from ``FAILURE_STEP`` so a run
    that somehow reached both states says both things rather than having the second collapse
    into the first.
"""

import json
import logging

from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError, failure_reason
from cpcommon.notify import dedup_id
from tbcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

FAILURE_STEP = "failure"
TIMEOUT_STEP = "timeout"

_TIMEOUT_DETAIL_TYPE = "Step Functions Execution Status Change"
_TIMEOUT_REASON = "build_timed_out"


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


def _text(value) -> str:
    """Narrows a display-only body field to a string, discarding anything else.

    The container is type-guarded a few lines below and the leaves read out of it were not, which
    is a real gap rather than defensive padding: ``messages.failure_message`` reaches
    ``str.replace(marker, value)``, which raises ``TypeError`` on a non-string **whether or not the
    marker occurs**. A raise inside this door is an async Lambda failure EventBridge retries, so one
    malformed body would become three, on the one failure the user most needs to hear about.

    Args:
      value: A body field that reaches the message text.

    Returns:
      The value when it is a string, otherwise an empty string.

    Raises:
      None.
    """
    return value if isinstance(value, str) else ""


def _timed_out_request(detail) -> dict:
    """Recovers the actor and the table from a timed-out execution's own input.

    The input is the Pipe's forwarded SQS batch, so this is the same parse every verb does, then
    the identity block — the ONLY acceptable source of the username, since the body's own actor
    field is producer-supplied. ``tableName``, the database and the mode are display-only: they
    reach the message text, and that text goes to an inbox the verified actor chose.

    This reads ``detail.input`` directly rather than through
    ``cpcommon.events.timed_out_execution_input``. That helper exists for planes whose execution
    input can approach EventBridge's 256 KB event cap, where Step Functions drops the input and
    the door must read it back with ``DescribeExecution``. A table-build request is a table name,
    a database and a short partition-key list, so it cannot approach the cap — and taking the
    helper anyway would oblige this plane's role to carry a ``states:DescribeExecution`` grant it
    has no other use for.

    Args:
      detail: The event's ``detail`` block.

    Returns:
      A request-shaped dict carrying the verified actor and the display context — or an empty
      dict when the input was omitted or cannot be attributed.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op. That
      includes a ``detail`` of the wrong type: a raise here would be an async Lambda failure and
      EventBridge retries those, turning one unattributable event into three.
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

    space = body.get("space") if isinstance(body.get("space"), dict) else {}
    return {
        "actor": actor,
        "requestId": body.get("requestId"),
        "tableName": _text(body.get("tableName")),
        "database": _text(space.get("database")),
        "mode": body.get("mode") if body.get("mode") in ("create", "refresh") else "create",
        "error": {"Error": "States.Timeout", "Cause": None},
    }


def _on_execution_timed_out(event) -> dict:
    """Notifies the actor that the whole run was stopped by the machine's own timeout.

    The wording carries two things the generic sentence does not, and both are load-bearing.

    It says the table **may or may not** have been built, because the resolver's own prefix reads
    "Couldn't create table X" and that alone is false: ``ExecuteDdl`` and ``ApplyRefresh`` run
    before the deadline, so a timeout can land with the table already created. The verbs also emit
    their SUCCESS notification inline — ``execute_ddl`` at the end of its own handler, with
    ``ReleaseRefreshLock`` and ``RecordSuccess`` still to run — so a timeout in that tail window
    delivers "ready to query" and this sentence for one run. Saying "may or may not" is what keeps
    that pair from contradicting itself.

    And it tells the actor to wait before retrying, because a top-level timeout runs neither
    ``ReleaseRefreshLock`` nor its on-failure twin, so the refresh lock is stranded.
    ``table_lock.STALE_LOCK_SECONDS`` is the machine timeout plus 900 s, and the lock is claimed
    early in the run, so it is not stealable for roughly another fifteen minutes. Without the
    clause the advice earns a ``refresh_already_running`` refusal that says a refresh "is already
    running" when nothing is, and gives no bound.

    Args:
      event: The EventBridge event.

    The request id is stamped rather than merely passed to ``dedup_id``. ``observability`` reads it
    off the event's own shape, and a status-change event is none of the shapes it knows, so without
    this the one notification an operator most needs to correlate to a build is the only one whose
    records carry no ``request_id`` to join on.

    **The run's TRACE is a separate gap, and it is not closed here.** The value is in reach — the
    traceparent rides in the same body this function already parses — but nothing sanctioned adopts
    it: ``_shape_values`` does not walk that far, and ``observability`` exposes no public helper for
    joining a trace read by hand, while ``stamp``'s own contract says a call site never imports
    ``log_foundry`` directly. So this is a missing door in the shared module rather than a decision
    of this plane's, and the same is true of all six timeout doors. A spec is open on the wider
    version of the problem; when it lands a helper, this function has the value ready to pass it.

    **The function's 15 s timeout is deliberately left alone**, where five sibling doors sit at 60.
    Three of those read the execution input back with ``DescribeExecution`` when EventBridge drops
    an oversized one — an AWS call with its own retries — and this door does not, by design. What it
    does instead is a JSON parse and one queue send, measured at roughly 35x headroom inside 15 s.
    Raising it to match would also move a pinned fleet parity fixture, which is a real declaration
    to make for a cosmetic reason.

    Args:
      event: The EventBridge event.

    Returns:
      The recovered request, for the log and for symmetry with the ASL door.

    Raises:
      None.
    """
    request = _timed_out_request(event.get("detail") or {})
    actor = request.get("actor") or ""

    request_id = request.get("requestId")
    if request_id:
        observability.stamp(request_id=request_id)

    if not actor:
        logger.info("timed-out execution has no verified actor; nothing to notify")
        observability.warning(
            "no verified actor on a timed-out execution; nothing to notify",
            outcome="no-recipient",
            reason=_TIMEOUT_REASON,
            notified=False,
        )
        return request

    notify.emit_notification(
        actor,
        messages.failure_message(
            _TIMEOUT_REASON,
            request.get("tableName") or "",
            request.get("database") or "",
            request.get("mode") or "create",
        ),
        dedup_id=dedup_id(request.get("requestId"), TIMEOUT_STEP),
    )
    logger.info("notified %s that their build timed out", actor)
    observability.info(
        "notified the actor that the execution timed out",
        outcome="notified",
        reason=_TIMEOUT_REASON,
        actor=actor,
        notified=True,
    )
    return request


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a better message for this failure.

    One name, not a heuristic, and the narrowness is the point. ``TerminalError`` is the only
    error treated as already-reported, because it is the only positive evidence: a verb raised
    it deliberately, the decorator fired on the way out, and that message carries the tokens
    without which a columns-removed refusal cannot name the columns it is refusing over.

    An earlier version inferred this from the absence of a dot — bare class name means a
    handler ran, dotted engine name means it did not. It is wrong in the dangerous direction:
    ``cpcommon.config`` calls its requirement check at module scope and raises a bare
    ``RuntimeError``, which is not hypothetical but this fleet's own recorded outage, and a
    dot-free name would have suppressed exactly the class of failure this function exists to
    report.

    The price is paid deliberately. An unexpected in-verb exception notifies through the
    decorator and again here, with the same generic sentence. A duplicate notification is
    preferable to none: a guess that suppresses is unrecoverable, a duplicate is a papercut on
    a path that is already a bug.

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
    """Notifies the actor that their build failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort. The mode picks the verb in the
    sentence, and getting it wrong is worse than generic — telling a user they cannot create a
    table they were trying to refresh is about the most confusing thing this layer could say.

    Two entry shapes reach here, dispatched on the detail-type: the ASL state's request object,
    and EventBridge's status-change event for a run the machine's own ``TimeoutSeconds`` stopped.
    One function rather than two because they end in the same place — one verified actor, one
    sentence, one queue — and a second function would be a second copy of the emit with a second
    chance to drift.

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
    request_id = request.get("requestId")

    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: requestId=%s actor=%s reason=%s", request_id, actor, reason)

    if not request_id:
        observability.warning("no requestId on the failed request", actor_bound=bool(actor))

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
        logger.info("no verified actor on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    notify.emit_notification(
        actor,
        messages.failure_message(
            reason,
            request.get("tableName") or "",
            request.get("database") or "",
            request.get("mode") or "create",
        ),
        dedup_id=dedup_id(request_id, FAILURE_STEP),
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=actor,
        notified=True,
    )
    return request
