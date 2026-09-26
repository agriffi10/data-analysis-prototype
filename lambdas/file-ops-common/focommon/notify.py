"""Best-effort failure notifications for the file-operations pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps what is file-ops': binding
the plane's own wording into the failure-notification skeleton, and choosing the wording by the
OPERATION the user actually asked for.

That last part is the whole reason this module is not two lines. Every other plane has one verb
and so one prefix; this one serves three, and a user who pressed Delete must not be told that a
copy failed. The operation rides on the verb's event, so the emitters read it from there rather
than being bound at import.

A missed notification must never change or fail the outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.

**No per-message dedup token is passed, and the queue's content-based dedup is load-bearing
rather than incidental.** The rule is one token per OUTCOME, not per verb; each failure here is
emitted from exactly one place, so there is no duplicate-emit pair for a token to collapse —
while the machine's own states carry a ``Retry``, and a re-invocation after a transient Lambda
fault would otherwise send the same message twice. Content dedup is what makes that retry safe.

What content dedup does NOT collapse is two different requests, because the dedup hashes the whole
body and every failure row carries its own request id in the payload. A user refused for the same
protected folder twice in a row sees both refusals; only a request with no usable id, whose row
carries no payload, can still merge with an identical one inside the queue's five-minute window.
"""

import json
import logging
import re
from urllib.parse import quote

from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.notify import (
    actor_of,
    dedup_id,
    emit_notification,
    is_silent,
    request_payload,
)
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from . import config, outcomes
from .messages import failure_message, outcome_summary
from .paths import item_name

logger = logging.getLogger()

__all__ = [
    "emit_failure",
    "emit_notification",
    "emit_outcomes",
    "emit_unexpected",
    "notifies_on_failure",
    "operation_of",
    "outcome_link",
    "outcome_payload",
    "request_payload",
]

#: The file browser's route. The link is a PATH, never a URL — ``isSafeInAppPath`` in the browser
#: rejects anything that could resolve off this origin, and this producer is the first of the two
#: gates.
_FILES_ROUTE = "/files"

#: What a SPACE NAME may contain to be interpolated into a link. Usernames and space names are
#: already constrained to this by the catalog rule, so it refuses nothing the pipeline legitimately
#: produces. A key is not checked against it — keys are arbitrary and are percent-encoded instead.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

#: The outcomes that mean something reached the destination. A ``duplicate`` is here on purpose —
#: its objects DID land, and the destination is where the user has to look to decide which copy to
#: keep.
_LANDED = frozenset({outcomes.MOVED, outcomes.COPIED, outcomes.DUPLICATE})


def operation_of(event) -> object:
    """Returns the operation a request asked for, from wherever on the event it survives.

    Read defensively rather than indexed, because these emitters run on the failure path: an
    event malformed enough to fail validation is exactly the event whose ``operation`` may be
    missing or the wrong type, and the wording resolver falls back on its own for anything it
    does not recognise. Raising here would replace a friendly sentence with an unhandled error
    on the one path whose whole job is reporting a failure.

    The Pipe's raw batch is checked too, because the pre-identity failure path carries the
    original request under ``raw`` and nowhere else.

    Args:
      event: The verb's event, or a recorded failure.

    Returns:
      The operation, or None when it cannot be found.

    Raises:
      None.
    """
    if not isinstance(event, dict):
        return None
    if isinstance(event.get("operation"), str):
        return event["operation"]
    raw = event.get("raw")
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        try:
            body = json.loads(raw[0].get("body") or "{}")
        except Exception:  # noqa: BLE001
            return None
        return body.get("operation") if isinstance(body, dict) else None
    return None


