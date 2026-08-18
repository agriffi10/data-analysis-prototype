"""validate-authorize — the file-send Step Function's first task.

Parses the SQS record, verifies the caller's Cognito ID token into the trusted actor,
authorizes the actor's read access to the SOURCE space, confirms every selected item sits
inside that source, enforces the request-shape caps, and annotates each recipient. Read-only:
nothing is listed, planned or copied here.

A whole-request failure raises a terminal error with a stable reason, so the Catch records it
and nothing downstream runs. A recipient that cannot be resolved is NOT fatal — it is
annotated invalid with a reason and carried forward, which is what keeps recipients
independent of one another.

The service name is the control plane, not the function, so one send's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _ALLOWED_FIELDS: The complete set of top-level request fields. Unknown fields are REJECTED
    rather than ignored (FR-002): a field the producer thinks it is sending and this verb
    silently drops is a contract break that shows up as behaviour nobody asked for, and the
    cheapest moment to catch a renamed field is the first one.
  _ITEM_KINDS: The two selection kinds a request may carry. A ``folder`` key is normalised to a
    trailing slash before any rule runs: the expansion walks a folder with a prefix listing, so
    ``alice/athenaresult`` without one would match ``alice/athenaresults/`` and carry the query
    results out through a door the results rule never sees.
  _MAX_RECIPIENT_NAME: Cognito's own limit on a username. A longer name is not "no such user" —
    ``AdminGetUser`` rejects it as an invalid parameter, which the shared lookup classifies as
    TRANSIENT, so the machine would retry three times and then fail the WHOLE request over one
    bad recipient that should have been annotated and carried. Bounded here, where it is what it
    actually is: a contract violation.
"""

import json
import logging

from cpcommon import auth, cognito, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from fscommon import authz, notify, paths
from fscommon.config import (
    RECIPIENT_KINDS,
    SEND_MAX_ITEM_BYTES,
    SEND_MAX_ITEMS,
    SEND_MAX_RECIPIENTS,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")

_ALLOWED_FIELDS = frozenset({"requestId", "actor", "source", "recipients"})

_ITEM_KINDS = frozenset({"file", "folder"})

_MAX_RECIPIENT_NAME = 128


def _check_contract(req) -> None:
    """Fails the request if its top-level shape is not the one this contract defines.

    Both directions, because only one of them is obvious. Unknown fields are REJECTED rather
    than ignored (FR-002) — a field the producer thinks it is sending and this verb silently
    drops is a contract break that surfaces as behaviour nobody asked for. And the required
    fields are type-checked, which the rejection does not imply: an absent ``requestId``
    would flow through as ``None`` and a non-string one would flow through whole, and SPEC-166
    makes that value part of an execution-unique manifest key.

    Args:
      req: The parsed request body.

    Returns:
      None.

    Raises:
      TerminalError: ``malformed_event`` when the body is not an object, names a field outside
        the contract, or carries no usable request id.
    """
    if not isinstance(req, dict):
        raise TerminalError(events.MALFORMED, "request body is not an object")
    unknown = sorted(set(req) - _ALLOWED_FIELDS)
    if unknown:
        raise TerminalError(events.MALFORMED, f"unknown request fields: {', '.join(unknown)}")
    request_id = req.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, "requestId missing or not a string")


def _normalize_items(items, source: dict) -> list:
    """Shape-checks the selection and confirms every key is one the sender may read.

    The cap is checked on the RAW list, before the per-item loop: the loop is work
    proportional to caller-supplied input, and rejecting after doing it would defeat the point
    of having a cap.

    Every key goes through both containment rules and then the results-folder rule. All three
    are whole-request terminals rather than per-item skips — a request naming a key outside
    the sender's own space is not a request with one bad row in it.

    The byte guard at the end bounds a different quantity from the count cap above: the count
    bounds the per-item work, this bounds what rides on the state and reaches the Pipe. S3 keys
    are arbitrary UTF-8 and JSON escaping expands a quote to two bytes and a control character
    to six, so a count that fits comfortably in ASCII can be several times the payload limit in
    bytes. Measured on the normalised form, which is what actually travels.

    Args:
      items: The raw selection from the request.
      source: The authorized source, carrying the root prefix.

    Returns:
      The normalised selection.

    Raises:
      TerminalError: ``no_items`` when the list is missing or empty, ``invalid_items`` for a
        non-list, a non-object entry, an unknown kind or a missing key, ``too_many_items``
        when the count cap is exceeded, ``selection_too_large`` when the serialised keys
        exceed the byte budget, ``forbidden`` when a key is not inside the source root, and
        ``results_not_sendable`` for the space's own query results.
    """
    if items is None:
        raise TerminalError("no_items", "items missing")
    if not isinstance(items, list):
        raise TerminalError("invalid_items", "items must be a list")
    if not items:
        raise TerminalError("no_items", "items is empty")
    if len(items) > SEND_MAX_ITEMS:
        raise TerminalError("too_many_items", f"{len(items)} items, over {SEND_MAX_ITEMS}")

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
        paths.assert_inside_root(root, key)
        authz.assert_not_results_folder(root, key)
        normalized.append({"kind": kind, "key": key})

    serialized = len(json.dumps(normalized, separators=(",", ":")).encode())
    if serialized > SEND_MAX_ITEM_BYTES:
        raise TerminalError(
            "selection_too_large", f"{serialized} bytes of keys, over {SEND_MAX_ITEM_BYTES}"
        )
    return normalized


