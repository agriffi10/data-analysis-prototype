"""notify — the plane's only success producer, and the last state before ``Succeeded``.

One message per request: what was saved, in what format, how many rows, and a link to the folder
it landed in. Every other verb on this plane emits only failures, precisely so that one place
says the good outcome once.

**NOTHING HERE CAN FAIL THE RUN.** By the time this state runs the object is already in the
user's space; a raise would turn a completed conversion into a failed execution and tell the
user their save did not happen when it did. That is why the state carries ``ResultPath: null``
with a ``Catch`` leading onward, why this verb has no ``@notifies_on_failure`` — that decorator
would report a failure of the notifier as a failure of the conversion — and why the emit is
wrapped even though ``emit_notification`` already swallows: composing the sentence and minting
the link do not.

**It only ever runs on a converted outcome.** A refusal is routed away by the machine's Choice
and reaches the user through ``NotifyFailure``, so this verb never has to decide whether an
outcome was good — a decision it would make from the same field the Choice reads, in a second
place.

**The recipient is ``username`` on the state**, never a nested ``actor``: this plane carries the
verified username flat, and ``cpcommon.notify.actor_of`` would address nobody.

Attributes:
  None.
"""

import logging

from cpcommon import observability
from rccommon import links, messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)
observability.init(service="results-conversion")


@observability.traced("notify")
def handler(event, context) -> dict:
    """Step Functions entry point: tells the actor their results were saved.

    ``@traced`` is the only decorator, for the reason in the module docstring.

    Args:
      event: The converted request object.
      context: The Lambda context, unused.

    Returns:
      The event, threaded onward unchanged, so the execution's output stays what the machine
      shaped rather than whatever this verb happened to return.

    Raises:
      None.
    """
    return _notify(event)


def _notify(event) -> dict:
    """Emits the run's one success message, and never raises doing it.

    Args:
      event: The converted request object.

    Returns:
      The event, unchanged.

    Raises:
      None.
    """
    state = event if isinstance(event, dict) else {}
    username = notify.username_of(state)
    destination = state.get("destination") or {}
    key = str(destination.get("key") or "")
    filename = key.rsplit("/", 1)[-1]
    try:
        message = messages.success_message(
            filename,
            str(state.get("format") or ""),
            int(state.get("rows") or 0),
            bool(state.get("precisionNote")),
        )
        link = links.destination_link(
            str(destination.get("spaceKind") or ""), str(destination.get("spaceName") or ""), key
        )
        notify.emit_notification(
            username, message, link=link, payload=notify.request_payload(state)
        )
    except Exception:
        logger.exception("could not notify the conversion outcome; the run itself is unaffected")
        return state
    logger.info("notified %s that %s was saved", username, filename)
    observability.info(
        "conversion notified",
        actor=username,
        format=state.get("format"),
        rows=state.get("rows"),
        linked=link is not None,
        notified=bool(username),
    )
    return state
