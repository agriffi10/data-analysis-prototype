"""validate-authorize — the table-builder Step Function's first task.

Parses the SQS record, verifies the caller's Cognito ID token into the trusted
actor, authorizes the target space/DB, and validates the table name, partition keys,
and in-space location. Read-only — no provisioning side effects. A failed check
raises TerminalError with a stable reason, so the state machine's Catch records the
failure and no downstream verb runs.

Emits the validated, normalized request the next states consume:
{actor, space, tableName, partitionKeys, location, requestId}.
"""

import logging

from cpcommon import auth, config, events
from cpcommon import errors
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tbcommon import notify
from tbcommon.config import PARTITION_TYPES

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _load_registry(database: str):
    """Load the shared-space registry record, mapping a throttle to ``TransientError``.

    ``registry.load`` catches only ``NoSuchKey``, so a throttle on the underlying
    ``get_object`` propagates as a bare ``ClientError`` — which the ValidateAuthorize
    Retry list does not name, so it would permanently fail the request. Mapping it (paired
    with adding ``TransientError`` to that Retry list) is what gets it retried. Mapped
    HERE, at the verb, not in ``cpcommon.registry.load``: that is shared with the
    shared-space verbs, whose state machine does not retry ``TransientError``.
    """
    try:
        return reg.load(database)
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"registry load {database}")
        raise


def _normalize_prefix(prefix):
    """Trim, drop a leading slash, ensure a single trailing slash."""
    p = (prefix or "").strip().lstrip("/")
    if p and not p.endswith("/"):
        p += "/"
    return p


def _validate_table_name(name):
    if not isinstance(name, str) or not config.CATALOG_IDENTIFIER_RE.match(name):
        raise TerminalError("invalid_table_name", f"{name!r}")


def _validate_partition_keys(keys):
    """Validate the user-declared partition keys; [] or None means a flat table."""
    if not keys:
        return []
    if not isinstance(keys, list):
        raise TerminalError("invalid_partition_keys", "partitionKeys must be a list")
    seen = set()
    for key in keys:
        if not isinstance(key, dict):
            raise TerminalError("invalid_partition_keys", "each partition key must be an object")
        name = key.get("name")
        if not isinstance(name, str) or not config.CATALOG_IDENTIFIER_RE.match(name):
            raise TerminalError("invalid_partition_keys", f"invalid key name {name!r}")
        if name in seen:
            raise TerminalError("invalid_partition_keys", f"duplicate key name {name!r}")
        seen.add(name)
        ptype = key.get("type")
        if ptype not in PARTITION_TYPES:
            raise TerminalError("invalid_partition_keys", f"{name}: invalid type {ptype!r}")
        if ptype in ("integer", "date"):
            rng = key.get("range")
            if not (isinstance(rng, list) and len(rng) == 2):
                raise TerminalError("invalid_partition_keys", f"{name}: range must be [min, max]")
        else:  # string → projection enum
            values = key.get("values")
            if not (isinstance(values, list) and len(values) >= 1):
                raise TerminalError("invalid_partition_keys", f"{name}: values must be a non-empty list")
    return keys


def _authorize_space(space, actor):
    """Authorize ``actor`` for the target space; return the normalized prefix."""
    if not isinstance(space, dict):
        raise TerminalError("forbidden", "missing space")
    kind = space.get("kind")
    bucket = space.get("bucket")
    database = space.get("database")
    prefix = _normalize_prefix(space.get("prefix"))

    if kind == "personal":
        if database != actor:
            raise TerminalError("forbidden", "personal database must be the actor's own")
        if bucket != config.USER_SPACE_BUCKET:
            raise TerminalError("forbidden", "personal space must be the user-space bucket")
        if not prefix.startswith(f"{actor}/"):
            raise TerminalError("forbidden", "location escapes the personal space")
    elif kind == "shared":
        record = _load_registry(database)
        if not reg.is_active_member(record, actor):
            raise TerminalError("forbidden", f"{actor!r} is not an active member of {database!r}")
        if bucket != config.SHARED_SPACE_BUCKET:
            raise TerminalError("forbidden", "shared space must be the shared-space bucket")
        if not prefix.startswith(f"{database}/"):
            raise TerminalError("forbidden", "location escapes the shared space")
    else:
        raise TerminalError("forbidden", f"unknown space kind {kind!r}")
    return prefix


@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """SFN entry point: parse → verify → authorize → validate → assemble the build state.

    A thin shim; the orchestration (including the notify-on-failure envelope) lives in
    ``_validate_and_authorize`` so it is testable without a Lambda context.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    req = events.parse_sqs_request(event, reason="unauthorized")
    space = req.get("space") or {}

    # The actor comes from the verified token, never the body. An unauthorized failure
    # raises before the actor is known — there is no recipient to notify (the SFN still
    # records it), so this is deliberately outside the try below.
    actor = auth.verified_username(req.get("idToken"))

    # From here the actor is known, so a terminal validation failure notifies the actor
    # (best-effort) before the SFN Catch records it.
    try:
        prefix = _authorize_space(space, actor)
        table_name = req.get("tableName")
        _validate_table_name(table_name)
        partition_keys = _validate_partition_keys(req.get("partitionKeys"))
    except TerminalError as err:
        notify.emit_failure(
            {
                "actor": actor,
                "tableName": req.get("tableName"),
                "space": {"database": space.get("database")},
                "requestId": req.get("requestId"),
            },
            err,
            "validate",
        )
        raise

    bucket = space.get("bucket")
    validated = {
        "actor": actor,
        "space": {
            "kind": space.get("kind"),
            "bucket": bucket,
            "prefix": prefix,
            "database": space.get("database"),
        },
        "tableName": table_name,
        "partitionKeys": partition_keys,
        "location": f"s3://{bucket}/{prefix}",
        "requestId": req.get("requestId"),
    }
    logger.info("validated table %s in %s for %s", table_name, space.get("database"), actor)
    return validated