def _normalize_recipients(recipients) -> list:
    """Shape-checks and de-duplicates the recipient list.

    A malformed entry is a contract violation and fails the whole request; existence is
    checked later, per recipient, as an annotation rather than a failure. Duplicates collapse
    to one, and **sending to oneself is permitted** — it lands in the sender's own inbox and
    conflicts naturally if repeated.

    The cap is checked before the de-duplication loop for the same reason the item cap is, and
    de-duplication can only shrink the list, so a request that passes here cannot exceed the
    cap afterwards.

    Args:
      recipients: The raw recipient list from the request.

    Returns:
      The normalised, de-duplicated recipients.

    Raises:
      TerminalError: ``no_recipients`` when the list is missing or empty,
        ``invalid_recipients`` for a non-list, a non-object entry, an unknown kind or a
        missing name, or ``too_many_recipients`` when the cap is exceeded.
    """
    if recipients is None:
        raise TerminalError("no_recipients", "recipients missing")
    if not isinstance(recipients, list):
        raise TerminalError("invalid_recipients", "recipients must be a list")
    if not recipients:
        raise TerminalError("no_recipients", "recipients is empty")
    if len(recipients) > SEND_MAX_RECIPIENTS:
        raise TerminalError(
            "too_many_recipients", f"{len(recipients)} recipients, over {SEND_MAX_RECIPIENTS}"
        )

    normalized = []
    seen = set()
    for entry in recipients:
        if not isinstance(entry, dict):
            raise TerminalError("invalid_recipients", "each recipient must be an object")
        kind = entry.get("kind")
        if kind not in RECIPIENT_KINDS:
            raise TerminalError("invalid_recipients", f"unknown recipient kind {kind!r}")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TerminalError("invalid_recipients", "recipient name missing")
        name = name.strip().lower()
        if len(name) > _MAX_RECIPIENT_NAME:
            raise TerminalError("invalid_recipients", f"recipient name is {len(name)} characters")
        key = (kind, name)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"kind": kind, "name": name})
    return normalized


def _annotate_recipients(recipients) -> list:
    """Marks each recipient reachable or not, without failing the request.

    A user must be an existing Cognito account; a space must be an active registry space.
    **Membership is not required** — any space by name is a valid target, matching table
    share's recorded decision, because the execution role does the write and the sender's own
    access question was about the source.

    The username directory is deliberately NOT consulted: it is advisory and never an
    authorization input, so existence stays ``admin_get_user``.

    Args:
      recipients: The normalised recipients.

    Returns:
      The recipients, each carrying an ``invalid`` reason when it could not be resolved.

    Raises:
      TransientError: On a Cognito fault other than the user not existing.
    """
    annotated = []
    for entry in recipients:
        if entry["kind"] == "user":
            reason = None if cognito.user_exists(entry["name"]) else "unknown_user"
        else:
            reason = None if reg.is_active(reg.load(entry["name"])) else "unknown_space"
        annotated.append({**entry, **({"invalid": reason} if reason else {})})
    return annotated


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, verifies, authorizes and annotates the request.

    A thin shim; the orchestration lives below so it is testable without a Lambda context. An
    unexpected failure here happens against the raw SQS array with no trusted actor yet, so
    the wrapper's failure emit is a safe no-op in that window. ``@traced`` is outermost, above
    ``@notifies_on_failure``: the latter catches on its way out, so if it were outermost the
    span would close as successful on an invocation that actually failed and notified.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated, normalised request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the sender is bound, or any validation reason
        afterwards.
      TransientError: On a retryable Cognito or S3 fault.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Verifies the token, authorizes the source, validates the request and annotates recipients.

    The actor comes from the verified token in the envelope, never from a body username — the
    token is the top-level ``actor`` field, the same flat shape every plane's envelope uses and
    the one the drain and its redaction both depend on. From the point the sender is
    known, a whole-request rejection notifies them before the Catch records it; pre-verification
    failures have no trusted recipient and stay notification-free.

    Requested and reachable recipient counts are both recorded, because they diverge silently:
    a send to five recipients where two resolve to nothing is neither a failure nor a clean
    success, and one count cannot say which.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: request id, actor, resolved source and annotated recipients.

    Raises:
      TerminalError: ``unauthorized`` for a bad token, ``forbidden`` for an unreadable source
        or an out-of-root key, or any item/recipient list reason.
      TransientError: On a retryable Cognito or S3 fault.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")

    actor = auth.verified_username(
        req.get("actor") if isinstance(req, dict) else None,
        missing_token_detail="missing actor token",
    )

    try:
        _check_contract(req)
        declared = req.get("source") if isinstance(req.get("source"), dict) else {}
        source = authz.authorize_source(actor, declared.get("space"))
        source["items"] = _normalize_items(declared.get("items"), source)
        recipients = _annotate_recipients(_normalize_recipients(req.get("recipients")))
    except TerminalError as err:
        notify.emit_failure({"actor": {"username": actor}}, err, "validate")
        raise

    validated = {
        "requestId": req.get("requestId"),
        "actor": {"username": actor},
        "source": source,
        "recipients": recipients,
    }
    unreachable = [r["name"] for r in recipients if r.get("invalid")]
    logger.info(
        "validated send of %d item(s) from %s as %s for %d recipient(s), %d unreachable",
        len(source["items"]),
        source["root"],
        actor,
        len(recipients),
        len(unreachable),
    )
    observability.info(
        "send validated",
        actor=actor,
        source_bucket=source["bucket"],
        source_root=source["root"],
        items=len(source["items"]),
        recipients_requested=len(recipients),
        recipients_reachable=len(recipients) - len(unreachable),
        unreachable_recipients=unreachable,
    )
    return validated
