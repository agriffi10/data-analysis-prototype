"""Best-effort notification primitives shared by every control plane.

Four pieces are genuinely shared: the sender, the failure-notification skeleton, the
*shape* of the FIFO deduplication token, and ``is_silent``, the test for a reason nobody is
told. The domain emitters — ``emit_failure``, ``emit_unexpected`` and the per-arc success
emitters — stay in each domain layer, because their signatures differ. So do the dedup **strategies**: ``dedup_id`` composes an id, it does
not decide what goes in one, and the four planes make four different choices (see its
docstring). A plane relying on the queue's content-based dedup simply does not call it.

Event-context extraction is domain work too, with **one narrow exception**: ``actor_of`` reads
the flat ``actor`` envelope file-send introduced and archive inherited, where the
field may be either the verified username or the token object it was verified from. The other
four planes bind a plain string and read it directly, so this is a two-plane contract living
here rather than a fleet-wide one.
"""

import functools
import hashlib
import json
import logging

from . import clients, config
from .errors import TerminalError, TransientError
from .events import in_vocabulary
from .messages import SILENT_REASONS

logger = logging.getLogger()


def dedup_id(request_id, step: str) -> str | None:
    """Composes the FIFO deduplication id from a request id and a step token.

    The shape only. **What a caller passes as ``step`` is the plane's own decision, and the
    planes deliberately disagree** — this function must not be read as endorsing one.

    data-quality passes one token per *outcome* (``failure``/``completed``), which is
    load-bearing there: two code paths emit the same failure — the verb decorator on its way
    out, and the notify state after the Catch — and that state cannot know which verb raised,
    so a per-verb token would give the two emits different ids and the user would get two
    notifications for one failure. shared-spaces reproduces its verbs' own tokens for the same
    reason. table-builder passes the **verb name** from its decorator and ``failure`` from its
    notify-failure verb, on purpose: that plane suppresses the duplicate by identifying the
    verb's error instead, and unifying the tokens would change notification behaviour on paths
    that already work (see ``tb_notify_failure``'s module docstring). table-share passes
    nothing at all and relies on the queue's content-based dedup.

    Where a plane does collapse a pair this way, the collapse depends on the queue's
    deduplication window: the two emits land seconds apart, comfortably inside it. A future
    change that put minutes between them — a long wait on the failure path, a retry storm in
    cleanup — would let the window expire and the user would get both.

    Args:
      request_id: The run's request id.
      step: The caller's step or outcome token.

    Returns:
      ``{requestId}:{step}``, or None without a request id, which falls back to the queue's
      content-based dedup. None rather than an invented id, which would defeat that fallback
      rather than replace it. Unbounded: a request id may already be 128 characters, and
      ``emit_notification`` is what holds the result to a key the queue accepts.

    Raises:
      None.
    """
    return f"{request_id}:{step}" if request_id else None


def _queue_key(dedup_id: str) -> str:
    """Returns a deduplication id the notifications queue accepts, digesting one it would refuse.

    A producer composes its id from a caller's request id, which the API admits at up to 128
    characters on its own, so anything added to it — a step token, a username, the DLQ drain's
    prefix — can carry it past the queue's limit. SQS then refuses the send, the sender logs and
    swallows the refusal, and that caller's notification is lost.

    A digest, never None: None hands the send to the queue's content-based deduplication, which
    collapses only byte-identical bodies, so two emits a plane keys alike on purpose would
    collapse only if they also happened to be worded alike. The same key always digests to the
    same value, so every collapse a caller chose still happens. A key the queue accepts is sent
    as it is.

    Args:
      dedup_id: The id a producer composed.

    Returns:
      The id unchanged when ``config.FIFO_KEY_RE`` matches it whole, else the SHA-256 of its UTF-8
      bytes in lower-case hex. ``surrogatepass`` lets a lone surrogate, which a JSON body can
      decode to, digest rather than raise.

    Raises:
      None.
    """
    if config.FIFO_KEY_RE.fullmatch(dedup_id):
        return dedup_id
    return hashlib.sha256(dedup_id.encode("utf-8", "surrogatepass")).hexdigest()


def actor_of(event) -> str:
    """Reads the verified actor out of a verb's event, tolerating the pre-identity shapes.

    Returns an empty actor rather than raising for anything that is not a request object with a
    username on it. That window is real and is not an error: validate-authorize's event is the
    raw SQS array until the identity block is read, and an emit with no addressee is a logged no-op —
    never a message sent to whoever the untrusted body named.

    Args:
      event: The verb's event, of any shape.

    Returns:
      The verified username, or an empty string when the event carries none.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    actor = data.get("actor")
    if isinstance(actor, dict):
        actor = actor.get("username")
    return actor if isinstance(actor, str) else ""


def emit_notification(
    username: str,
    message: str,
    dedup_id: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
) -> None:
    """Sends a create envelope to the FIFO notifications queue, grouped by username.

    A missed notification must never change or fail a pipeline outcome, which the Step
    Function execution has already recorded — so every error is caught and logged.

    Args:
      username: Recipient, also the FIFO message group. No recipient is a logged no-op.
      message: The rendered notification body.
      dedup_id: Optional FIFO deduplication token, built by this module's ``dedup_id`` —
        which is a different thing with the same name, and does not read this parameter.
        A producer that passes none relies on the queue's content-based dedup. One the
        queue would refuse is sent as its
        digest (``_queue_key``), so a long request id costs the key its readability rather
        than the user their notification.
      link: Optional in-app path the notification deep-links to. Omitted from the body
        rather than sent as null, because the writer treats any non-empty string as a link
        to persist and an absent key is unambiguous in a way a null is not. Not validated
        here: the browser decides what is safe to render as a link, and duplicating that
        rule in a Lambda would give two places to keep in step. Producers pass in-app paths
        only, never an absolute URL.
      payload: Optional structured object the row carries beside its message, for a reader
        that knows the producing plane's shape. Omitted from the body rather than sent as
        null, for the same reason as the link: the writer treats a present non-empty object
        as one to persist, and an absent key is unambiguous where a null is not. **A plane
        that passes one owns its own size bound** — the writer enforces a ceiling and refuses
        anything over it, which dead-letters the message rather than delivering half a field.

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
        body: dict = {"action": "create", "username": username, "message": message}
        if link:
            body["link"] = link
        if payload:
            body["payload"] = payload
        kwargs = {
            "QueueUrl": config.NOTIFICATIONS_QUEUE_URL,
            "MessageBody": json.dumps(body),
            "MessageGroupId": username,
        }
        if dedup_id:
            kwargs["MessageDeduplicationId"] = _queue_key(dedup_id)
        clients.sqs().send_message(**kwargs)
    except Exception:
        logger.exception("emit_notification failed for %s", username)


def is_silent(reason: object) -> bool:
    """Reports whether a terminal reason ends the run without a notification.

    The one predicate a domain's ``emit_failure`` reads before it sends, so no plane keeps its
    own list of which refusals stay quiet. It sits in the emitter rather than in
    ``notifies_on_failure``, because a validator calls its plane's ``emit_failure`` directly and
    would otherwise tell a silent reason the decorator keeps quiet.

    Args:
      reason: The terminal reason code, of any type.

    Returns:
      True when the reason is one of ``messages.SILENT_REASONS``.

    Raises:
      None.
    """
    return in_vocabulary(reason, SILENT_REASONS)


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
        ``emit_terminal(event, err, step)``. When supplied, a TerminalError is handed to it
        before re-raising, so handlers need no ``try/except TerminalError`` of their own; the
        emitter sends nothing for a reason ``is_silent`` names.
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
