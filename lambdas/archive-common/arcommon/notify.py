"""Best-effort outcome notifications for the archive pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the archive specifics: the
actor-addressed failure (SPEC-168), and since SPEC-172 the three outcomes a FAILURE table cannot
carry — an archive that completed, a restore that has started, and a restore that finished.

**Only three, because the other six terminal outcomes are already told by the decorator.**
FR-006 names nine; ``archive_not_found``, ``archive_incomplete``, ``destination_occupied``,
``restore_incomplete``, ``restore_timed_out`` and every other refusal are reason codes in
``messages._BODIES``, emitted once from ``notifies_on_failure`` or from the machine's
``NotifyFailure``. Adding a second producer for them would be the duplicate-notification bug
SPEC-114's one-token-per-outcome rule exists to prevent.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.

**The FAILURE emitters pass no dedup token and rely on the queue's content-based dedup** — the
shape inherited from table-share. Every failure body names its own reason and most name a count
or a file, so two distinct runs rendering byte-identical text is remote, and content dedup is
what makes a verb's ``Retry`` safe.

**The three SUCCESS emitters pass one, and that is SPEC-172 closing a real hole rather than a
stylistic difference.** ``restore_started_message`` says only how many files are being retrieved;
``restored_message`` adds a byte total and a space-root link. Two restores of the same folder
started back to back render **identical** text, and the queue's five-minute window would collapse
them into one inbox row — the user sees a response to one of two requests and cannot tell which.
``cpcommon.notify.dedup_id(requestId, outcome)`` is per RUN and per OUTCOME, so it keeps the
retry-safety content dedup was providing (a re-invocation composes the same token) without
letting two runs share one. This is SPEC-114's rule read literally: one token per outcome.
"""

import logging
import re

from cpcommon.errors import TerminalError
from cpcommon.notify import dedup_id, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import (
    archived_message,
    failure_message,
    restore_started_message,
    restored_message,
)
from .paths import receipt_root

logger = logging.getLogger()

__all__ = [
    "archive_folder_link",
    "emit_archived",
    "emit_failure",
    "emit_notification",
    "emit_restore_started",
    "emit_restored",
    "emit_unexpected",
    "notifies_on_failure",
    "space_link",
]

#: The file browser's route. Every link minted here is a PATH, never a URL — the browser's
#: ``isSafeInAppPath`` rejects anything that could resolve off this origin, and this module is
#: the first of the two gates.
_FILES_ROUTE = "/files"

