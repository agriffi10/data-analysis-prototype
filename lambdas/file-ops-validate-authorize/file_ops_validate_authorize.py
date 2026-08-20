"""validate-authorize — the file-operations Step Function's first task.

Parses the SQS record, verifies the caller's Cognito ID token into the trusted actor, authorizes
BOTH the source and the destination, confirms every selected item sits inside its root, refuses
the portal's own folders per (side x operation), and emits the per-item outcome list every later
verb carries forward. Read-only: nothing is listed, planned, copied or deleted here.

**TWO AUTHORIZATION QUESTIONS, WHICH IS WHAT MAKES THIS VERB DIFFERENT FROM ITS NEIGHBOURS.** The
other planes ask only whether the actor may read what they named; a recipient there is a lookup,
because the execution role does the write. Here the destination is a place the actor chose inside
a space they claim, so it is authorized independently and by the same rules — without that, an
actor could write into a space they may read nothing of.

**A WHOLE-REQUEST failure raises; a PER-ITEM refusal returns a record.** The split is not
stylistic. A containment breach, a dot segment or two selected items whose destinations collide
are statements about the REQUEST — there is no sensible partial execution of a request that names
a key outside the actor's own space. A protected folder, an item copied into itself and a same-key
no-op are statements about ONE item, and the browser has always carried on with the rest: a
select-all delete at a space root deletes what it may and reports the folders it may not, and
turning that into a whole-request refusal would delete nothing.

**THE COPY/MOVE-ONLY FIELDS ARE NORMALISED TO NULL FOR A DELETE.** They are rejected on the way in
and emitted as explicit nulls on the way out, so no downstream state has to ask whether they are
there. That is a positive property of this verb rather than something the machine leans on — the
state machine deliberately does not read them at all — but it keeps the state one shape for all
three operations, which is what a later verb's `Choice` will want.

Attributes:
  _ALLOWED_FIELDS: The complete set of top-level request fields. Unknown fields are REJECTED
    rather than ignored: a field the producer thinks it is sending and this verb silently drops
    is a contract break that shows up as behaviour nobody asked for, and the cheapest moment to
    catch a renamed field is the first one.
  _COPY_MOVE_FIELDS: The three fields that are required for a copy or a move and rejected for a
    delete. Rejected rather than ignored for the same reason, and because a delete carrying an
    `onConflict` is a request whose author believed something false about what it would do.
  _ITEM_KINDS: The two selection kinds a request may carry. A folder key is normalised to a
    trailing slash before any rule runs.
"""

import json
import logging
from datetime import UTC, datetime

from cpcommon import auth, events, observability
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment, normalize_root
from focommon import authz, notify, outcomes, paths, protected
from focommon.config import (
    FILE_OPS_MAX_ITEMS,
    FILE_OPS_MAX_SELECTION_BYTES,
    ON_CONFLICT,
    OPERATIONS,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_ALLOWED_FIELDS = frozenset(
    {"requestId", "actor", "operation", "source", "destination", "onConflict", "submittedAt"}
)

_COPY_MOVE_FIELDS = ("destination", "onConflict", "submittedAt")

_ITEM_KINDS = frozenset({"file", "folder"})


def _check_contract(req) -> str:
    """Fails the request if its top-level shape is not the one this contract defines.

    Both directions, because only one of them is obvious. Unknown fields are REJECTED rather than
    ignored, and the required fields are type-checked, which the rejection does not imply: an
    absent ``requestId`` would flow through as None and a non-string one would flow through whole.

    Args:
      req: The parsed request body.

    Returns:
      The validated operation.

    Raises:
      TerminalError: ``malformed_event`` when the body is not an object, names a field outside
        the contract, or carries no usable request id; ``invalid_operation`` for an operation
        this plane does not serve.
    """
    if not isinstance(req, dict):
        raise TerminalError(events.MALFORMED, "request body is not an object")
    unknown = sorted(set(req) - _ALLOWED_FIELDS)
    if unknown:
        raise TerminalError(events.MALFORMED, f"unknown request fields: {', '.join(unknown)}")
    request_id = req.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, "requestId missing or not a string")

    operation = req.get("operation")
    if operation not in OPERATIONS:
        raise TerminalError("invalid_operation", f"unknown operation {operation!r}")
    return operation


