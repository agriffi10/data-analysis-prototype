"""shared-space notify-failure — the terminal failure notification (SPEC-152 FR-002).

THIS EXISTS FOR THE FAILURES NO VERB CAN CATCH. The other three planes wrap their verbs in
``@notifies_on_failure``; this one notifies from INSIDE each handler instead (SPEC-134
FR-002). Either way the mechanism needs the verb's Python to run, and it does not run when
the execution dies before or outside it — a Lambda that fails at IMPORT, a state timeout, a
task that cannot be invoked at all.

That is not hypothetical HERE OF ALL PLACES. PR #196 is this plane's own history: the
shared layer's import-time ``_require`` raised on one missing environment variable and
every verb died at cold start, before a single line of handler code. SPEC-137 repeated the
shape on the singleton Lambdas nine days running. A user in that window sees a request they
submitted, a toast that said it was accepted, and then permanent silence.

WHY IT SUPPRESSES NOTHING, WHICH IS THE OPPOSITE OF THE OTHER TWO PLANES. ``create`` and
``delete`` emit their own failure message from inside the handler; the other five verbs
emit NONE. A Python guard keyed on "did a verb run" would therefore restore the silence for
five of seven actions — so the duplicate is collapsed by the FIFO DEDUP TOKEN instead, which
this verb reproduces byte-for-byte from the action and actor (``{requestId}:create-failed:
{actor}``, ``{requestId}:delete-failed:{actor}``). Where a verb already spoke, SQS drops
this message; where none did, it is the only one the user gets. The token is per OUTCOME,
not per verb, which is what makes reproducing it possible at all.

ITS INPUT CARRIES THE RAW STEP FUNCTIONS ERROR, NOT A DECODED REASON, and it must stay
that way. RecordFailure passes ``error`` through as ``{Error, Cause}`` untouched, because
an ASL ``States.StringToJson`` on a Cause raises an UNCATCHABLE ``States.Runtime`` whenever
the Cause is absent or is not JSON — on precisely the failures a user most needs to hear
about (#252). ``cpcommon.errors.failure_reason`` decodes it in Python, where any shape is
safe.

IT NEVER RAISES. The execution has already failed; the only thing this function can add is
a message, and a crash here would replace a friendly notification with nothing.
"""

import logging

import messages
from cpcommon import observability
from cpcommon.errors import failure_reason
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field.
observability.init(service="shared-space")


def _dedup(request_id, action: str, actor: str) -> str | None:
    """The verb's OWN failure token, reproduced so SQS collapses the pair.

    ``create_space`` and ``delete_space`` both emit ``{requestId}:{action}-failed:{actor}``
    on their handled-failure path. Matching it exactly is the whole suppression mechanism
    (see the module note), so this must not be "tidied" into a token of its own.

    ``None`` without a requestId, which falls back to the queue's content-based dedup
    rather than inventing an id that could collide across requests.
    """
    return f"{request_id}:{action}-failed:{actor}" if request_id and action else None


# @traced is the ONLY decorator on this plane (SPEC-134 FR-002), and here it is also the
# only one that could be: a failure decorator on the notification of last resort would be
# circular.
@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notify the actor that their shared-space request failed, and thread it onward."""
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    action = request.get("action") or ""
    space = request.get("space") or ""
    request_id = request.get("requestId")

    # failure_reason never raises and never returns empty. Nothing it can return here is a
    # registered code, so every message ends on the generic clause — deliberately: every
    # reason that reaches this path is a raw engine name and SPEC-106 FR-008 forbids
    # showing one. What carries the information is the ACTION, not the reason.
    reason = failure_reason(request.get("error"))
    logger.info(
        "notify-failure: requestId=%s actor=%s action=%s reason=%s",
        request_id, actor, action, reason,
    )

    if not request_id:
        # SPEC-128 FR-002 requires the span to carry NO request_id rather than an invented
        # one, so this event cannot be joined to its run — what it says about itself is the
        # whole record.
        observability.warning("no requestId on the failed request", actor_bound=bool(actor))

    if not actor:
        # A PRE-VALIDATION FAILURE — a garbage or missing token, so Validate raised before
        # it could bind an actor and ValidateFailureSeed seeded a null one. There is no
        # trustworthy recipient: the body's own username is attacker-controlled and
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

    emit_notification(
        actor,
        messages.failure_message(action, space, reason),
        dedup_id=_dedup(request_id, action, actor),
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=actor,
        space=space,
        notified=True,
    )
    return request