#: What a space name may contain to be interpolated into a link. Usernames and space names are
#: already constrained to this by the catalog rule, so it rejects nothing this plane legitimately
#: produces — it is here so a future change to either format cannot quietly put a traversal or a
#: query string into a link.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _actor(event) -> str:
    """Reads the verified actor out of a verb's event, tolerating the pre-identity shapes.

    Returns an empty actor rather than raising for anything that is not a request object with a
    username on it. That window is real and is not an error: validate-authorize's event is the
    raw SQS array until the token is verified, and an emit with no addressee is a logged no-op —
    never a message sent to whoever the untrusted body named.

    Args:
      event: The verb's event.

    Returns:
      The verified username, or an empty string.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    actor = data.get("actor")
    if isinstance(actor, dict):
        actor = actor.get("username")
    return actor if isinstance(actor, str) else ""


def _mode(event) -> str:
    """Reads the request's mode out of a verb's event, for the wording.

    Returns an empty string for anything that is not a request object with a mode on it, which
    renders the archive sentence — the same fallback ``failure_message`` documents. That window
    is real: validate-authorize's event is the raw SQS array until the body is parsed.

    Args:
      event: The verb's event.

    Returns:
      The mode, or an empty string.

    Raises:
      None.
    """
    mode = event.get("mode") if isinstance(event, dict) else None
    return mode if isinstance(mode, str) else ""


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a key the actor supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its tokens are the opposite channel and ARE forwarded, because they exist
    to fill the markers in a body.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None. A failure raised before the actor is bound has no addressee, so the emit is a no-op
      rather than a lost message.

    Raises:
      None.
    """
    emit_notification(
        _actor(event), failure_message(err.reason, tokens=err.tokens, mode=_mode(event))
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(_actor(event), failure_message("unexpected_error", mode=_mode(event)))


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds archive's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because the
        actor is not bound until the token is verified.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


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


def _space_query(kind: str, name: str) -> str:
    """Renders the ``?space=`` part of a link, which a PERSONAL space does not carry.

    A shared space needs it or the route resolves the personal space and then DISCARDS a prefix
    that does not start with it — landing the user in their own files with no banner while the
    message tells them where to look. That is the SPEC-167 finding, and it applies unchanged here.

    Args:
      kind: ``personal`` or ``shared``.
      name: The space name.

    Returns:
      ``space={name}&`` for a shared space, or an empty string.

    Raises:
      None.
    """
    return f"space={name}&" if kind == "shared" else ""


def archive_folder_link(kind: str, name: str, request_id: str) -> str | None:
    """Builds the in-app path to the folder holding ONE archive's receipt.

    **The prefix is the FULL KEY, including the space root**, which is the rule this function
    exists to get right: ``FilesPage`` keeps a ``?prefix=`` only when it starts with the resolved
    space's own root, so a root-relative ``archive/{uuid}/`` is silently discarded and the user
    lands at their space root with no idea why — a link that looks like it worked and did not.

    Args:
      kind: The space kind, ``personal`` or ``shared``.
      name: The space's name, which is also its root prefix.
      request_id: The archive's id.

    Returns:
      The in-app path, or None when no working link can be minted. That is the honest answer:
      the notification still says what happened, it just cannot offer a link.

    Raises:
      None.
    """
    if kind not in ("personal", "shared") or not _plain(name) or not _plain(request_id):
        logger.warning("refusing to build an archive link from unexpected segments")
        return None
    try:
        prefix = receipt_root(name, request_id)
    except TerminalError:
        # `_plain` and `validated_request_id` do not agree — the first accepts any plain segment,
        # the second only a UUID v4 — and the gap between them RAISES rather than returning None.
        # Unreachable today (the id is validated at the front door), but this function's contract
        # is "None when no working link can be minted", and the caller's caller would otherwise
        # lose the WHOLE `archived` message to its blanket except: the only one carrying the
        # archive id, on the arm where the source is already deleted.
        logger.warning("refusing to build an archive link from an id that is not a UUID")
        return None
    return f"{_FILES_ROUTE}?{_space_query(kind, name)}prefix={prefix}"


def space_link(kind: str, name: str) -> str | None:
    """Builds the in-app path to a space's own root.

    **The restore's link, and it is the space root rather than a folder ON PURPOSE.** A restore
    puts every object back where it came from, which for any selection of more than one folder is
    several places at once — there is no single restored path to point at, and inventing one by
    picking the first would send the user to a folder that holds part of what they asked for.

    Args:
      kind: The space kind.
      name: The space's name, which is also its root prefix.

    Returns:
      The in-app path, or None when no working link can be minted.

    Raises:
      None.
    """
    if kind not in ("personal", "shared") or not _plain(name):
        logger.warning("refusing to build a space link from unexpected segments")
        return None
    return f"{_FILES_ROUTE}?{_space_query(kind, name)}prefix={name}/"


def emit_archived(actor: str, space: dict, request_id: str, objects: int, total_bytes: int) -> None:
    """Tells the actor their archive finished, and where to find its id.

    Args:
      actor: The verified username.
      space: The source space, carrying its kind and name.
      request_id: The run's id, which is the archive's identity.
      objects: How many objects were archived.
      total_bytes: Their total size.

    Returns:
      None. Best-effort: the archive has already happened, and a missed message must not change
      what did.

    Raises:
      None.
    """
    emit_notification(
        actor,
        archived_message(request_id, objects, total_bytes),
        dedup_id=dedup_id(request_id, "archived"),
        link=archive_folder_link(space.get("kind") or "", space.get("name") or "", request_id),
    )


def emit_restore_started(actor: str, request_id: str, objects: int) -> None:
    """Tells the actor a restore is under way and will take hours.

    No link: nothing has arrived yet, and a link to a space that has not changed would suggest
    there is something to look at.

    Args:
      actor: The verified username.
      request_id: This RUN's id — the dedup token's discriminator, and the reason this message
        needs one: its text names a count and nothing else, so two restores started together
        would otherwise collapse into one inbox row.
      objects: How many objects are being retrieved.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(
        actor,
        restore_started_message(objects),
        dedup_id=dedup_id(request_id, "restore_started"),
    )


def emit_restored(
    actor: str,
    space: dict,
    request_id: str,
    objects: int,
    total_bytes: int,
    *,
    archive_swept: bool = True,
) -> None:
    """Tells the actor their restore finished, and links to the space it landed in.

    Args:
      actor: The verified username.
      space: The destination space, carrying its kind and name.
      request_id: This RUN's id, for the dedup token.
      objects: How many objects were restored.
      total_bytes: Their total size.
      archive_swept: Whether the vault copy was actually removed. False on the route through
        ``CleanupIncomplete``, where the run succeeded and the sweep did not.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(
        actor,
        restored_message(objects, total_bytes, archive_swept=archive_swept),
        dedup_id=dedup_id(request_id, "restored"),
        link=space_link(space.get("kind") or "", space.get("name") or ""),
    )
