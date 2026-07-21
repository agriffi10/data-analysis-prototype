"""data-quality notify-failure — the terminal failure notification (SPEC-114 FR-004).

THIS EXISTS FOR THE FAILURES NO VERB CAN CATCH. ``@notifies_on_failure`` is a decorator on
the verb handlers: it catches an exception *inside a verb*, and does nothing at all when the
failure happens where no verb code is running —

  - a Lambda that fails at IMPORT (a bad layer, a config value that fails validate-at-init);
  - a STEP FUNCTIONS-level error (a state timeout, a payload-size failure, a task that
    cannot be invoked at all).

The state machine reaches this function on every failure path, after DropTempTablesOnFailure
and RecordFailure, so notification delivery does not depend on the failing verb having been
able to emit it. That is the condition SPEC-123's completed-checks-only dashboard was
accepted on: a check that fails must always reach the user with a concrete reason.

ITS INPUT CARRIES THE RAW STEP FUNCTIONS ERROR, NOT A DECODED REASON, and it must stay that
way. RecordFailure passes ``error`` through as ``{Error, Cause}`` untouched, because the ASL
decode that used to produce a ``reason`` field ran ``States.StringToJson`` in a Pass state —
which raises an UNCATCHABLE ``States.Runtime`` on any Cause that is absent or is not JSON
(``States.Timeout``, ``States.DataLimitExceeded``, ``Lambda.Unknown``), killing the execution
before it ever reached this function, on precisely the failures a user most needs to hear
about. ``cpcommon.errors.failure_reason`` does the decode in Python, where any shape is safe.

IT NEVER RAISES. The execution has already failed; the only thing this function can add is a
message, and a crash here would replace a friendly notification with nothing while also
polluting the recorded outcome.
"""

import logging

from cpcommon.errors import failure_reason
from dqcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context) -> dict:
    """Notify the actor that their check failed, and thread the request object onward."""
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    request_id = request.get("requestId")

    # The reason code, from whatever shape the failure left behind. failure_reason never
    # raises and never returns empty, so `reason` is always something the resolver can map;
    # an unmapped code (a raw SFN name like States.Timeout) falls through to the generic
    # rather than being shown to the user (SPEC-106 FR-008).
    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: requestId=%s actor=%s reason=%s", request_id, actor, reason)

    if request.get("reportKey"):
        # THE CHECK ACTUALLY SUCCEEDED. reportKey is null until assemble-report writes the
        # report, and assemble-report is followed only by DropTempTables — so a non-null
        # value here means the report exists, the success notification already went out
        # (assemble-report emits it immediately after the write), and what failed was
        # CLEANUP, after the fact.
        #
        # Telling the user their check failed at that point would flatly contradict the
        # message they already have, and the one they can act on is the success: their
        # report is real and their link works. The leaked temp table is an operator
        # problem, and it is already an ERROR log in drop-temp-tables plus a failed
        # execution in the console.
        #
        # Note this is NOT the common cleanup failure: a Glue DROP that fails is swallowed
        # by drop-temp-tables._drop and never reaches a terminal at all. What lands here is
        # the cleanup Lambda itself failing — an import error, a timeout — which no verb
        # code can catch, which is exactly why the suppression has to live here.
        logger.info(
            "report %s was written; suppressing the post-success cleanup failure for %s",
            request.get("reportKey"),
            request_id,
        )
        return request

    if not actor:
        # A PRE-IDENTITY FAILURE — a garbage or missing token, so validate-authorize raised
        # before it could bind an actor and ValidateFailureSeed seeded a null one. There is
        # no trustworthy recipient: the body's own username field is attacker-controlled and
        # notifying it would let anyone deliver text to any inbox. A logged no-op is the
        # correct outcome, not a lost message (mirrors tbcommon/notify.py).
        logger.info("no verified actor on the failed request; nothing to notify")
        return request

    # NO TOKENS ARE AVAILABLE HERE and none are needed. The raw error yields a reason code
    # and nothing else, so a body with {object}/{count} markers would render them literally
    # — but this emit only reaches the user when the decorator's did not, and the decorator
    # covers every TerminalError raised inside a verb (which is every reason that HAS
    # markers). What lands here instead is the no-verb-ran class, whose reasons carry none.
    # When both fire, the decorator's emit wins the FIFO dedup: it is sent first, seconds
    # earlier, under the identical {requestId}:failure id (dqcommon.notify.FAILURE_STEP).
    notify.emit_notification(
        actor,
        messages.failure_message(reason, str(request.get("location") or "")),
        dedup_id=f"{request_id}:{notify.FAILURE_STEP}" if request_id else None,
    )
    return request
