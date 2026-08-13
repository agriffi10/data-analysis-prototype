"""Best-effort outcome notifications for the file-send pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the file-send specifics:
the sender-addressed failure (SPEC-164), and since SPEC-167 the per-recipient outcomes, the
recipient's own message and the link that takes them to what arrived.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises. That is the whole
contract of this plane's producer: the copy has already happened by the time it runs, and a
message is the only thing it can add.

**No per-message dedup token is passed, and the queue's content-based dedup is load-bearing
rather than incidental.** SPEC-114's rule is one token per OUTCOME, not per verb; here every
outcome is emitted from exactly one place, so there is no duplicate-emit pair for a token to
collapse — while the producer's own state carries a ``Retry``, and a re-invocation after a
transient Lambda fault would otherwise send every message twice. Content dedup is what makes that
retry safe.

The cost is a real one and worth knowing: two sends that render a byte-identical sentence inside
the queue's five-minute window collapse to one message. The reachable case is a sender who is
refused a ``conflict``, asks the recipient to move what is there, and re-sends immediately — the
second refusal reads identically and is dropped, so she sees no response to her second attempt.
Inherited from table-share rather than introduced here.

Attributes:
  _FILES_ROUTE: The file browser's route. The link is a PATH, never a URL — the browser's
    ``isSafeInAppPath`` rejects anything that could resolve off this origin, and this producer
    is the first of the two gates.
  _SEGMENT: What a name may contain to be interpolated into a link. Usernames and space names
    are already constrained to this by the catalog rule, so it rejects nothing the pipeline
    legitimately produces — it is here so a future change to either format cannot quietly put a
    traversal or a query string into a link.
"""

import logging
import re

from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from cpcommon.notify import actor_of, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import (
    failure_message,
    recipient_message,
    space_owner_message,
    success_message,
)
from .paths import inbox_prefix

logger = logging.getLogger()

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_recipient_outcome",
    "emit_unexpected",
    "notifies_on_failure",
    "received_files_link",
]

_FILES_ROUTE = "/files"

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def received_files_link(kind: str, name: str, sender: str) -> str | None:
    """Builds the in-app path that lands a recipient in the folder holding what arrived.

    **The prefix is the FULL KEY, including the recipient's own space root**, and that is the
    rule this function exists to get right. ``FilesPage`` keeps a ``?prefix=`` only when it
    starts with the resolved space's ``rootPrefix``, so a root-relative
    ``shared_files/{sender}/`` is silently discarded and the recipient lands at their space root
    with no idea why — a link that looks like it worked and did not. A ``space`` recipient also
    needs ``?space=``, or the browser resolves the personal space and discards the prefix for
    the same reason.

    It mirrors ``dqcommon.notify.report_link``, including its refusal to mint anything from a
    value it does not recognise. ``isSafeInAppPath`` is browser TypeScript and cannot run at
    mint time; the browser re-checks what arrives, and this is the producer half.

    Args:
      kind: ``user`` or ``space``.
      name: The recipient's name, which is also their space root.
      sender: The verified sender's username, which namespaces the inbox.

    Returns:
      The in-app path, or None when no working link can be minted. That is the honest answer:
      the notification still says what arrived, it just cannot offer a link.

    Raises:
      None.
    """
    if kind not in ("user", "space") or not _plain(name) or not _plain(sender):
        logger.warning("refusing to build a received-files link from unexpected segments")
        return None
    prefix = inbox_prefix(name, sender)
    if kind == "user":
        return f"{_FILES_ROUTE}?prefix={prefix}"
    return f"{_FILES_ROUTE}?space={name}&prefix={prefix}"


def _plain(value) -> bool:
    """Reports whether a value is a single path segment with nothing that could change a URL.

    Args:
      value: The candidate segment.

    Returns:
      True when it is a non-empty string of alphanumerics, hyphens and underscores.

    Raises:
      None.
    """
    return isinstance(value, str) and bool(_SEGMENT.match(value))


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the sender-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a key the sender supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its tokens are the opposite channel and ARE forwarded, because they
    exist to fill the markers in a body.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None. A failure raised before the actor is bound has no addressee, so the emit is a
      no-op rather than a lost message.

    Raises:
      None.
    """
    emit_notification(actor_of(event), failure_message(err.reason, tokens=err.tokens))


def emit_unexpected(event, step: str) -> None:
    """Emits the sender-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(actor_of(event), failure_message("unexpected_error"))


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds file-send's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because
        the sender is not bound until the token is verified.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def emit_recipient_outcome(sender: str, outcome: dict, item_names, object_count: int) -> None:
    """Tells everyone who should hear about ONE recipient's outcome, and nobody who should not.

    **The sender hears about every outcome; the recipient hears only about a success.** A
    recipient who was never reached is not told that somebody tried and failed — that would leak
    a send they have no part in, and there is nothing they could do about it. A ``space``
    recipient is announced to its registered OWNER only, never its membership, matching table
    share.

    The link is the recipient's, not the sender's: it points into the recipient's own space, so
    it is minted per message rather than once per outcome.

    Args:
      sender: The verified sender's username.
      outcome: One entry from the terminal summary — kind, name, status, reason, detail.
      item_names: The selected item names, for the wording.
      object_count: How many objects the send held.

    Returns:
      None. Every emit is best-effort: the copy has already happened, and a missed message must
      not change what did.

    Raises:
      None. An owner lookup that fails is logged and skipped, leaving the sender's own message
      untouched — the two are independent, and the sender's is the one that always applies.
    """
    kind, name = outcome.get("kind") or "", outcome.get("name") or ""

    if outcome.get("status") != "ok":
        emit_notification(
            sender,
            failure_message(
                outcome.get("reason") or "unexpected_error",
                kind=kind,
                name=name,
                tokens={"itemName": outcome.get("detail") or ""},
            ),
        )
        return

    emit_notification(sender, success_message(kind, name, item_names, object_count))
    link = received_files_link(kind, name, sender)

    if kind == "user":
        emit_notification(name, recipient_message(sender, item_names, object_count), link=link)
        return

    try:
        owner = (reg.load(name) or {}).get("owner") or ""
    except Exception:
        logger.exception("owner lookup failed for space %s; skipping the owner notification", name)
        return
    if not owner:
        logger.info("space %s has no resolvable owner; skipping the owner notification", name)
        return
    emit_notification(owner, space_owner_message(sender, name, item_names, object_count), link=link)
