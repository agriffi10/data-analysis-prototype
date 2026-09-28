"""data-quality notify-failure — the terminal failure notification of last resort.

This exists for the failures no verb can report. The verb decorator reports an exception raised
inside a verb, and reports nothing when the verb's own code cannot run to do it — a verb Lambda
that fails at import or is killed at its timeout, or a task that cannot be invoked — nor for a
``TransientError``, which it passes through to the Retry. Each of those is an error the Task
raises, so once any retries run out its ``States.ALL`` Catch still routes it here.

The state machine reaches this function on every CAUGHT failure path, after cleanup and the
recorded failure, so notification delivery does not depend on the failing verb having been able to
emit it. That is the condition the completed-checks-only dashboard was accepted on. Two Step
Functions errors never arrive: ``States.Runtime``, which ``States.ALL`` does not catch and a Pass
or Choice state cannot catch at all, and ``States.DataLimitExceeded``, which only a catcher naming
it can catch and none here does. The machine is built so neither is raised. If one is, a failure
no verb had already reported reaches nobody, and the same holds when this function itself fails —
an import error in code it shares with the verbs included — because its own Catch leads straight
to the terminal Fail.

Its input carries the raw Step Functions error rather than a decoded reason, and must stay that
way — an ASL decode raises an uncatchable runtime error on any Cause that is absent or is not
JSON, killing the execution before it ever reaches this function, on precisely the failures a
user most needs to hear about.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

**Its send waits rather than being capped** (``bounded=False``), as every failure door's does. The
run has already failed, so a stall can fail nothing the user was told, and a capped send would
give up on a slow queue with the notice unsent.
"""

import logging

from cpcommon import observability
from cpcommon.errors import failure_reason
from cpcommon.notify import dedup_id
from dqcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")


@observability.traced("notify-failure")
def handler(event, context) -> dict:
    """Notifies the actor that their check failed, and threads the request object onward.

    ``@traced`` is the only decorator here: a failure decorator on the notification of last
    resort would be circular.

    A run whose report key is set actually succeeded. That key is null until the report is
    written, and only cleanup follows, so a non-null value here means the report exists, the
    success notification already went out, and what failed was cleanup after the fact. Telling
    the user their check failed at that point would flatly contradict the message they already
    have, and the one they can act on is the success: their report is real and their link works.
    The leaked temp table is an operator problem, already an error log and a failed execution in
    the console. Note this is not the common cleanup failure — a drop that fails is swallowed by
    the cleanup verb and never reaches a terminal at all. What lands here is the cleanup Lambda
    itself failing, which no verb code can catch, which is exactly why the suppression lives here.

    A failure with no verified actor is a logged no-op rather than a lost message: the body's own
    username is attacker-controlled, and notifying it would let anyone deliver text to any inbox.
    A run with no request id records that explicitly, because the span must carry no invented one
    and so cannot be joined to its run — this verb is the one most likely to be handed a malformed
    event, and it is invoked precisely when the rest of the run has already gone wrong.

    No message tokens are available here and none are needed. The raw error yields a reason code
    and nothing else, so a body with markers would render them literally — but this emit only
    reaches the user when the decorator's did not, and the decorator covers every terminal raised
    inside a verb, which is every reason that has markers. What lands here instead is the
    no-verb-ran class, whose reasons carry none. When both fire, the decorator's emit wins the
    FIFO dedup: it is sent first, seconds earlier, under the identical token.

    A silent reason sends nothing. A reused request id is refused because another execution holds
    it, and that execution is the one that reports. The browser mints a fresh id per submit, so a
    reuse comes from a request somebody built by hand, which has nothing it should be told.

    The link is always absent, and that is not a placeholder: this path runs only when no report
    was written, and the link builder mints nothing where the report view would resolve wrong. No
    link is a real state, distinct from no notification.

    Args:
      event: The failed request, carrying the raw Step Functions error.
      context: The Lambda context, unused.

    Returns:
      The request object, threaded onward unchanged.

    Raises:
      None. The execution has already failed; the only thing this function can add is a message,
      and a crash here would replace a friendly notification with nothing while also polluting
      the recorded outcome.
    """
    request = dict(event) if isinstance(event, dict) else {}
    actor = request.get("actor") or ""
    request_id = request.get("requestId")

    reason = failure_reason(request.get("error"))
    logger.info("notify-failure: requestId=%s actor=%s reason=%s", request_id, actor, reason)

    if not request_id:
        observability.warning("no requestId on the failed request", actor_bound=bool(actor))

    if notify.is_silent(reason):
        observability.info(
            "suppressed a silent refusal",
            outcome="suppressed",
            reason=reason,
            notified=False,
            link=False,
        )
        return request

    if request.get("reportKey"):
        logger.info(
            "report %s was written; suppressing the post-success cleanup failure for %s",
            request.get("reportKey"),
            request_id,
        )
        observability.info(
            "suppressed a post-success failure",
            outcome="suppressed",
            reason=reason,
            report_key=request.get("reportKey"),
            notified=False,
            link=False,
        )
        return request

    if not actor:
        logger.info("no verified actor on the failed request; nothing to notify")
        observability.warning(
            "no verified actor; nothing to notify",
            outcome="no-recipient",
            reason=reason,
            notified=False,
            link=False,
        )
        return request

    notify.emit_notification(
        actor,
        messages.failure_message(reason, str(request.get("location") or "")),
        dedup_id=dedup_id(request_id, notify.FAILURE_STEP),
        bounded=False,
    )
    observability.info(
        "notified the actor of a failure",
        outcome="notified",
        reason=reason,
        actor=actor,
        notified=True,
        link=False,
    )
    return request
