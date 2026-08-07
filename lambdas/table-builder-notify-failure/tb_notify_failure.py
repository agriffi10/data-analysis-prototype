"""table-builder notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on
the verb handlers: it catches an exception inside a verb and does nothing at all when the
failure happens where no verb code is running — a Lambda that fails at import, a Step
Functions-level error such as a state timeout or a payload-size failure, or a transient error
that exhausts its Retry, which the decorator passes through un-notified by design because a
retry was still pending when it saw it. None of those is hypothetical for this fleet: three
singleton Lambdas once raised ``ModuleNotFoundError`` at cold start for nine days, and a
table-builder verb failing the same way produces the same silence.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay
that way — the ASL decode that would produce a reason raises an uncatchable runtime error on
any Cause that is absent or not JSON, killing the execution before it reaches this function,
on precisely the failures a user most needs to hear about.

This is deliberately not data-quality's mechanism. That plane collapses the duplicate pair
with an identical FIFO dedup token because its layer centralises one failure step; this
layer deduplicates per verb step, and unifying it would change notification behaviour on
paths that already work.

Attributes:
  FAILURE_STEP: The dedup token for this emit. One per outcome rather than per verb: an
    execution reaches this state at most once, and the token only has to keep this failure
    message distinct from the run's success message.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError, failure_reason
from tbcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

FAILURE_STEP = "failure"


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

    Args:
      event: The failed request, carrying the raw Step Functions error.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a
      message, and a crash here would replace a friendly notification with nothing.
    """
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
