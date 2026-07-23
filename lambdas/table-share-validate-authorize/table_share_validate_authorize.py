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

import logging

from cpcommon import auth, config, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tscommon import cognito as cog
from tscommon import notify
from tscommon.config import RECIPIENT_KINDS, SHARE_MAX_RECIPIENTS

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share is five invocations (plus a
# recipient Map fan-out), and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field.
observability.init(service="table-share")


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
    # Checked BEFORE the dedupe loop, on the raw list: the loop is O(n) work on
    # caller-supplied input, and the reason a cap exists at all is to stop an unbounded list
    # reaching the Map. Rejecting 10,000 entries after normalising them would still have
    # done the work. (Dedupe can only shrink the list, so a request that passes here can
    # never exceed the cap after collapsing.)
    if len(recipients) > SHARE_MAX_RECIPIENTS:
        raise TerminalError(
            "too_many_recipients", f"{len(recipients)} recipients, over {SHARE_MAX_RECIPIENTS}"
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


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """SFN entry point: parse → verify → authorize → validate → annotate the share request.

    A thin shim; the orchestration lives in ``_validate_and_authorize`` so it is testable
    without a Lambda context. An unexpected failure here happens against the raw SQS array
    (no trusted actor yet), so the wrapper's failure-emit is a safe no-op in that window.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    req = events.parse_sqs_request(event, reason="unauthorized")

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
    # Requested vs VALID, because they diverge silently: a share to five recipients where two
    # resolve to nothing is not a failure and not a clean success, and the count alone cannot
    # say which. Recipient NAMES are space/user names — permitted metadata, and the whole
    # question when someone asks why they did not receive a table.
    observability.info(
        "share validated",
        actor=actor,
        source_database=source["database"],
        source_table=source["table"],
        table=table_name,
        recipients_requested=len(recipients),
        recipients_valid=sum(1 for r in recipients if r["valid"]),
        invalid_recipients=[r.get("name") for r in recipients if not r["valid"]],
    )
    return validated