def emit_failure(event, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — which can quote a folder name the actor supplied — is deliberately not
    forwarded into the user's message; it stays on the exception for the logs and the Step
    Functions record. Its TOKENS are the opposite channel and are forwarded, because they exist
    to fill the markers in a body.

    A silent reason sends nothing, and says so in the log. The only one this plane raises is a
    reused request id, refused because a plan under that id names another execution: that run
    reports under the id, and its outcome row is what settles the browser's in-flight card. A
    refusal row carrying the same id would read to that card as "Refused", for an operation that
    may have finished. The price is that a hand-built request reusing an id, which has no such run
    to hear from, is told nothing at all; its refusal is on the execution.

    Args:
      event: The verb's event.
      err: The terminal error being reported.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None. A failure raised before the actor is bound has no addressee, so the emit is a no-op
      rather than a lost message. The request id rides on the payload for the same reason the
      outcome producer's does: a reader tracking this request in flight settles its record by
      matching it, and a run that FAILED settles nothing otherwise — it is held until its own
      expiry instead of answered.

    Raises:
      None.
    """
    if is_silent(err.reason):
        logger.info(
            "not notifying %s for %s", err.reason, observability.request_id_of(event)
        )
        return
    emit_notification(
        actor_of(event),
        failure_message(operation_of(event), err.reason, err.tokens),
        payload=request_payload(event),
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The verb's event.
      step: The verb name, unused here because the notifications queue deduplicates on content.

    Returns:
      None.

    Raises:
      None.
    """
    emit_notification(
        actor_of(event),
        failure_message(operation_of(event), "unexpected_error"),
        payload=request_payload(event),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds this plane's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator. False for
        validate-authorize, which notifies inside its own actor-aware orchestration because the
        actor is not bound until the identity block is read.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def _space_root(space: dict) -> str:
    """Returns a space's root prefix, which is also the only prefix its links may sit under.

    Args:
      space: A ``{kind, name}`` block from the terminal summary.

    Returns:
      ``{name}/``, or an empty string when the name is not one the browser could resolve.

    Raises:
      None.
    """
    name = (space or {}).get("name")
    return f"{name}/" if isinstance(name, str) and _SEGMENT.fullmatch(name) else ""


def _folder_of(key: str) -> str:
    """Returns the folder a key sits in, which is where a link about it should land.

    Args:
      key: An absolute object or folder key.

    Returns:
      Everything up to and including the last slash, or an empty string when there is none.

    Raises:
      None.
    """
    trimmed = key.removesuffix("/")
    cut = trimmed.rfind("/")
    return trimmed[: cut + 1] if cut >= 0 else ""


def _common_folder(keys: list) -> str:
    """Returns the deepest folder every one of these items sits in.

    **The parents, not the items themselves.** The longest common prefix OF THE KEYS is the item
    itself when there is only one of them — which, for a delete, links the user into the folder
    that was just removed: an empty listing where a folder used to be. What they want is where it
    used to sit, and taking the parents first makes the one-item case and the many-item case the
    same computation.

    A common prefix is also truncated back to its last slash, because two siblings named
    ``report-a`` and ``report-b`` share ``report-`` and that names no folder at all.

    Args:
      keys: The request's item keys, all inside one source root — the front door refuses anything
        else, so a two-space delete is unreachable rather than handled.

    Returns:
      The common folder, ending in a slash, or an empty string when there is none.

    Raises:
      None.
    """
    folders = [_folder_of(key) for key in keys if isinstance(key, str) and key]
    if not folders:
        return ""
    shared = folders[0]
    for folder in folders[1:]:
        while not folder.startswith(shared):
            shared = shared[: shared.rfind("/", 0, len(shared) - 1) + 1] if "/" in shared else ""
            if not shared:
                return ""
    return shared


def outcome_link(summary: dict, records: list) -> str | None:
    """Builds the in-app path that lands the actor where the run's result actually is.

    **A copy or move that landed anything links to the DESTINATION; anything else links to the
    SOURCE**, because that is where the items still are. One message per run means one link, so
    the rule is about the run rather than about an item.

    **A delete links to the deepest folder its items shared**, falling back to the space root.
    That rule has to be stated or the producer invents one: a delete carries no destination, and a
    multi-item delete can span folders.

    **The prefix is the FULL KEY, including the space root**, and it is PERCENT-ENCODED. Both
    halves are load-bearing. ``FilesPage`` keeps a ``?prefix=`` only when it starts with the
    resolved space's ``rootPrefix``, so a root-relative prefix is silently discarded and the user
    lands at their space root with no idea why. And unlike the neighbouring planes' links, this
    prefix is an arbitrary user-controlled key rather than a constrained name — an unencoded
    ``?``, ``#`` or ``&`` in it truncates the link into one that resolves somewhere else entirely.

    **``space`` comes FIRST in the query string**, as every plane's link puts it. It is a
    convention rather than a guard: the notification row's feature gate parses the link, so the
    order does not decide whether a shared-space link is gated.

    Args:
      summary: The terminal summary — the operation, both spaces and the destination prefix.
      records: Every item's terminal outcome, which decides whether anything landed.

    Returns:
      The in-app path, or None when no working link can be minted. That is the honest answer: the
      notification still says what happened, it just carries no link.

    Raises:
      None.
    """
    operation = summary.get("operation")
    source, destination = summary.get("source") or {}, summary.get("destination") or {}
    landed = any(r.get("outcome") in _LANDED for r in records)

    if operation in ("copy", "move") and landed:
        space, prefix = destination, destination.get("prefix") or ""
    elif operation == "delete":
        space = source
        prefix = _common_folder([item.get("itemKey") for item in summary.get("items") or []])
    else:
        space, prefix = source, ""

    root = _space_root(space)
    if not root:
        logger.warning("refusing to build an outcome link from an unexpected space name")
        return None
    if not isinstance(prefix, str) or not prefix.startswith(root):
        prefix = root

    encoded = quote(prefix, safe="/")
    if space.get("kind") == "shared":
        return f"{_FILES_ROUTE}?space={space.get('name')}&prefix={encoded}"
    return f"{_FILES_ROUTE}?prefix={encoded}"


def _serialised(payload: dict) -> int:
    """Returns how many bytes a payload occupies in the document the browser downloads.

    Measured on the ENCODED form, because that is what a poll actually costs: JSON escaping turns
    one control character into six bytes, and S3 keys are arbitrary UTF-8.

    Args:
      payload: The payload as built so far.

    Returns:
      Its serialised length in bytes.

    Raises:
      None.
    """
    return len(json.dumps(payload).encode())


def outcome_payload(summary: dict, records: list, request_id: object) -> dict:
    """Builds the structured field a reader needs to ACT on this notification.

    **``requestId`` rides on every payload, including a wholly successful run's.** A reader
    settles its in-flight record by matching it, and a clean run has nothing to re-submit — so
    scoping the field to "what a re-submit needs" would leave successful operations unsettled and
    a per-space gate held until the machine's own ceiling.

    Beyond that it carries what a RE-SUBMIT needs and nothing else: the operation, BOTH spaces
    (the source is not derivable from an absolute key), the destination prefix, and the conflicted
    items with the ``kind`` and ``targetName`` the request contract requires — a rename's target
    name has no other source.

    **The conflicted items are added while they FIT, not while they are few.** One is ~200 bytes
    at ordinary key lengths and ~12,000 at this plane's caps, so a count alone bounds nothing;
    ``more`` says plainly that some were dropped, for either reason.

    **The head is mandatory and rides whatever it costs, so its one unbounded term is capped
    here.** Dropping conflicts cannot help when the head alone is over budget, and nothing
    validates the LENGTH of a destination prefix on the way in — only its containment. Left
    unbounded, a hand-crafted envelope would push this past the writer's ceiling and lose the whole
    message rather than its conflict list.

    Args:
      summary: The terminal summary.
      records: Every item's terminal outcome record.
      request_id: The run's request id.

    Returns:
      The payload. Never empty: the request id alone is worth carrying.

    Raises:
      None.
    """
    source, destination = summary.get("source") or {}, summary.get("destination") or {}
    payload = {"requestId": request_id, "operation": summary.get("operation")}
    payload["source"] = {"kind": source.get("kind"), "name": source.get("name")}
    prefix = destination.get("prefix")
    if prefix and len(prefix.encode()) <= config.FILE_OPS_NOTIFIED_PREFIX_BYTES:
        payload["destination"] = {
            "kind": destination.get("kind"),
            "name": destination.get("name"),
            "prefix": prefix,
        }

    shapes = {
        item.get("itemKey"): item
        for item in (summary.get("items") or [])
        if isinstance(item, dict)
    }
    conflicted = [r for r in records if r.get("outcome") == outcomes.CONFLICT]
    carried: list[dict] = []
    dropped = False
    for record in conflicted:
        if len(carried) >= config.FILE_OPS_NOTIFIED_CONFLICTS:
            dropped = True
            break
        shape = shapes.get(record.get("itemKey")) or {}
        entry = {"itemKey": record.get("itemKey"), "kind": shape.get("kind")}
        if shape.get("targetName"):
            entry["targetName"] = shape["targetName"]
        if record.get("sample"):
            entry["sample"] = record["sample"]
        if record.get("more"):
            entry["more"] = True
        # Probed WITH the ``more`` flag, because it is set below and would otherwise push the
        # emitted payload past the budget the loop just checked it against.
        candidate = {**payload, "conflicts": [*carried, entry], "more": True}
        if _serialised(candidate) > config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES:
            dropped = True
            break
        carried.append(entry)

    if carried:
        payload["conflicts"] = carried
    if dropped or len(carried) < len(conflicted):
        payload["more"] = True
    return payload


def _destination_label(prefix: str) -> str:
    """Returns the destination folder as a person would name it, or nothing.

    Defensive because it runs on the producer path: every emit here is best-effort, and a run
    whose destination prefix lost its shape must still get its message. ``item_name`` raises for
    a key with no final segment, which is why it is called here rather than inline.

    Args:
      prefix: The destination prefix, absolute.

    Returns:
      The folder's own name, or an empty string when there is none to give.

    Raises:
      None.
    """
    if not prefix:
        return ""
    try:
        return item_name(prefix)
    except Exception:  # noqa: BLE001
        return ""


def emit_outcomes(event) -> None:
    """Tells the actor what the whole run did, in one message.

    Args:
      event: The terminal — the outcome list, the summary, the actor and the request id.

    Returns:
      None. Best-effort by construction: by the time this runs a ``move`` has already deleted
      sources, and a raise here would report a completed operation as a failed one.

    Raises:
      None.
    """
    summary = event.get("summary") or {}
    records = [r for r in (event.get("outcomes") or []) if isinstance(r, dict)]
    operation = summary.get("operation")
    destination = (summary.get("destination") or {}).get("prefix") or ""

    message = outcome_summary(
        operation, records, _destination_label(destination), named=config.FILE_OPS_NOTIFIED_ITEMS
    )
    emit_notification(
        actor_of(event),
        message,
        dedup_id=dedup_id(event.get("requestId"), "outcomes"),
        link=outcome_link(summary, records),
        payload=outcome_payload(summary, records, event.get("requestId")),
    )
