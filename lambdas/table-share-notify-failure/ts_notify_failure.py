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
from cpcommon.errors import TerminalError, failure_reason
from tscommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share request is several
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="table-share")


def _verb_already_notified(error) -> bool:
    """True when ``@notifies_on_failure`` ran, so this emit would be a second message.

    ONE NAME, NOT A HEURISTIC, and the narrowness is the point. ``TerminalError`` is the
    only error this function will treat as already-reported, because it is the only one
    that is POSITIVE evidence: a verb raised it deliberately and the decorator's
    ``emit_terminal`` fired on the way out.

    AN EARLIER VERSION INFERRED THIS FROM THE ABSENCE OF A DOT — bare class name means a
    handler ran, dotted engine name means it did not. It is wrong in the dangerous
    direction. ``tscommon.config`` and ``cpcommon.config`` both call ``_require`` at MODULE
    SCOPE and raise a bare ``RuntimeError``; that is not a hypothetical shape but this
    fleet's own recorded outage (PR #196). A dot-free name would have suppressed it —
    silencing the exact class of failure this spec was written to report.

    THE PRICE IS PAID DELIBERATELY. An unexpected in-verb exception (a ``KeyError``, a
    ``ClientError``) notifies through the decorator's ``emit_unexpected`` AND again here,
    and the two carry the same generic sentence. FR-002 settles it: "a duplicate
    notification is preferable to none". A guess that suppresses is unrecoverable; a
    duplicate is a papercut on a path that is already a bug.
    """
    return isinstance(error, dict) and error.get("Error") == TerminalError.__name__


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
