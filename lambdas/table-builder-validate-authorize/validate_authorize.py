"""validate-authorize — the table-builder Step Function's first task.

Parses the SQS record, verifies the caller's Cognito ID token into the trusted
actor, authorizes the target space/DB, and validates the table name, partition keys,
and in-space location. Read-only — no provisioning side effects. A failed check
raises TerminalError with a stable reason, so the state machine's Catch records the
failure and no downstream verb runs.

Both MODES land here (SPEC-143): a create and a refresh are authorized identically —
same actor, same space, same database — and only the partition-key rule differs, since a
refresh declares none. The mode is validated rather than defaulted silently, so an
unknown value fails as a typed terminal here instead of falling through the state
machine's Choice default into a create.

Emits the validated, normalized request the next states consume:
{mode, actor, space, tableName, partitionKeys, location, requestId}.
"""

import logging

from cpcommon import auth, config, errors, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tbcommon import notify
from tbcommon.config import PARTITION_TYPES

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")


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
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"registry load {database}")
        raise


def _validate_mode(mode):
    """Normalize the request mode to a literal; absent means the shipped create path.

    Returns the literal string (never ``None``) so the state machine's Choice always has a
    field to test — a missing ``$.mode`` would fall to its Default, which is create, but
    relying on that would make an unknown mode indistinguishable from an old producer's
    envelope. SPEC-067's envelope carries no ``mode`` at all and must keep routing to
    create, which is why absent is accepted rather than required.
    """
    if mode is None:
        return "create"
    if mode not in ("create", "refresh"):
        raise TerminalError("invalid_mode", f"{mode!r}")
    return mode


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


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("validate-authorize")
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
        mode = _validate_mode(req.get("mode"))
        # Runs identically for both modes: the catalog is not the authorization boundary,
        # so the prefix the producer BELIEVES the table points at is authorized here, and
        # load-table-definition re-checks the location it actually finds.
        prefix = _authorize_space(space, actor)
        table_name = req.get("tableName")
        _validate_table_name(table_name)
        if mode == "refresh":
            # A refresh that accepted keys would be offering to CHANGE them, which the
            # arc forbids: they were user-declared at create time and are recorded
            # nowhere but on the table, so load-table-definition reconstructs them.
            if req.get("partitionKeys"):
                raise TerminalError(
                    "partition_keys_not_refreshable",
                    "a refresh reconstructs the table's existing partition keys",
                )
            partition_keys = []
        else:
            partition_keys = _validate_partition_keys(req.get("partitionKeys"))
    except TerminalError as err:
        notify.emit_failure(
            {
                "actor": actor,
                "tableName": req.get("tableName"),
                "space": {"database": space.get("database")},
                "requestId": req.get("requestId"),
                # From the REQUEST, not the local `mode`, which is unbound when
                # _validate_mode is what raised. Without it every failure this verb
                # notifies reads "Couldn't create table" — including
                # partition_keys_not_refreshable, which only a refresh can reach.
                "mode": req.get("mode"),
            },
            err,
            "validate",
        )
        raise

    bucket = space.get("bucket")
    validated = {
        "mode": mode,
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
    # The DATABASE is the field that matters most on this plane: the silent-create incident was
    # a CREATE that targeted a per-user or per-shared-space database the role could not write
    # to, and "which database did this request aim at" was the first thing nobody could answer.
    observability.info(
        "validated",
        mode=mode,
        actor=actor,
        space=(space or {}).get("name"),
        database=(space or {}).get("database"),
        table=table_name,
        partition_keys=len(partition_keys or []),
        partition_key_names=[k.get("name") for k in (partition_keys or [])],
    )
    return validated