def _check_conflict_fields(req: dict, operation: str) -> None:
    """Confirms the copy/move-only fields are present for a copy or move and absent for a delete.

    **The wrong shape for the operation is a refusal, not a coerced default.** A delete carrying
    an ``onConflict`` is a request whose author believed it would do something it cannot, and
    silently dropping the field would leave that belief intact. A copy missing one is worse: the
    conflict answer and the submission time are what bound an overwrite, so defaulting either
    would decide on the user's behalf what happens to a file they never saw.

    Args:
      req: The parsed request body.
      operation: The validated operation.

    Returns:
      None.

    Raises:
      TerminalError: ``unexpected_destination`` when a delete carries any of them,
        ``invalid_destination`` for a missing or malformed destination, ``invalid_conflict`` for
        a missing or unrecognised conflict answer, and ``invalid_submitted_at`` for a submission
        time that is missing, unparseable or in the future.
    """
    if operation == "delete":
        present = [field for field in _COPY_MOVE_FIELDS if field in req]
        if present:
            raise TerminalError(
                "unexpected_destination", f"a delete carries {', '.join(present)}"
            )
        return

    destination = req.get("destination")
    if not isinstance(destination, dict) or not isinstance(destination.get("prefix"), str):
        raise TerminalError("invalid_destination", "destination missing or malformed")

    if req.get("onConflict") not in ON_CONFLICT:
        raise TerminalError("invalid_conflict", f"unknown conflict answer {req.get('onConflict')!r}")

    _check_submitted_at(req.get("submittedAt"))


def _check_submitted_at(value) -> None:
    """Confirms the submission time is a real instant that has already happened.

    **A future timestamp would make every collision overwritable**, because the plane only
    overwrites an object whose last modification precedes it. That is the one field on this
    envelope a caller could set to defeat a safety rule rather than merely to malform a request.

    Args:
      value: The request's submission time.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_submitted_at`` when it is missing, unparseable, naive, or ahead
        of now.
    """
    if not isinstance(value, str) or not value:
        raise TerminalError("invalid_submitted_at", "submittedAt missing")
    try:
        submitted = datetime.fromisoformat(value)
    except ValueError as err:
        raise TerminalError("invalid_submitted_at", f"{value!r} is not an instant") from err
    if submitted.tzinfo is None:
        raise TerminalError("invalid_submitted_at", f"{value!r} names no time zone")
    if submitted > datetime.now(UTC):
        raise TerminalError("invalid_submitted_at", f"{value!r} is in the future")


def _normalize_items(items, root: str) -> list:
    """Shape-checks the selection and confirms every key is one the actor may reach.

    The caps are checked on the RAW list, before the per-item loop: the loop is work proportional
    to caller-supplied input, and rejecting after doing it would defeat the point of having a cap.
    The byte cap bounds a different quantity from the count — the count bounds the per-item work,
    this bounds what rides on the state and reaches the Pipe.

    Containment is a WHOLE-REQUEST terminal rather than a per-item skip: a request naming a key
    outside the actor's own space is not a request with one bad row in it.

    Args:
      items: The raw selection from the request.
      root: The authorized source root prefix.

    Returns:
      The normalised selection.

    Raises:
      TerminalError: ``no_items`` when the list is missing or empty, ``invalid_items`` for a
        non-list, a non-object entry, an unknown kind or a missing key, ``too_many_items`` and
        ``selection_too_large`` for the caps, and ``forbidden`` when a key is not inside the root
        or carries a dot segment.
    """
    if items is None:
        raise TerminalError("no_items", "items missing")
    if not isinstance(items, list):
        raise TerminalError("invalid_items", "items must be a list")
    if not items:
        raise TerminalError("no_items", "items is empty")
    if len(items) > FILE_OPS_MAX_ITEMS:
        raise TerminalError("too_many_items", f"{len(items)} items, over {FILE_OPS_MAX_ITEMS}")

    normalized = []
    for entry in items:
        if not isinstance(entry, dict):
            raise TerminalError("invalid_items", "each item must be an object")
        kind = entry.get("kind")
        if kind not in _ITEM_KINDS:
            raise TerminalError("invalid_items", f"unknown item kind {kind!r}")
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            raise TerminalError("invalid_items", "item key missing")
        if kind == "folder" and not key.endswith("/"):
            key = f"{key}/"
        assert_inside_root(root, key)
        item = {"kind": kind, "key": key}
        if entry.get("targetName") is not None:
            item["targetName"] = paths.validate_target_name(entry["targetName"])
        normalized.append(item)

    serialized = len(json.dumps(normalized, separators=(",", ":")).encode())
    if serialized > FILE_OPS_MAX_SELECTION_BYTES:
        raise TerminalError(
            "selection_too_large", f"{serialized} bytes of keys, over {FILE_OPS_MAX_SELECTION_BYTES}"
        )
    return normalized


