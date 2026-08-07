"""Best-effort notification primitives shared by every control plane.

Only two pieces are genuinely shared. The domain emitters — ``emit_failure``,
``emit_unexpected``, the per-arc success emitters and event-context extraction — stay in
each domain layer, because their signatures and dedup strategies differ.
"""

import functools
import json
import logging

from . import clients, config
from .errors import TerminalError, TransientError

logger = logging.getLogger()


def emit_notification(
    username: str, message: str, dedup_id: str | None = None, link: str | None = None
) -> None:
    """Sends a create envelope to the FIFO notifications queue, grouped by username.

    A missed notification must never change or fail a pipeline outcome, which the Step
    Function execution has already recorded — so every error is caught and logged.

    Args:
      username: Recipient, also the FIFO message group. No recipient is a logged no-op.
      message: The rendered notification body.
      dedup_id: Optional FIFO deduplication token. Table-builder passes
        ``{requestId}:{step}``; table-share relies on the queue's content-based dedup and
        passes nothing.
      link: Optional in-app path the notification deep-links to. Omitted from the body
        rather than sent as null, because the writer treats any non-empty string as a link
        to persist and an absent key is unambiguous in a way a null is not. Not validated
        here: the browser decides what is safe to render as a link, and duplicating that
        rule in a Lambda would give two places to keep in step. Producers pass in-app paths
        only, never an absolute URL.

    Returns:
      None. Also returns without sending when the queue URL is unset.

    Raises:
      None. Every failure is logged and swallowed.
    """
    if not config.NOTIFICATIONS_QUEUE_URL:
        logger.info("notifications queue unset; skipping notify for %s", username)
        return
    if not username:
        logger.info("no recipient; skipping notify")
        return
    try:
        body = {"action": "create", "username": username, "message": message}
        if link:
            body["link"] = link
        kwargs = {
            "QueueUrl": config.NOTIFICATIONS_QUEUE_URL,
            "MessageBody": json.dumps(body),
            "MessageGroupId": username,
        }
        if dedup_id:
            kwargs["MessageDeduplicationId"] = dedup_id
        clients.sqs().send_message(**kwargs)
    except Exception:
        logger.exception("emit_notification failed for %s", username)


def notifies_on_failure(step: str, emit_unexpected, emit_terminal=None):
    """Builds a decorator that notifies the actor of a verb failure before it propagates.

    The skeleton takes the domain's emitters as explicit seams, so a domain calls this from
    its own thin ``notifies_on_failure(step)`` and verb handlers keep decorating with the
    domain helper. A ``TransientError`` always passes through un-notified: the SFN Retry
    re-runs it, so notifying now would be premature. Emits are best-effort — each domain
    emitter catches and logs — and the exception always re-raises for the Catch.

    Args:
      step: The verb name carried into the notification.
      emit_unexpected: The domain's generic-failure emitter, called as
        ``emit_unexpected(event, step)`` for an exception the handler did not anticipate —
        an AccessDenied, a bug, a bad response. This is what closes the silent-failure gap.
      emit_terminal: The domain's TerminalError emitter, called as
        ``emit_terminal(event, err, step)``. When supplied, a TerminalError is notified here
        before re-raising, so handlers need no ``try/except TerminalError`` of their own.
        When None, a TerminalError passes through un-notified — for a verb that owns its own
        actor-aware notification, such as a validate-authorize that notifies only once the
        actor is bound.

    Returns:
      A decorator for a verb handler.

    Raises:
      None. The returned wrapper re-raises whatever the handler raised.
    """

    def decorate(handler):
        """Wraps one verb handler.

        Args:
          handler: The verb handler to wrap.

        Returns:
          The wrapped handler.

        Raises:
          None.
        """

        @functools.wraps(handler)
        def wrapper(event, context):
            """Runs the handler, notifying on the failures this decorator owns.

            Args:
              event: The verb's event.
              context: The Lambda context.

            Returns:
              Whatever the handler returned.

            Raises:
              Exception: Whatever the handler raised, always re-raised for the SFN Catch.
            """
            try:
                return handler(event, context)
            except TransientError:
                raise
            except TerminalError as err:
                if emit_terminal is not None:
                    emit_terminal(event, err, step)
                raise
            except Exception:
                logger.exception("unexpected failure in %s step", step)
                emit_unexpected(event, step)
                raise

        return wrapper

    return decorate
