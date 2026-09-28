"""validate-authorize — the archive Step Function's first task, for BOTH of its modes.

Parses the SQS record, reads the trusted actor out of the API's identity block, authorizes
the actor's access to the space, and resolves the archive prefix — for an ARCHIVE, checking that
every selected item sits inside the source and is not one of the portal's own folders and
enforcing the request-shape caps, and checking the optional archive name against
``arcommon.names`` before the space is authorized, since authorizing a shared space reads the
registry and a refused name should cost nothing; for a RESTORE, validating the pasted archive id
before it is concatenated into a key. Read-only in both: nothing is listed, copied or deleted
here.

**The restore branch lives in this verb rather than in a second front-door Lambda, and that is
forced by the machine's shape.** ``ChooseMode`` sits DOWNSTREAM of this task and branches on
``$.mode`` of the parsed request; in the raw Pipe record the same field is buried inside an
escaped JSON string that ASL cannot look into. A separate restore validator would need the
branch to happen before anything had parsed the body.

**Both modes return the same six top-level keys** — ``traceparent``, ``requestId``, ``mode``,
``actor``, ``source``, ``archive`` — because both flow through one ``Validated`` Pass and a Pass
naming a path the state does not carry raises an uncatchable ``States.Runtime``. (It said five
until the run's traceparent joined them; the identical count in the ASL comment was corrected and
this copy was not, which is what a claim written twice costs.)
``source`` is the authorized SPACE in both — the archive's source in one mode, the restore's
destination in the other — and only its ``items`` are archive-only.

A whole-request failure raises a terminal error with a stable reason, so the Catch records it
and nothing downstream runs. **There are no per-item and no per-recipient failures on this
plane**: an archive has one actor, one source and one destination, so every refusal is a
whole-request refusal — which is also what makes "nothing was archived" a true statement in
every message this verb can produce.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _ALLOWED_FIELDS: The complete set of top-level request fields, PER MODE. Unknown fields are
    REJECTED rather than ignored: a field the producer thinks it is sending and this
    verb silently drops is a contract break that shows up as behaviour nobody asked for, and the
    cheapest moment to catch a renamed field is the first one.

    **Per mode rather than a union**, because the two contracts genuinely differ — ``source``
    against ``space`` + ``archiveId`` — and a union would accept a restore carrying a selection
    and an archive naming an archive id, then silently ignore whichever the mode did not read.
  _ITEM_KINDS: The two selection kinds a request may carry. A ``folder`` key is normalised to a
    trailing slash before any rule runs: the archive expands a folder with a prefix listing, so
    ``alice/archiv`` without one would match ``alice/archive/`` and carry the receipts of every
    past archive out through a door the reserved-root rule never sees.
"""

import json
import logging

from arcommon import authz, names, notify, paths, restore
from arcommon.config import (
    ARCHIVE_MAX_ITEM_BYTES,
    ARCHIVE_MAX_ITEMS,
    ARCHIVE_MODES,
    archive_bucket,
)
from cpcommon import actor as cpactor
from cpcommon import events, observability
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

_ALLOWED_FIELDS = {
    "archive": frozenset(
        {"requestId", "mode", "actor", "source", "archiveName", "identity", "traceparent"}
    ),
    "restore": restore.ALLOWED_FIELDS,
}

_ITEM_KINDS = frozenset({"file", "folder"})


def _check_contract(req) -> str:
    """Fails the request if its top-level shape is not the one its mode's contract defines.

    Both directions, because only one of them is obvious. Unknown fields are REJECTED rather
    than ignored — a field the producer thinks it is sending and this verb silently
    drops is a contract break that surfaces as behaviour nobody asked for. And the required
    fields are type-checked, which the rejection does not imply: an absent ``requestId`` would
    flow through as ``None``, and this value becomes the ``{uuid}`` segment of a key in two
    buckets.

    **The mode is settled BEFORE the unknown-field check**, because the mode is what says which
    fields are known. The order costs nothing: an unrecognised mode is refused either way, and
    the alternative — a union of both contracts — is the check not being made.

    The id's FORM is not checked here — ``arcommon.paths.validated_request_id`` owns that, and
    owns it at every point of concatenation rather than once at the front door.

    Args:
      req: The parsed request body.

    Returns:
      The request's mode, so the caller branches on a value this function has already validated
      rather than re-reading the untrusted body.

    Raises:
      TerminalError: ``malformed_event`` when the body is not an object, carries no usable
        request id or mode, or names a field outside its mode's contract.
    """
    if not isinstance(req, dict):
        raise TerminalError(events.MALFORMED, "request body is not an object")
    if not isinstance(req.get("requestId"), str) or not req["requestId"].strip():
        raise TerminalError(events.MALFORMED, "requestId missing or not a string")
    mode = req.get("mode")
    if not events.in_vocabulary(mode, ARCHIVE_MODES):
        raise TerminalError(events.MALFORMED, f"unexpected mode {mode!r}")
    unknown = sorted(set(req) - _ALLOWED_FIELDS[mode])
    if unknown:
        raise TerminalError(
            events.MALFORMED, f"unknown {mode} request fields: {', '.join(unknown)}"
        )
    return mode


