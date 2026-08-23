"""notify — the plane's only outcome producer, and the last state before ``Succeeded``.

It turns the terminal the finaliser shaped into ONE message: what the operation did, what it could
not do, a link to where the result actually is, and the structured field a reader needs to act on a
refusal. Every other verb on this plane emits nothing about an ITEM — the guard returns its
refusals as records and the collector and the deletion say nothing at all — precisely so that one
place can say each outcome once. The whole-REQUEST verbs still notify from their decorators: a
request that dies in validate-authorize never reaches this state.

**IT RUNS AFTER THE LOCK IS RELEASED, AND BOTH OF ``ReleaseLock``'s EDGES REACH IT.** Before the
release it would hold a space for as long as the messages take to write. And a release that
exhausts its own ``Retry`` still has to arrive here, or an operation that COMPLETED tells the user
nothing — while a reader waiting on this message to settle its record holds that space's gate until
the machine's ceiling.

**NOTHING HERE CAN FAIL THE RUN.** By the time it runs, a ``move`` has already deleted sources: the
data has moved and the execution is otherwise successful, so a raise would replace a completed
operation with a failed one. That is why the state carries ``ResultPath: null`` and a ``Catch``
leading onward, and why this verb has no ``@notifies_on_failure`` — that decorator would report a
failure of the notifier as a failure of the operation.

**IT READS THE STATE AND NOTHING ELSE.** The terminal already carries the outcome list, the
operation, both spaces, the destination prefix and every item's shape, so there is no second
source to consult — and reaching for the plan would put this verb in the set whose MEMORY sizes
``FILE_OPS_MAX_OBJECTS``, silently shrinking a cap that has nothing to do with notifying.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from focommon import notify, outcomes

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")


@observability.traced("notify")
def handler(event, context) -> dict:
    """Step Functions entry point: tells the actor what the run did.

    ``@traced`` is the only decorator, for the reason in the module docstring.

    Args:
      event: The terminal — the finalised outcome list, the summary, the actor and the request id.
      context: The Lambda context, unused.

    Returns:
      The terminal, threaded onward unchanged, so the execution's output is still what the machine
      shaped rather than whatever this verb happened to return.

    Raises:
      None.
    """
    return _notify(event)


def _notify(event) -> dict:
    """Emits the run's one message, and never raises doing it.

    A terminal with no outcomes at all is a logged no-op rather than an error: it is not reachable
    through the finaliser, which returns a record per selected item, and inventing a failure here
    would report a completed operation as a broken one.

    **The emit is wrapped even though ``emit_notification`` already swallows.** Composing the
    sentence, minting the link and building the payload do not — and an unanticipated raise in any
    of them would lose the message while the execution still succeeded through the state's Catch:
    nothing notified, and nothing recorded either.

    Args:
      event: The terminal.

    Returns:
      The terminal, unchanged.

    Raises:
      None.
    """
    terminal = event if isinstance(event, dict) else {}
    records = [r for r in (terminal.get("outcomes") or []) if isinstance(r, dict)]
    operation = (terminal.get("summary") or {}).get("operation")

    if not records:
        logger.info("nothing to notify for %s: the terminal carries no outcomes", operation)
        observability.warning(
            "no outcome to notify",
            outcome="no-items",
            actor=notify.actor_of(terminal),
            operation=operation,
            notified=False,
        )
        return terminal

    try:
        notify.emit_outcomes(terminal)
    except Exception:
        logger.exception("could not notify the outcome of %s; the run itself is unaffected", operation)
        return terminal

    tally = {}
    for record in records:
        tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
    logger.info("notified the actor of %d item outcome(s) for %s: %s", len(records), operation, tally)
    observability.info(
        "outcomes notified",
        actor=notify.actor_of(terminal),
        operation=operation,
        items=len(records),
        conflicts=tally.get(outcomes.CONFLICT, 0),
        notified=True,
    )
    return terminal
