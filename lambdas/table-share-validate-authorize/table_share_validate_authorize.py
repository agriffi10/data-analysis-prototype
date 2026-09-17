"""validate-authorize — the table-share Step Function's first task.

Parses the SQS record, reads the trusted actor out of the API's identity block,
authorizes the actor's read access to the source table, validates the catalog-safe result name,
and validates each recipient exists. Read-only, with no copy or create side effects.

A whole-request failure raises a terminal error with a stable reason, so the Catch records it
and no recipient is processed. A recipient that fails validation is not fatal — it is annotated
invalid with a reason and carried into the Map for a per-recipient terminal failure, which is
what keeps recipients independent of each other.

The service name is the control plane, not the function, so one share's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import actor as cpactor
from cpcommon import config, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tscommon import cognito as cog
from tscommon import notify
from tscommon.config import RECIPIENT_KINDS, SHARE_MAX_RECIPIENTS

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


def _message_id(event) -> str | None:
    """Reads the SQS message id of the request this run was started from.

    It names the run in validate-authorize's own refusal notices. The machine stamps the
    execution's name onto the state only after this verb, and its input is the Pipe's record, so
    the message id is the one identity it holds: one per enqueued request, the same on a retry and
    on a redelivery. Its notices never meet another door's, since notify-failure tells nobody of a
    refusal a verb already told and has no sender on this verb's failure seed.

    Args:
      event: The Pipe payload, in either shape ``events.parse_sqs_request`` accepts.

    Returns:
      The message id, or None when the record carries no usable one.

    Raises:
      None.
    """
    record = event[0] if isinstance(event, list) and event else event
    value = record.get("messageId") if isinstance(record, dict) else None
    return value if isinstance(value, str) and value else None


def _authorize_source(source, actor) -> dict:
    """Authorizes the actor's read access to the source table and normalises it.

    A personal source is the actor's own database. Anything else is treated as a shared-space
    source and requires active membership, so an unknown database falls out here too — no
    registry record means no access.

    Args:
      source: The request's source, naming a database and table.
      actor: The verified username.

    Returns:
      The normalised source.

    Raises:
      TerminalError: ``forbidden`` when the source is missing, incomplete, or the actor is not
        an active member of the database it names.
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
    """Checks the requested result name against the catalog-safe identifier rule.

    Args:
      name: The requested result table name.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_table_name`` when it is not a catalog-safe identifier.
    """
    if not isinstance(name, str) or not config.CATALOG_IDENTIFIER_RE.fullmatch(name):
        raise TerminalError("invalid_table_name", f"{name!r}")


def _normalize_recipients(recipients) -> list:
    """Shape-checks and de-duplicates the recipient list.

    A malformed entry is a contract violation and fails the whole request; existence is checked
    later, per recipient, as an annotation rather than a failure. Duplicates collapse to one.

    The cap is checked before the de-duplication loop, on the raw list: the loop is work
    proportional to caller-supplied input, and the reason a cap exists at all is to stop an
    unbounded list reaching the Map, so rejecting after normalising would still have done the
    work. De-duplication can only shrink the list, so a request that passes here can never
    exceed the cap afterwards.

    Args:
      recipients: The raw recipient list from the request.

    Returns:
      The normalised, de-duplicated recipients.

    Raises:
      TerminalError: ``no_recipients`` when the list is missing or empty,
        ``invalid_recipients`` for a non-list, a non-object entry, an unknown kind or a missing
        name, or ``too_many_recipients`` when the cap is exceeded.
    """
    if recipients is None:
        raise TerminalError("no_recipients", "recipients missing")
    if not isinstance(recipients, list):
        raise TerminalError("invalid_recipients", "recipients must be a list")
    if not recipients:
        raise TerminalError("no_recipients", "recipients is empty")
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
        if not events.in_vocabulary(kind, RECIPIENT_KINDS):
            raise TerminalError("invalid_recipients", f"unknown recipient kind {kind!r}")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TerminalError("invalid_recipients", "recipient name missing")
        name = name.strip().lower()
        key = (kind, name)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"kind": kind, "name": name})
    return normalized


def _annotate_recipients(recipients) -> list:
    """Marks each recipient valid or invalid without failing the request.

    A user must be an existing Cognito account; a space must be an active registry space, since
    one still provisioning, deleting or failed is not a usable target. Invalid recipients carry
    a stable reason so the Map records a per-recipient terminal failure and the notification can
    be precise.

    Args:
      recipients: The normalised recipients.

    Returns:
      The recipients, each carrying a validity flag and a reason when invalid.

    Raises:
      TransientError: On a Cognito fault other than the user not existing.
    """
    annotated = []
    for entry in recipients:
        if entry["kind"] == "user":
            valid = cog.user_exists(entry["name"])
            reason = None if valid else "unknown_user"
        else:
            valid = reg.may_receive_share(reg.load(entry["name"]))
            reason = None if valid else "unknown_space"
        annotated.append({**entry, "valid": valid, **({"reason": reason} if reason else {})})
    return annotated


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, attributes, authorizes and annotates the request.

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
      TerminalError: ``unauthorized`` before the sender is bound, or any validation reason
        afterwards.
      TransientError: On a retryable Cognito or S3 fault.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Reads the trusted actor, authorizes the source, validates the request, annotates recipients.

    The actor comes from the ``identity`` block the API stamped, never from a body username and
    never from the flat field beside it. From the point the sender is known, a whole-request
    rejection notifies them before the Catch records it; a failure before it has no trusted
    recipient and stays notification-free.
    The source table named in that message is display-only body input — shown back to the sender
    who wrote it, never used for addressing.

    Requested and valid recipient counts are both recorded, because they diverge silently: a
    share to five recipients where two resolve to nothing is neither a failure nor a clean
    success, and one count cannot say which. Recipient names are permitted metadata, and the
    whole question when someone asks why they did not receive a table.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: actor, source, result table name and annotated recipients.

    Raises:
      TerminalError: ``unauthorized`` for an unusable identity block, ``forbidden`` for an
        unreadable source,
        ``invalid_table_name``, or any recipient-list reason.
      TransientError: On a retryable Cognito or S3 fault.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")

    who = cpactor.trusted_actor(req)
    observability.stamp(
        actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
    )
    actor = who.username

    try:
        source = _authorize_source(req.get("source"), actor)
        table_name = req.get("tableName")
        _validate_table_name(table_name)
        recipients = _annotate_recipients(_normalize_recipients(req.get("recipients")))
    except TerminalError as err:
        raw_source = req.get("source") if isinstance(req.get("source"), dict) else {}
        notify.emit_failure({"actor": actor, "source": raw_source}, err, "validate", run=_message_id(event))
        raise

    validated = {
        "traceparent": observability.run_traceparent(),
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