def _check_destination_prefix(root: str, prefix: str) -> str:
    """Confirms the destination prefix sits inside the destination space's own root.

    **Authorizing the SPACE is not the whole question.** Without this nothing constrains the
    prefix within it, so a request naming a shared space the actor genuinely belongs to, with
    another member's prefix, would be a privileged cross-tenant write — the plane's own role doing
    what the browser's credentials never could.

    Args:
      root: The authorized destination root prefix.
      prefix: The destination folder key from the request.

    Returns:
      The prefix, normalised to a trailing slash.

    Raises:
      TerminalError: ``forbidden`` when the prefix is outside the root or carries a dot segment.
    """
    normalized = prefix if prefix.endswith("/") else f"{prefix}/"
    assert_inside_root(root, normalized)
    if has_dot_segment(normalized):
        raise TerminalError("forbidden", f"{prefix!r} carries a dot segment")
    return normalized


def _assert_no_derived_collision(items: list, destination_prefix: str) -> None:
    """Refuses a selection in which two items would land on the same key.

    A WHOLE-REQUEST refusal rather than a per-item one, and the asymmetry with the protected-
    folder rules is the point: neither of the two colliding items is the wrong one, so there is no
    item to fail and no way to choose.

    **A collision is between two DIFFERENT items, and an exact repeat is not one.** The identity
    is ``(kind, key)``, not the derived key alone: the same item named twice lands on itself, which
    is idempotent, while two different items landing on one key lose a file. Collapsing on the
    derived key alone would refuse a request that does exactly what it says. Today's browser catches this only by accident — the second
    item's existence probe finds the first item's freshly-written object — so under an overwrite
    answer one file would be lost and the request would report full success.

    Args:
      items: The normalised selection.
      destination_prefix: The validated destination prefix.

    Returns:
      None.

    Raises:
      TerminalError: ``colliding_item_names`` naming the shared name.
    """
    seen: dict[str, tuple] = {}
    for item in items:
        derived = paths.derived_destination_key(destination_prefix, item)
        identity = (item["kind"], item["key"])
        if seen.get(derived, identity) != identity:
            raise TerminalError(
                "colliding_item_names",
                paths.item_name(derived),
                tokens={"itemName": paths.item_name(derived)},
            )
        seen[derived] = identity


