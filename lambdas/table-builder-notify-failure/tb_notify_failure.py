"""table-builder notify-failure — the terminal failure notification (SPEC-152 FR-002).

THIS EXISTS FOR THE FAILURES NO VERB CAN CATCH. ``@notifies_on_failure`` is a decorator on
the verb handlers: it catches an exception *inside a verb*, and does nothing at all when
the failure happens where no verb code is running —

  - a Lambda that fails at IMPORT (a bad layer, a config value that fails validate-at-init);
  - a STEP FUNCTIONS-level error (a state timeout, a payload-size failure, a task that
    cannot be invoked at all);
  - a ``TransientError`` that exhausts its Retry, which the decorator passes through
    UN-notified by design because a retry was still pending when it saw it.

None of those is hypothetical for this fleet. SPEC-137 shipped three singleton Lambdas
that raised ``ModuleNotFoundError`` at cold start for nine days; a table-builder verb
failing the same way produces the same silence, and the user has no admin UI to check and
no reason to suspect anything but slowness.

ITS INPUT CARRIES THE RAW STEP FUNCTIONS ERROR, NOT A DECODED REASON, and it must stay
that way. RecordFailure passes ``error`` through as ``{Error, Cause}`` untouched, because
the ASL decode that would produce a reason runs ``States.StringToJson`` — which raises an
UNCATCHABLE ``States.Runtime`` on any Cause that is absent or is not JSON
(``States.Timeout``, ``States.DataLimitExceeded``, ``Lambda.Unknown``), killing the
execution before it ever reached this function, on precisely the failures a user most
needs to hear about (#252). ``cpcommon.errors.failure_reason`` does the decode in Python,
where any shape is safe.

IT SUPPRESSES WHAT A VERB ALREADY SAID. This state sits on EVERY failure path, so without
a guard an ordinary ``TerminalError`` would notify twice — once from the decorator, once
from here — and the decorator's message is strictly the better one (it carries the verb's
``err.tokens``, which this path has no way to reconstruct). ``_verb_already_notified`` is
that guard, and it suppresses on ONE positively-identified name rather than on a heuristic:
read its docstring before widening it, because the obvious generalisation silences the
failure this whole spec exists to report.

This is deliberately NOT data-quality's mechanism. That plane collapses the pair with an
identical FIFO dedup token because ``dqcommon`` centralises one ``FAILURE_STEP``;
``tbcommon`` deduplicates per VERB step, and unifying it would change notification
behaviour on paths that already work — out of scope for SPEC-152.

IT NEVER RAISES. The execution has already failed; the only thing this function can add is
a message, and a crash here would replace a friendly notification with nothing.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError, failure_reason
from tbcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-builder run is several
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="table-builder")

#: The dedup token for this emit. One per OUTCOME, not per verb (SPEC-114): an execution
#: reaches this state at most once, and the token only has to keep this failure message
#: distinct from the run's success message.
FAILURE_STEP = "failure"


def _verb_already_notified(error) -> bool:
    """True when ``@notifies_on_failure`` ran, so this emit would be a second message.

    ONE NAME, NOT A HEURISTIC, and the narrowness is the point. ``TerminalError`` is the
    only error this function will treat as already-reported, because it is the only one
    that is POSITIVE evidence: a verb raised it deliberately, the decorator's
    ``emit_terminal`` fired on the way out, and that message is strictly better than
    anything reconstructable here — it carries ``err.tokens``, without which a
    ``columns_removed`` refusal cannot name the columns it is refusing over.

    AN EARLIER VERSION INFERRED THIS FROM THE ABSENCE OF A DOT — bare class name means a
    handler ran, dotted engine name means it did not. It is wrong in the dangerous
    direction. ``cpcommon.config`` calls ``_require`` at MODULE SCOPE and raises a bare
    ``RuntimeError``; that is not a hypothetical shape but this fleet's own recorded
    outage (``lambda.tf``: "check-table-absent: RuntimeError COGNITO_USER_POOL_ID unset",
    PR #196). A dot-free name would have suppressed it — silencing the exact class of
    failure this spec was written to report, on the plane it actually happened to.

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
    """Notify the actor that their build failed, and thread the request object onward."""
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    request_id = request.get("requestId")

    # failure_reason never raises and never returns empty, so `reason` is always something
    # the resolver can map; an unmapped code (a raw SFN name like States.Timeout) falls
    # through to the generic rather than being shown to the user (SPEC-106 FR-008).
    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: requestId=%s actor=%s reason=%s", request_id, actor, reason)

    if not request_id:
        # SPEC-128 FR-002 requires the span to carry NO request_id rather than an invented
        # one, so this event cannot be joined to its run — what it says about itself is the
        # whole record. This verb is the one most likely to be handed a malformed event,
        # and it is invoked precisely when the rest of the run has already gone wrong.
        observability.warning("no requestId on the failed request", actor_bound=bool(actor))

    if _verb_already_notified(request.get("error")):
        # A VERB RAISED THIS AND THE DECORATOR ALREADY NOTIFIED, with a better message: it
        # carries err.tokens — the removed column names a `columns_removed` refusal is
        # meaningless without.
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
        logger.info("no verified actor on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    # `mode` picks the verb in the sentence, and getting it wrong is worse than generic:
    # telling a user they can't CREATE a table they were trying to REFRESH is about the
    # most confusing thing this layer could say (tbcommon.messages). RecordFailure carries
    # it for exactly this call, and ValidateFailureSeed seeds it for the one path that has
    # no validated mode to carry.
    notify.emit_notification(
        actor,
        messages.failure_message(
            reason,
            request.get("tableName") or "",
            request.get("database") or "",
            request.get("mode") or "create",
        ),
        dedup_id=f"{request_id}:{FAILURE_STEP}" if request_id else None,
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=actor,
        notified=True,
    )
    return request