def _normalize_items(items, source: dict) -> list:
    """Shape-checks the selection and confirms every key is one the actor may archive.

    The cap is checked on the RAW list, before the per-item loop: the loop is work proportional
    to caller-supplied input, and rejecting after doing it would defeat the point of having a
    cap.

    Every key goes through containment, then the reserved-root rule, then the marker rule. All
    three are whole-request terminals rather than per-item skips — and on this plane that is
    more than a style choice: archiving deletes the source, so a selection with one bad row in
    it must not become a partial archive whose refused row was silently dropped.

    The byte guard at the end bounds a different quantity from the count cap above: the count
    bounds the per-item work, this bounds what rides on the state and reaches the Pipe. Measured
    on the normalised form, which is what actually travels.

    Args:
      items: The raw selection from the request.
      source: The authorized source, carrying the root prefix.

    Returns:
      The normalised selection.

    Raises:
      TerminalError: ``no_items`` when the list is missing or empty, ``invalid_items`` for a
        non-list, a non-object entry, an unknown kind or a missing key, ``too_many_items`` when
        the count cap is exceeded, ``selection_too_large`` when the serialised keys exceed the
        byte budget, ``forbidden`` when a key is not inside the source root, ``reserved_folder``
        for a portal-managed folder, and ``protected_marker`` for a prefix marker.
    """
    if items is None:
        raise TerminalError("no_items", "items missing")
    if not isinstance(items, list):
        raise TerminalError("invalid_items", "items must be a list")
    if not items:
        raise TerminalError("no_items", "items is empty")
    if len(items) > ARCHIVE_MAX_ITEMS:
        raise TerminalError("too_many_items", f"{len(items)} items, over {ARCHIVE_MAX_ITEMS}")

    root = source["root"]
    normalized = []
    for entry in items:
        if not isinstance(entry, dict):
            raise TerminalError("invalid_items", "each item must be an object")
        kind = entry.get("kind")
        if not events.in_vocabulary(kind, _ITEM_KINDS):
            raise TerminalError("invalid_items", f"unknown item kind {kind!r}")
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            raise TerminalError("invalid_items", "item key missing")
        if kind == "folder" and not key.endswith("/"):
            key = f"{key}/"
        assert_inside_root(root, key)
        authz.assert_not_reserved(root, key)
        authz.assert_not_protected_marker(key)
        normalized.append({"kind": kind, "key": key})

    serialized = len(json.dumps(normalized, separators=(",", ":")).encode())
    if serialized > ARCHIVE_MAX_ITEM_BYTES:
        raise TerminalError(
            "selection_too_large", f"{serialized} bytes of keys, over {ARCHIVE_MAX_ITEM_BYTES}"
        )
    return normalized


def _wording_mode(req) -> str:
    """Reads the mode for the WORDING of a refusal, before the contract has validated anything.

    **Found in review, and it is the case the two-prefix design exists for.** Every refusal
    ``_check_contract`` raises — a non-object body, a bad request id, an unknown mode, an unknown
    field — happens BEFORE the mode has been validated, so taking the mode from the validator's
    return leaves exactly those failures worded as archives. A user who pasted an archive id and
    clicked Restore would read "Couldn't archive that".

    It reads the UNTRUSTED body, and that is safe here because of what the value can do: it selects
    between two fixed prefixes and nothing else. It is not an authorization input, it does not
    reach a key, and ``_check_contract`` still refuses anything outside ``ARCHIVE_MODES`` before a
    single AWS call. An attacker's only reward is being told "Couldn't restore that" about a
    request they malformed themselves.

    Args:
      req: The parsed request body, of any shape.

    Returns:
      The mode as the body claims it, or an empty string — which renders the archive wording.

    Raises:
      None.
    """
    mode = req.get("mode") if isinstance(req, dict) else None
    return mode if events.in_vocabulary(mode, ARCHIVE_MODES) else ""


