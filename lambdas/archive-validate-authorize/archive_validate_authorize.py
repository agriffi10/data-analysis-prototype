"""validate-authorize — the archive Step Function's first task.

Parses the SQS record, verifies the caller's Cognito ID token into the trusted actor, authorizes
the actor's access to the SOURCE space, confirms every selected item sits inside that source and
is not one of the portal's own folders, enforces the request-shape caps, and resolves the
archive prefix the objects will be written under. Read-only: nothing is listed, copied or
deleted here.

A whole-request failure raises a terminal error with a stable reason, so the Catch records it
and nothing downstream runs. **There are no per-item and no per-recipient failures on this
plane**: an archive has one actor, one source and one destination, so every refusal is a
whole-request refusal — which is also what makes "nothing was archived" a true statement in
every message this verb can produce.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _ALLOWED_FIELDS: The complete set of top-level request fields. Unknown fields are REJECTED
    rather than ignored (FR-004): a field the producer thinks it is sending and this verb
    silently drops is a contract break that shows up as behaviour nobody asked for, and the
    cheapest moment to catch a renamed field is the first one.
  _ITEM_KINDS: The two selection kinds a request may carry. A ``folder`` key is normalised to a
    trailing slash before any rule runs: SPEC-169 expands a folder with a prefix listing, so
    ``alice/archiv`` without one would match ``alice/archive/`` and carry the receipts of every
    past archive out through a door the reserved-root rule never sees.
"""

import json
import logging

from arcommon import authz, notify, paths
from arcommon.config import ARCHIVE_MAX_ITEM_BYTES, ARCHIVE_MAX_ITEMS, archive_bucket
from cpcommon import auth, events, observability
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

_ALLOWED_FIELDS = frozenset({"requestId", "mode", "actor", "source"})

_ITEM_KINDS = frozenset({"file", "folder"})


def _check_contract(req) -> None:
    """Fails the request if its top-level shape is not the one this contract defines.

    Both directions, because only one of them is obvious. Unknown fields are REJECTED rather
    than ignored (FR-004) — a field the producer thinks it is sending and this verb silently
    drops is a contract break that surfaces as behaviour nobody asked for. And the required
    fields are type-checked, which the rejection does not imply: an absent ``requestId`` would
    flow through as ``None``, and this value becomes the ``{uuid}`` segment of a key in two
    buckets.

    The id's FORM is not checked here — ``arcommon.paths.validated_request_id`` owns that, and
    owns it at every point of concatenation rather than once at the front door.

    Args:
      req: The parsed request body.

    Returns:
      None.

    Raises:
      TerminalError: ``malformed_event`` when the body is not an object, names a field outside
        the contract, or carries no usable request id or mode.
    """
    if not isinstance(req, dict):
        raise TerminalError(events.MALFORMED, "request body is not an object")
    unknown = sorted(set(req) - _ALLOWED_FIELDS)
    if unknown:
        raise TerminalError(events.MALFORMED, f"unknown request fields: {', '.join(unknown)}")
    if not isinstance(req.get("requestId"), str) or not req["requestId"].strip():
        raise TerminalError(events.MALFORMED, "requestId missing or not a string")
    if req.get("mode") != "archive":
        raise TerminalError(events.MALFORMED, f"unexpected mode {req.get('mode')!r}")


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
        if kind not in _ITEM_KINDS:
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
    """Verifies the token, authorizes the source, validates the selection and resolves the keys.

    The actor comes from the verified token in the envelope, never from a body username — the
    token is the top-level ``actor`` field, the same flat shape every plane's envelope uses and
    the one SPEC-126's drain and its redaction both depend on. From the point the actor is
    known, a whole-request rejection notifies them before the Catch records it;
    pre-verification failures have no trusted recipient and stay notification-free.

    **The archive prefix is resolved HERE, not by the verb that copies.** It is a pure function
    of the request — kind, name and request id — so computing it once and carrying it forward
    means the copier, the receipt writer and SPEC-170's restore all read one string rather than
    three agreeing constructions of it.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: request id, mode, actor, resolved source and archive destination.

    Raises:
      TerminalError: ``unauthorized`` for a bad token, ``forbidden`` for an unreadable source or
        an out-of-root key, ``invalid_request`` for a malformed request id, or any selection
        reason.
      TransientError: On a retryable S3 fault.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")

    actor = auth.verified_username(
        req.get("actor") if isinstance(req, dict) else None,
        missing_token_detail="missing actor token",
    )

    try:
        _check_contract(req)
        request_id = paths.validated_request_id(req.get("requestId"))
        declared = req.get("source") if isinstance(req.get("source"), dict) else {}
        source = authz.authorize_source(actor, declared.get("space"))
        source["items"] = _normalize_items(declared.get("items"), source)
        archive_root = paths.archive_root(source["kind"], source["name"], request_id)
        receipt_key = paths.receipt_key(source["name"], request_id)
    except TerminalError as err:
        notify.emit_failure({"actor": {"username": actor}}, err, "validate")
        raise

    validated = {
        "requestId": request_id,
        "mode": "archive",
        "actor": {"username": actor},
        "source": source,
        "archive": {
            "bucket": archive_bucket(),
            "root": archive_root,
            "receiptBucket": source["bucket"],
            "receiptKey": receipt_key,
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
