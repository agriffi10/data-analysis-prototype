"""file-send notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the sender is told nothing:
no notification, no DLQ message, and the request simply never completes. SPEC-152 exists to
close that, and a plane shipping without it leaves "it just never came back" reachable.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable ``States.Runtime`` whenever the Cause is absent or is
not JSON, killing the execution on precisely the failures a user most needs to hear about.

**ONE DOOR AT THIS STAGE.** Table-share's twin has a second — an EventBridge ``TIMED_OUT``
rule — because SPEC-161 gave that machine a top-level ``TimeoutSeconds``, which terminates a
run outright where no Catch fires. This machine has neither: it calls one 15-second validator
and stops. SPEC-166 adds the long Distributed-Map copy, and the timeout, the rule and this
function's second door must arrive together with it.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError, failure_reason
from fscommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")


def _verb_already_notified(error) -> bool:
    """Reports whether the verb decorator already sent a message for this failure.

    One name, not a heuristic, and the narrowness is the point. ``TerminalError`` is the only
    error treated as already-reported, because it is the only positive evidence: a verb raised
    it deliberately and the decorator fired on the way out.

    The tempting heuristic — a dotted error name means the engine, a bare one means a handler
    ran — is wrong in the dangerous direction, and this fleet has the outage to prove it: a
    config module raising a bare ``RuntimeError`` at import is PR #196's own shape, and that
    rule would have silenced exactly the class of failure this function exists to report.

    The price is paid deliberately: an unexpected in-verb exception notifies through the
    decorator and again here, with the same generic sentence. A duplicate is a papercut on a
    path that is already a bug; a guess that suppresses is unrecoverable.

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
    """Notifies the sender that their send failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    The message uses the whole-request phrasing with no recipient named — naming one would be a
    guess, because the failure ended the request before any per-recipient outcome existed. No
    dedup id is passed, matching every other emitter on this plane: the queue deduplicates on
    content and an execution reaches this state at most once.

    A failure with no verified sender is a logged no-op rather than a lost message. The body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

    Args:
      event: The failed request carrying the raw Step Functions error.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a
      message, and a crash here would replace a friendly notification with nothing.
    """
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor")
    username = actor.get("username") if isinstance(actor, dict) else None
    username = username if isinstance(username, str) else ""

    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: actor=%s reason=%s", username, reason)

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
        logger.info("no verified sender on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    notify.emit_notification(username, messages.failure_message(reason))
    observability.info(
        "notified the sender of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
