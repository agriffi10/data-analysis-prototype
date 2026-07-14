"""validate-authorize — the table-share Step Function's first task (SPEC-089).

Parses the SQS record, verifies the caller's Cognito ID token into the trusted
actor, authorizes the actor's read access to the SOURCE table (personal = own DB;
shared = active member per the registry), validates the catalog-safe result name,
and validates each recipient exists (users via Cognito, spaces via the registry).
Read-only — no copy/create side effects. A whole-request failure raises
TerminalError with a stable reason, so the state machine's Catch records it and no
recipient is processed; a recipient that fails validation is NOT fatal — it is
annotated {valid: false, reason} and carried into the Map for a per-recipient
terminal failure (FR-003, per-recipient independence).

Emits the validated, normalized request the next states consume:
{actor, source: {database, table}, tableName, recipients: [{kind, name, valid, reason?}]}.
"""

import json
import logging

from cpcommon import auth, config
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tscommon import cognito as cog
from tscommon import notify
from tscommon.config import RECIPIENT_KINDS

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _extract_record(event):
    """The Pipe forwards the raw SQS batch (a JSON array); take the single record."""
    if isinstance(event, list):
        if not event:
            raise TerminalError("unauthorized", "empty event")
        return event[0]
    if isinstance(event, dict):
        return event
    raise TerminalError("unauthorized", "unrecognised event shape")


def _parse_request(record):
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise TerminalError("unauthorized", "missing message body")
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise TerminalError("unauthorized", f"body is not valid JSON: {exc}") from exc


def _authorize_source(source, actor) -> dict:
    """Authorize ``actor``'s read access to the source table; return it normalized.

    Personal source = the actor's own database. Anything else is treated as a
    shared-space source and requires ACTIVE membership (SPEC-089 FR-002) — an
    unknown database falls out here too (no registry record → forbidden).
    """
    if not isinstance(source, dict):
        raise TerminalError("forbidden", "missing source")
    database = source.get("database")
    table = source.get("table")
    if not isinstance(database, str) or not database or not isinstance(table, str) or not table:
        raise TerminalError("forbidden", "source must name a database and table")
    if database != actor:
        record = reg.load(database)
        if not reg.is_active_member(record, actor):
            raise TerminalError("forbidden", f"{actor!r} may not read {database!r}.{table!r}")
    return {"database": database, "table": table}


def _validate_table_name(name):
    if not isinstance(name, str) or not config.CATALOG_IDENTIFIER_RE.match(name):
        raise TerminalError("invalid_table_name", f"{name!r}")


def _normalize_recipients(recipients) -> list:
    """Shape-check + dedupe the recipient list; whole-request failure when unusable.

    A malformed entry (unknown kind, missing name) is a contract violation → terminal
    invalid_recipients; an empty (or fully-collapsed) list is terminal no_recipients.
    Existence is checked later, per recipient (annotation, not failure).
    """
    if recipients is None:
        raise TerminalError("no_recipients", "recipients missing")
    if not isinstance(recipients, list):
        raise TerminalError("invalid_recipients", "recipients must be a list")
    if not recipients:
        raise TerminalError("no_recipients", "recipients is empty")

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
        key = (kind, name)
        if key in seen:
            continue  # FR-003: duplicates collapse to one
        seen.add(key)
        normalized.append({"kind": kind, "name": name})
    return normalized


def _annotate_recipients(recipients) -> list:
    """Mark each recipient valid/invalid without failing the request (FR-003).

    user → must be an existing Cognito account; space → must be an ACTIVE registry
    space (a provisioning/deleting/failed space is not a usable target). Invalid
    recipients carry a stable reason so the Map records a per-recipient terminal
    failure (SPEC-091) and SPEC-094 can notify precisely.
    """
    annotated = []
    for entry in recipients:
        if entry["kind"] == "user":
            valid = cog.user_exists(entry["name"])
            reason = None if valid else "unknown_user"
        else:
            valid = reg.is_active(reg.load(entry["name"]))
            reason = None if valid else "unknown_space"
        annotated.append({**entry, "valid": valid, **({"reason": reason} if reason else {})})
    return annotated


@notify.notifies_on_failure("validate")
def handler(event, context) -> dict:
    # Thin handler: the parse → verify → authorize → validate → annotate orchestration
    # lives in the delegated pure function, so it is testable without a Lambda context.
    # (An UNEXPECTED failure here happens against the raw SQS array — no trusted
    # actor — so the wrapper's emit is a safe no-op in that window.)
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    record = _extract_record(event)
    req = _parse_request(record)

    # The actor comes from the verified token (the envelope's `actor` field), never
    # from a body username.
    actor = auth.verified_username(req.get("actor"), missing_token_detail="missing actor token")

    # From here the sender is KNOWN, so a whole-request rejection notifies them
    # before the Catch records it (SPEC-094 FR-003, best-effort). Pre-verification
    # failures (unauthorized) have no trusted recipient and stay notification-free.
    # The source table named in the message is display-only body input — shown
    # back to the sender who wrote it, never used for addressing.
    try:
        source = _authorize_source(req.get("source"), actor)
        table_name = req.get("tableName")
        _validate_table_name(table_name)
        recipients = _annotate_recipients(_normalize_recipients(req.get("recipients")))
    except TerminalError as err:
        raw_source = req.get("source") if isinstance(req.get("source"), dict) else {}
        notify.emit_failure({"actor": actor, "source": raw_source}, err, "validate")
        raise

    validated = {
        "actor": actor,
        "source": source,
        "tableName": table_name,
        "recipients": recipients,
    }
    logger.info(
        "validated share of %s.%s as %s for %s (%d recipients, %d valid)",
        source["database"],
        source["table"],
        table_name,
        actor,
        len(recipients),
        sum(1 for r in recipients if r["valid"]),
    )
    return validated