def _per_item_outcomes(
    items: list, operation: str, source: dict, destination: dict | None, space_kind: str
) -> list:
    """Decides each item's own outcome, in the order the rules must run.

    **The ORDER is the rule, not an implementation detail.** Same-key precedes into-itself,
    because the subtree comparison matches the equal case too and would turn a rename-to-the-
    same-name into an error. It precedes the conflict evaluation a later verb adds for a second
    reason: under an overwrite answer S3 rejects a copy whose source and destination are
    identical, so the no-op has to be recognised before anything asks about collisions.

    The protected-location rules come last because they are about the item's own location rather
    than the pairing, and an item that is going nowhere does not need them.

    Args:
      items: The normalised selection.
      operation: The validated operation.
      source: The resolved source location.
      destination: The resolved destination, or None for a delete.
      space_kind: The source space's kind, which selects the bucket-asymmetric rules.

    Returns:
      One outcome record per item that has already been decided. An item with no entry is
      undecided and proceeds.

    Raises:
      None.
    """
    decided = []
    for item in items:
        label = paths.item_name(item["key"])
        refusal = protected.settings_source_refusal(source["root"], item["key"]) or protected.marker_refusal(
            item["key"]
        )
        if refusal is None and destination is not None:
            derived = paths.derived_destination_key(destination["prefix"], item)
            same_bucket = source["bucket"] == destination["bucket"]
            if same_bucket and derived == item["key"]:
                decided.append(outcomes.outcome(item["key"], label, outcomes.NOOP))
                continue
            if same_bucket and derived.startswith(normalize_root(item["key"])) and item["kind"] == "folder":
                decided.append(
                    outcomes.outcome(
                        item["key"], label, outcomes.REFUSED, "destination_inside_source"
                    )
                )
                continue
        refusal = refusal or protected.source_refusal(
            source["root"], item["key"], operation, space_kind
        )
        if refusal is not None:
            decided.append(
                outcomes.outcome(item["key"], label, outcomes.PROTECTED, refusal.reason)
            )
    return decided


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, verifies, authorizes and decides per-item outcomes.

    A thin shim; the orchestration lives below so it is testable without a Lambda context. An
    unexpected failure here happens against the raw SQS array with no trusted actor yet, so the
    wrapper's failure emit is a safe no-op in that window. ``@traced`` is outermost, above
    ``@notifies_on_failure``: the latter catches on its way out, so if it were outermost the span
    would close as successful on an invocation that actually failed and notified.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the actor is bound, or any validation reason after.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Verifies the token, authorizes both sides, validates the request and decides outcomes.

    The actor comes from the verified token in the envelope, never from a body username — the
    token is the top-level ``actor`` field, the same flat shape every plane's envelope uses and
    the one the shared DLQ drain and its redaction both depend on. From the point the actor is
    known, a whole-request rejection notifies them before the Catch records it; pre-verification
    failures have no trusted recipient and stay notification-free.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: request id, actor, operation, resolved source and destination, the
      conflict answer, the submission time and the per-item outcome list.

    Raises:
      TerminalError: ``unauthorized`` for a bad token, ``forbidden`` for an unreachable space or
        an out-of-root key, or any request-shape reason.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")

    actor = auth.verified_username(
        req.get("actor") if isinstance(req, dict) else None,
        missing_token_detail="missing actor token",
    )

    try:
        operation = _check_contract(req)
        _check_conflict_fields(req, operation)

        declared = req.get("source") if isinstance(req.get("source"), dict) else {}
        source_space = declared.get("space") if isinstance(declared.get("space"), dict) else {}
        source = authz.authorize_source(actor, declared.get("space"))
        source["items"] = _normalize_items(declared.get("items"), source["root"])

        destination = None
        if operation != "delete":
            declared_destination = req["destination"]
            destination = authz.authorize_destination(actor, declared_destination.get("space"))
            destination["prefix"] = _check_destination_prefix(
                destination["root"], declared_destination["prefix"]
            )
            destination_kind = (
                declared_destination.get("space", {}).get("kind")
                if isinstance(declared_destination.get("space"), dict)
                else None
            )
            refusal = protected.destination_refusal(
                destination["root"], destination["prefix"], destination_kind or "personal"
            )
            if refusal is not None:
                raise TerminalError(refusal.reason, refusal.detail)
            _assert_no_derived_collision(source["items"], destination["prefix"])

        decided = _per_item_outcomes(
            source["items"], operation, source, destination, source_space.get("kind") or "personal"
        )
    except TerminalError as err:
        notify.emit_failure({"actor": {"username": actor}, "operation": req.get("operation")}, err, "validate")
        raise

    validated = {
        "requestId": req.get("requestId"),
        "actor": {"username": actor},
        "operation": operation,
        "source": source,
        # Explicit nulls for a delete, so the state is one shape for all three operations and no
        # later Choice has to ask whether the field is there. A Pass reading an absent path
        # raises an uncatchable States.Runtime, and the cheapest way never to meet that is for
        # this verb to leave nothing absent.
        "destination": destination,
        "onConflict": req.get("onConflict"),
        "submittedAt": req.get("submittedAt"),
        "outcomes": decided,
    }
    logger.info(
        "validated %s of %d item(s) in %s as %s, %d decided up front",
        operation,
        len(source["items"]),
        source["root"],
        actor,
        len(decided),
    )
    observability.info(
        "file operation validated",
        actor=actor,
        operation=operation,
        source_bucket=source["bucket"],
        source_root=source["root"],
        items=len(source["items"]),
        decided=len(decided),
        cross_space=bool(destination and destination["bucket"] != source["bucket"]),
    )
    return validated
