"""table-share notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the sender is told nothing:
no notification, no DLQ message, and the request simply never completes.

It is the whole-request failure only, and that is the design. A per-recipient failure ends its
own Map item and its siblings carry on, so the execution succeeds and never reaches this
function; the sender hears about that recipient from the Map verb's own decorator. What reaches
here is the failure that ended the whole request — the validate or inspect verb, or the Map
state itself, where a payload-size failure on the collected results is the realistic one, which
is why every terminal detail is bounded. The two paths are disjoint by construction, so there
is no double-notification to design around on the recipient path.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable runtime error whenever the Cause is absent or is not
JSON, killing the execution on precisely the failures a user most needs to hear about.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError, failure_reason
from tscommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a message for this failure.

    One name, not a heuristic, and the narrowness is the point. ``TerminalError`` is the only
    error treated as already-reported, because it is the only positive evidence: a verb raised
    it deliberately and the decorator fired on the way out.

    An earlier version inferred this from the absence of a dot — bare class name means a handler
    ran, dotted engine name means it did not. It is wrong in the dangerous direction: both config
    modules call their requirement check at module scope and raise a bare ``RuntimeError``, which
    is not hypothetical but this fleet's own recorded outage, and a dot-free name would have
    suppressed exactly the class of failure this function exists to report.

    The price is paid deliberately. An unexpected in-verb exception notifies through the
    decorator and again here, with the same generic sentence. A duplicate notification is
    preferable to none: a guess that suppresses is unrecoverable, a duplicate is a papercut on a
    path that is already a bug.

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
    """Notifies the sender that their share failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    The message uses the whole-request phrasing, with no recipient named: naming one would be a
    guess, because the failure ended the request before any recipient outcome existed. No dedup
    id is passed, matching every other emitter on this plane — the queue deduplicates on content
    and an execution reaches this state at most once.

    A failure with no verified sender is a logged no-op rather than a lost message: the body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

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
    source = request.get("source") if isinstance(request.get("source"), dict) else {}

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
        logger.info("no verified sender on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

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
