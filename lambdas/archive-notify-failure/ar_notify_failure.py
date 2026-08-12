"""archive notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can catch. ``@notifies_on_failure`` is a decorator on the
verb handlers: it catches an exception inside a verb and does nothing at all when the failure
happens where no verb code is running — a Lambda that fails at import, a state timeout, a
payload-size failure, a task that cannot be invoked. In that window the user is told nothing: no
notification, no DLQ message, and the request simply never completes. SPEC-152 exists to close
that, and a plane shipping without it leaves "it just never came back" reachable.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable ``States.Runtime`` whenever the Cause is absent or is
not JSON, killing the execution on precisely the failures a user most needs to hear about.

**THE ACTOR USUALLY COMES FROM THE REQUEST BODY, NOT FROM THE RECORDED FAILURE.** Every failure
this state exists for happens before a verb produced an actor, so the recorded object carries
``actor: null``; the machine's failure seed reads the Pipe's original body back from
``$$.Execution.Input`` so the actor can be recovered from the verified token. Without that this
function would take its no-recipient branch on every single failure — satisfied on paper, silent
in practice.

**IT HAS ONE DOOR, AND SAYING SO IS THE POINT.** File-send's twin grew a second, EventBridge
door because its machine has a top-level ``TimeoutSeconds`` and catchers do not cover a
top-level execution failure. This machine validates and stops: no Map, no manifest, no copy,
nothing that waits — so it has no timeout and there is no failure the ASL door cannot reach.
**SPEC-169 adds the transfer, and it must add the timeout, the EventBridge rule, the
``states:DescribeExecution`` grant and the second door with it** — a ceiling that cannot notify
is SPEC-152 satisfied on paper and silent in practice.
"""

import logging

from arcommon import messages, notify
from cpcommon import auth, events, observability
from cpcommon.errors import TerminalError, failure_reason

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


def _actor_from_raw_request(raw) -> str:
    """Recovers the verified actor from the Pipe's original request body.

    **This is what makes the state more than decorative.** The failures it exists for — a
    cold-start import error, a task that could not be invoked — all happen before any verb
    produced an actor, so the recorded-failure object carries ``actor: null`` every time.
    Without this the notifier would take its no-recipient branch on every single failure, and
    SPEC-152's guarantee would read as satisfied while telling nobody anything.

    The token is the ONLY acceptable source of the username; the body asserts nothing about who
    sent it. Expiry is deliberately not enforced, through the separately-named entry point the
    DLQ drain uses: a failure can surface long after the token was minted, and this path grants
    nothing — it only addresses a message.

    Args:
      raw: The Pipe's forwarded SQS batch, as captured at the top of the machine.

    Returns:
      The verified username, or an empty string when it cannot be recovered.

    Raises:
      None. Every failure degrades to no verified actor, which the caller logs as a no-op — a
      raise here would replace a missing notification with an unhandled error.
    """
    if raw is None:
        return ""
    try:
        body = events.parse_sqs_request(raw, reason="unauthorized")
        return auth.verified_username_ignoring_expiry(
            body.get("actor") if isinstance(body, dict) else None,
            missing_token_detail="missing actor token",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("could not recover a verified actor from the request: %s", exc)
        return ""


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
    """Notifies the actor that their archive failed, and threads the request object onward.

    ``@traced`` is the only decorator here: ``@notifies_on_failure`` would be circular on the
    function whose whole job is the notification of last resort.

    No dedup id is passed, matching every other emitter on this plane: the queue deduplicates on
    content and an execution reaches this state at most once.

    A failure with no verified actor is a logged no-op rather than a lost message. The body's
    own actor field is attacker-controlled, and notifying it would let anyone deliver text to
    any inbox.

    Args:
      event: The failed request carrying the raw Step Functions error.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a message,
      and a crash here would replace a friendly notification with nothing.
    """
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor")
    username = actor.get("username") if isinstance(actor, dict) else None
    username = username if isinstance(username, str) else ""
    if not username:
        username = _actor_from_raw_request(request.get("raw"))

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
        logger.info("no verified actor on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
        )
        return request

    notify.emit_notification(username, messages.failure_message(reason))
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=username,
        notified=True,
    )
    return request
