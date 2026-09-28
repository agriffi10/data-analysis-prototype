"""shared-space notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. The other three planes wrap their verbs in a
failure decorator; this one notifies from inside each handler instead. Either way the mechanism
needs the verb's Python to run, and it does not run when the execution dies before or outside
it — a Lambda that fails at import, a state timeout, a task that cannot be invoked at all.

That is not hypothetical here of all places. This plane's own history is a shared layer's
import-time requirement raising on one missing environment variable, killing every verb at cold
start before a single line of handler code, and the same shape repeated on the singleton Lambdas
for nine days. A user in that window sees a request they submitted, a toast saying it was
accepted, and then permanent silence.

It suppresses nothing, which is the opposite of the other two planes. Create and delete emit
their own failure message from inside the handler; the other five verbs emit none, so a guard
keyed on whether a verb ran would restore the silence for five of seven actions. The duplicate
is collapsed by the FIFO dedup token instead, reproduced byte-for-byte from the action and
actor. Where a verb already spoke, SQS drops this message; where none did, it is the only one
the user gets. The token is per outcome rather than per verb, which is what makes reproducing it
possible at all.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable runtime error whenever the Cause is absent or is not
JSON, on precisely the failures a user most needs to hear about.

**Its send waits rather than being capped** (``bounded=False``), as every failure door's does. The
run has already failed, so a stall can fail nothing the user was told, and a capped send would
give up on a slow queue with the notice unsent.
"""

import logging

import messages
from cpcommon import observability
from cpcommon.errors import failure_reason
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def _dedup(request_id, action: str, actor: str) -> str | None:
    """Reproduces the verb's own failure token so SQS collapses the pair.

    The create and delete verbs both emit this exact token on their handled-failure path, and
    matching it is the whole suppression mechanism — so it must not be tidied into a token of its
    own.

    Args:
      request_id: The run's request id.
      action: The requested action.
      actor: The verified actor.

    Returns:
      The token, or None without a request id, which falls back to the queue's content-based
      dedup rather than inventing an id that could collide across requests.

    Raises:
      None.
    """
    return f"{request_id}:{action}-failed:{actor}" if request_id and action else None


@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notifies the actor that their shared-space request failed, and threads it onward.

    ``@traced`` is the only decorator on this plane, and here it is also the only one that could
    be: a failure decorator on the notification of last resort would be circular.

    Every COMPOSED message ends on the generic clause, deliberately: every reason that can reach
    this path by way of a fault is a raw engine name and none may be shown to a user. What carries
    the information is the action, not the reason.

    **An expected refusal arrives with its sentence already written**, in ``message``, and that one
    is used verbatim. The two cases differ in what they are able to say: a fault knows the action
    and the space, while a refusal usually has to name the MEMBER it is about, and a composer
    holding only an action and a space cannot. The wording is still a literal in the domain layer
    — the refusal is composed there, at a point that has the name to hand — so this is not a
    second place messages are written.

    A failure with no verified actor is a logged no-op rather than a lost message: the body's own
    username is attacker-controlled, and notifying it would let anyone deliver text to any inbox.
    A run with no request id records that explicitly, because the span must carry no invented one
    and so cannot be joined to its run — what the event says about itself is the whole record.

    Args:
      event: The failed request, carrying the raw Step Functions error.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a message,
      and a crash here would replace a friendly notification with nothing.
    """
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    action = request.get("action") or ""
    space = request.get("space") or ""
    request_id = request.get("requestId")

    reason = failure_reason(request.get("error"))
    logger.info(
        "notify-failure: requestId=%s actor=%s action=%s reason=%s",
        request_id, actor, action, reason,
    )

    if not request_id:
        observability.warning("no requestId on the failed request", actor_bound=bool(actor))

    if not actor:
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
        request.get("message") or messages.failure_message(action, space, reason),
        dedup_id=_dedup(request_id, action, actor),
        bounded=False,
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
