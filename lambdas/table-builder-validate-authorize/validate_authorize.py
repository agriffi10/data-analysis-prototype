"""validate-authorize — the table-builder Step Function's first task.

Parses the SQS record, reads the trusted actor out of the API's identity block,
authorizes the target space and database, and validates the table name, partition keys and
in-space location. Read-only, with no provisioning side effects. A failed check raises a
terminal error with a stable reason, so the state machine's Catch records the failure and no
downstream verb runs.

Both modes land here: a create and a refresh are authorized identically — same actor, same
space, same database — and only the partition-key rule differs, since a refresh declares none.
The mode is validated rather than defaulted silently, so an unknown value fails as a typed
terminal here instead of falling through the state machine's default into a create.

The service name is the control plane, not the function, so one build's five invocations stay
one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import actor as cpactor
from cpcommon import config, errors, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from tbcommon import notify
from tbcommon.config import PARTITION_TYPES

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


def _load_registry(database: str):
    """Loads the shared-space registry record, mapping a throttle to a transient error.

    The shared loader catches only a missing key, so a throttle on the underlying read
    propagates as a bare ClientError, which this verb's Retry list does not name and would
    permanently fail the request. Mapped here at the verb rather than in the shared loader,
    which the shared-space verbs also use and whose state machine does not retry transients.

    Args:
      database: The shared space's database name.

    Returns:
      The registry record, or None when the space is not registered.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any deterministic fault propagates.
    """
    try:
        return reg.load(database)
    except Exception as err:
        errors.raise_if_transient(err, f"registry load {database}")
        raise


def _validate_mode(mode):
    """Normalises the request mode to a literal; absent means the shipped create path.

    Always returns a literal so the state machine's choice has a field to test. A missing mode
    would fall to its default, which is create, but relying on that would make an unknown mode
    indistinguishable from an old producer's envelope — and the original envelope carries no
    mode at all and must keep routing to create, which is why absent is accepted rather than
    required.

    Args:
      mode: The request's mode, or None.

    Returns:
      ``create`` or ``refresh``.

    Raises:
      TerminalError: ``invalid_mode`` on any other value.
    """
    if mode is None:
        return "create"
    if mode not in ("create", "refresh"):
        raise TerminalError("invalid_mode", f"{mode!r}")
    return mode


def _validate_allow_removals(flag, mode):
    """Normalises the removal opt-in to a boolean; it is meaningful only on a refresh.

    Rejected rather than ignored when it rides a create: a request that asks for something the
    mode cannot do is a producer bug, and silently dropping the flag would let a future caller
    believe removals were opted into when nothing read the field.

    Args:
      flag: The request's opt-in value, or None.
      mode: The validated mode.

    Returns:
      The opt-in as a boolean.

    Raises:
      TerminalError: ``removals_flag_not_applicable`` when the value is not a boolean, or is
        set on a create.
    """
    if flag is None:
        return False
    if not isinstance(flag, bool):
        raise TerminalError("removals_flag_not_applicable", f"allowRemovals must be a boolean, got {flag!r}")
    if flag and mode != "refresh":
        raise TerminalError("removals_flag_not_applicable", f"allowRemovals is not valid for mode {mode!r}")
    return flag


def _normalize_prefix(prefix):
    """Trims a prefix, drops a leading slash and ensures a single trailing one.

    Args:
      prefix: The raw prefix, or None.

    Returns:
      The normalised prefix, which is "" when there was none.

    Raises:
      None.
    """
    p = (prefix or "").strip().lstrip("/")
    if p and not p.endswith("/"):
        p += "/"
    return p


def _validate_table_name(name):
    """Checks the requested table name against the catalog-safe identifier rule.

    Args:
      name: The requested table name.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_table_name`` when it is not a catalog-safe identifier.
    """
    if not isinstance(name, str) or not config.CATALOG_IDENTIFIER_RE.match(name):
        raise TerminalError("invalid_table_name", f"{name!r}")


def _validate_partition_keys(keys):
    """Validates the user-declared partition keys, in full, before any renderer sees them.

    Every refusal is one reason code and names the offending key. Unvalidated, these reached
    the renderer as a bare KeyError or TypeError inside a later verb, which the user was told
    about as "something went wrong" — a message that cannot be acted on for a request they
    could simply have fixed. Booleans are excluded from the numeric bounds explicitly rather
    than by accident, since a boolean is an int in Python and would render as a capitalised
    word into a projection range.

    Args:
      keys: The declared partition keys. An empty list or None means a flat table.

    Returns:
      The keys unchanged.

    Raises:
      TerminalError: ``invalid_partition_keys`` for a non-list, a non-object key, an invalid or
        duplicate name, an unknown type, a malformed range, a date key with no format, an empty
        or non-string enum value list, or a non-integer digit count.
    """
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
            for bound in rng:
                if isinstance(bound, bool) or not isinstance(bound, (int, str)):
                    raise TerminalError(
                        "invalid_partition_keys", f"{name}: range bounds must be numbers or strings"
                    )
            if ptype == "date":
                fmt = key.get("format")
                if not isinstance(fmt, str) or not fmt.strip():
                    raise TerminalError(
                        "invalid_partition_keys", f"{name}: date keys need a non-empty format"
                    )
        else:
            values = key.get("values")
            if not (isinstance(values, list) and len(values) >= 1):
                raise TerminalError("invalid_partition_keys", f"{name}: values must be a non-empty list")
            if not all(isinstance(v, str) for v in values):
                raise TerminalError(
                    "invalid_partition_keys", f"{name}: every value must be a string"
                )
        digits = key.get("digits")
        if digits is not None and (isinstance(digits, bool) or not isinstance(digits, int)):
            raise TerminalError("invalid_partition_keys", f"{name}: digits must be an integer")
    return keys


def _authorize_space(space, actor):
    """Authorizes the actor for the target space and returns its normalised prefix and root.

    A personal space must be the actor's own database in the user-space bucket, with the
    location inside their prefix. A shared space must list the actor as an active member, live
    in the shared-space bucket, and have the location inside the space's own prefix.

    The root is returned rather than recomputed by the caller because it is the string this
    function already tested the prefix against; a second derivation of "where this space
    starts" would be free to disagree with the one that authorized the request.

    Args:
      space: The request's space dict.
      actor: The verified username.

    Returns:
      A ``(prefix, root)`` pair: the normalised location prefix, and the space's own root.

    Raises:
      TerminalError: ``forbidden`` when the space is missing, its kind is unknown, the actor is
        not entitled to it, the bucket is wrong, or the location escapes it.
      TransientError: On a retryable fault loading the registry.
    """
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
        root = f"{actor}/"
        if not prefix.startswith(root):
            raise TerminalError("forbidden", "location escapes the personal space")
    elif kind == "shared":
        record = _load_registry(database)
        if not reg.is_active_member(record, actor):
            raise TerminalError("forbidden", f"{actor!r} is not an active member of {database!r}")
        if bucket != config.SHARED_SPACE_BUCKET:
            raise TerminalError("forbidden", "shared space must be the shared-space bucket")
        root = f"{database}/"
        if not prefix.startswith(root):
            raise TerminalError("forbidden", "location escapes the shared space")
    else:
        raise TerminalError("forbidden", f"unknown space kind {kind!r}")
    return prefix, root


def _validate_not_space_root(prefix, root, mode):
    """Refuses a create whose location is the space root itself.

    A table's ``LOCATION`` is read recursively, so a table built at the root covers every
    app-managed folder the space keeps there — ``athenaresults/``, ``saved_queries/``,
    ``user_settings/``, ``shared_files/``, ``shared_tables/``, ``archive/`` — as well as the
    user's own data. It does not fail; it succeeds, and every later read of that table returns
    the portal's own bookkeeping mixed into the answer. Refused here, where the request is
    still a request.

    Creates only. A refresh re-derives an existing table's columns, so refusing one would
    strand any root table already in a catalog with no way to repair it, and a refresh reads
    the location the table already has rather than choosing a new one.

    Args:
      prefix: The normalised location prefix.
      root: The space's own root prefix.
      mode: The validated request mode.

    Returns:
      None.

    Raises:
      TerminalError: ``location_is_space_root`` when a create names the root.
    """
    if mode == "create" and prefix == root:
        raise TerminalError(
            "location_is_space_root",
            "a table cannot be built from the top of a space, which also holds query results, "
            "saved queries and shared files",
        )


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, attributes, authorizes and assembles the build state.

    A thin shim; the orchestration lives below so it is testable without a Lambda context.
    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated, normalised request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the actor is bound, or any validation reason
        afterwards.
      TransientError: On a retryable fault loading the registry.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Reads the trusted actor, authorizes the space, validates the request and shapes the state.

    The actor comes from the ``identity`` block the API stamped, never from the body, and the
    read sits outside the notifying try deliberately: an unauthorized failure raises before the
    actor is known, so there is no recipient to notify and the SFN still records it. From there on a
    terminal validation failure notifies the actor best-effort before the Catch records it, and
    that notification reads its mode from the request rather than the local variable, which is
    unbound when the mode check is what raised — without it every failure this verb notifies
    would read as a create failure, including one only a refresh can reach.

    The space authorization runs identically for both modes: the catalog is not the
    authorization boundary, so the prefix the producer believes the table points at is
    authorized here, and the refresh entry verb re-checks the location it actually finds.

    The database is the field that matters most in the record: this plane's silent-create
    incident was a create targeting a database the role could not write to, and which database
    the request aimed at was the first thing nobody could answer.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      The validated request: mode, removal opt-in, actor, space, table name, partition keys,
      location and request id.

    Raises:
      TerminalError: ``unauthorized`` for an unusable identity block, ``invalid_mode``,
        ``removals_flag_not_applicable``, ``forbidden``, ``location_is_space_root``,
        ``invalid_table_name``, ``partition_keys_not_refreshable`` or
        ``invalid_partition_keys``.
      TransientError: On a retryable fault loading the registry.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")
    space = req.get("space") or {}

    who = cpactor.trusted_actor(req)
    observability.stamp(
        actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
    )
    actor = who.username

    try:
        mode = _validate_mode(req.get("mode"))
        allow_removals = _validate_allow_removals(req.get("allowRemovals"), mode)
        prefix, root = _authorize_space(space, actor)
        _validate_not_space_root(prefix, root, mode)
        table_name = req.get("tableName")
        _validate_table_name(table_name)
        if mode == "refresh":
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
                "mode": req.get("mode"),
            },
            err,
            "validate",
        )
        raise

    bucket = space.get("bucket")
    validated = {
        "mode": mode,
        "allowRemovals": allow_removals,
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
    observability.info(
        "validated",
        mode=mode,
        allow_removals=allow_removals,
        actor=actor,
        space=(space or {}).get("name"),
        database=(space or {}).get("database"),
        table=table_name,
        partition_keys=len(partition_keys or []),
        partition_key_names=[k.get("name") for k in (partition_keys or [])],
    )
    return validated