def _restore(req: dict, request_id: str, actor: str) -> dict:
    """Validates a restore request and logs what it resolved.

    A thin seam over ``arcommon.restore.validate`` so this verb's two modes read the same way at
    the call site and the domain rules stay in the layer both future restore verbs import.

    Args:
      req: The parsed request body.
      request_id: The validated request id for this run.
      actor: The verified username.

    Returns:
      The validated restore request.

    Raises:
      TerminalError: ``malformed_event``, ``invalid_request`` or ``forbidden`` from the
        validation.
      TransientError: On a retryable S3 fault reading the shared-space registry.
    """
    validated = restore.validate(req, request_id, actor)
    space, archive = validated["source"], validated["archive"]
    logger.info(
        "validated restore of archive %s into %s as %s",
        archive["archiveId"],
        space["root"],
        actor,
    )
    observability.info(
        "restore validated",
        actor=actor,
        space_bucket=space["bucket"],
        space_root=space["root"],
        space_kind=space["kind"],
        archive_id=archive["archiveId"],
        archive_root=archive["root"],
    )
    return validated


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, verifies, authorizes and resolves the request.

    A thin shim; the orchestration lives below so it is testable without a Lambda context. An
    unexpected failure here happens against the raw SQS array with no trusted actor yet, so the
    wrapper's failure emit is a safe no-op in that window. ``@traced`` is outermost, above
    ``@notifies_on_failure``: the latter catches on its way out, so if it were outermost the
    span would close as successful on an invocation that actually failed and notified.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated, normalised request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the actor is bound, or any validation reason
        afterwards.
      TransientError: On a retryable S3 fault reading the registry.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Reads the trusted actor, authorizes the space, validates the request and resolves the keys.

    **The mode branch happens here and cannot happen earlier.** ``ChooseMode`` in the ASL reads
    ``$.mode`` off the object this function returns; in the raw Pipe record the same field sits
    inside an escaped JSON string. Everything up to and including the actor read is common to
    both modes, and the two contracts diverge only once the mode is known.

    The actor comes from the ``identity`` block the API stamped, never from a body username and
    never from the flat ``actor`` field beside it — that field carries the raw token on a message
    enqueued before the API stopped sending one, and a JWT and a username are both non-empty
    strings. From the point the actor is known, a whole-request rejection notifies them before the
    Catch records it; a failure before it has no trusted recipient and stays notification-free.

    **The archive prefix is resolved HERE, not by the verb that copies.** It is a pure function
    of the request — kind, name and request id — so computing it once and carrying it forward
    means the copier, the receipt writer and the restore all read one string rather than
    three agreeing constructions of it.

    The wording mode is seeded from the untrusted body, so a refusal raised INSIDE the contract
    check is still worded as the operation the user asked for; the mode is then replaced by the
    validated value the rest of the function uses.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: request id, mode, actor, the authorized space and the archive
      location — the same five keys in either mode.

    Raises:
      TerminalError: ``unauthorized`` for an unusable identity block, ``forbidden`` for an
        unreachable space or
        an out-of-root key, ``invalid_request`` for a malformed request or archive id,
        ``invalid_name`` for an archive name the rule refuses, or any selection reason.
      TransientError: On a retryable S3 fault.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")

    who = cpactor.trusted_actor(req)
    observability.stamp(
        actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
    )
    actor = who.username

    mode = _wording_mode(req)
    try:
        mode = _check_contract(req)
        request_id = paths.validated_request_id(req.get("requestId"))
        if mode == "restore":
            return _restore(req, request_id, actor)
        name = names.validated_name(req["archiveName"]) if "archiveName" in req else None
        declared = req.get("source") if isinstance(req.get("source"), dict) else {}
        source = authz.authorize_source(actor, declared.get("space"))
        source["items"] = _normalize_items(declared.get("items"), source)
        archive_root = paths.archive_root(source["kind"], source["name"], request_id)
        receipt_key = paths.receipt_key(source["name"], request_id)
    except TerminalError as err:
        notified = {"requestId": req.get("requestId"), "actor": {"username": actor}, "mode": mode}
        notify.emit_failure(notified, err, "validate")
        raise

    validated = {
        "traceparent": observability.run_traceparent(),
        "requestId": request_id,
        "mode": "archive",
        "actor": {"username": actor},
        "source": source,
        "archive": {
            "bucket": archive_bucket(),
            "root": archive_root,
            "receiptBucket": source["bucket"],
            "receiptKey": receipt_key,
            "indexKey": paths.index_key(source["name"]),
            "name": name,
        },
    }
    logger.info(
        "validated archive of %d item(s) from %s as %s into %s",
        len(source["items"]),
        source["root"],
        actor,
        archive_root,
    )
    observability.info(
        "archive validated",
        actor=actor,
        source_bucket=source["bucket"],
        source_root=source["root"],
        space_kind=source["kind"],
        items=len(source["items"]),
        archive_root=archive_root,
    )
    return validated
