"""table-share notify-failure — the terminal failure notification (SPEC-152 FR-002).

THIS EXISTS FOR THE FAILURES NO VERB CAN CATCH. ``@notifies_on_failure`` is a decorator on
the verb handlers: it catches an exception *inside a verb*, and does nothing at all when
the failure happens where no verb code is running — a Lambda that fails at IMPORT, a state
timeout, a payload-size failure, a task that cannot be invoked at all. In that window the
sender is told nothing: no notification, no DLQ message, and the request simply never
completes.

IT IS THE WHOLE-REQUEST FAILURE ONLY, AND THAT IS THE DESIGN. A per-recipient failure ends
its own Map item at ``RecipientFailed`` and its siblings carry on, so the execution
SUCCEEDS and never reaches this function; the sender hears about that recipient from the
Map verb's own decorator. What reaches here is the failure that ended the whole request —
validate-authorize, inspect-source, or the Map state itself (a ``States.DataLimitExceeded``
on the collected results is the realistic one, which is why ``cpcommon.errors``
bounds every TerminalError detail). So there is no double-notification to design around on
the recipient path: the two paths are disjoint by construction.

ITS INPUT CARRIES THE RAW STEP FUNCTIONS ERROR, NOT A DECODED REASON, and it must stay
that way. RecordFailure passes ``error`` through as ``{Error, Cause}`` untouched, because
an ASL ``States.StringToJson`` on a Cause raises an UNCATCHABLE ``States.Runtime`` whenever
the Cause is absent or is not JSON, killing the execution on precisely the failures a user
most needs to hear about (#252). ``cpcommon.errors.failure_reason`` decodes it in Python,
where any shape is safe.

IT NEVER RAISES. The execution has already failed; the only thing this function can add is
a message, and a crash here would replace a friendly notification with nothing.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TransientError, failure_reason
from tscommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share request is several
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="table-share")


def _verb_already_notified(error) -> bool:
    """True when ``@notifies_on_failure`` ran, so this emit would be a second message.

    THE QUESTION IS WHETHER A VERB'S PYTHON RAN, and Lambda's own ``Error`` field answers
    it without any guessing. An exception raised inside a handler surfaces as its BARE
    class name — ``TerminalError``, ``KeyError``, ``ClientError`` — because Lambda reports
    ``type(exc).__name__``. Every error that means no handler code ran is an ENGINE name
    and carries a dot: ``States.Timeout``, ``States.DataLimitExceeded``, ``Lambda.Unknown``,
    ``Runtime.ImportModuleError`` (raised at IMPORT, before the handler is entered).

    ``TransientError`` is the one in-verb exception the decorator deliberately leaves
    un-notified — a Retry was still pending when it saw it — so an exhausted retry has told
    the sender nothing and must not be suppressed here.

    THE DEFAULT IS TO SPEAK. A malformed, absent or non-dict error is not evidence that a
    verb ran; FR-002 ranks a duplicate above a silence, so anything unrecognisable falls
    through to a notification.
    """
    if not isinstance(error, dict):
        return False
    name = error.get("Error")
    if not isinstance(name, str) or not name:
        return False
    if "." in name:
        return False
    return name != TransientError.__name__


# @traced is OUTERMOST and is the ONLY decorator here: @notifies_on_failure would be
# circular on the function whose whole job is the notification of last resort.
@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notify the sender that their share failed, and thread the request object onward."""
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    source = request.get("source") if isinstance(request.get("source"), dict) else {}

    # failure_reason never raises and never returns empty, so `reason` is always something
    # the resolver can map; an unmapped code (a raw SFN name like States.Timeout) falls
    # through to the generic rather than being shown to the user (SPEC-106 FR-008).
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
        # A PRE-IDENTITY FAILURE — a garbage or missing token, so validate-authorize raised
        # before it could bind an actor and ValidateFailureSeed seeded a null one. There is
        # no trustworthy recipient: the body's own actor field is attacker-controlled and
        # notifying it would let anyone deliver text to any inbox (the SPEC-126 rule). A
        # logged no-op is the correct outcome, not a lost message.
        logger.info("no verified sender on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    # NO kind/name: this is the whole-request phrasing ('Couldn't share "x": …'), not the
    # per-recipient one. Naming a recipient here would be a guess — the failure ended the
    # request before any recipient outcome existed.
    #
    # NO DEDUP ID, matching every other emitter on this plane: the notifications queue
    # dedups on content, and an execution reaches this state at most once.
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
