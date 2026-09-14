"""load-table-definition — the refresh branch's entry task.

The mirror image of check-table-absent: where a create refuses to proceed if the table
exists, a refresh refuses unless it does — and unless it is a table this pipeline can
faithfully rebuild. It answers one question, can this table be rebuilt from its own definition
plus a fresh look at its files, from what Glue reports rather than from any marker. A marker
would be the obvious design and is the wrong one: every table created before this spec lacks
one, and TBLPROPERTIES are user-writable, so it could be trusted neither as a permission nor
as a fact.

Its second job is why the verb exists at all rather than the branch running straight into
inspect-source: the shared spine expects a create's inputs. inspect-source lists the space's
bucket and prefix and treats the location as an output, and infer-schema hands the partition
keys straight to the DDL builder, which requires the declared shape and raises on a
Glue-shaped key. So this verb normalises — rewriting the prefix to the table's own location
and reconstructing the declared keys from the projection properties — and both shared verbs
stay free of any mode branch.

Read-only: one Glue read, no S3, no DDL.

Attributes:
  _SHAPE_REASONS: The shared clone's shape refusals mapped into this path's vocabulary. An
    explicit table rather than a prefix substitution, because the stems differ. Every key is
    asserted against the shared list in the tests, because registration makes the source codes
    globally valid — so an unmapped one would no longer fail loudly, it would reach the user
    as a generic error.
  _DECLARED_TYPES: Projection type as written, mapped back to the declared type it was written
    from. The enum spelling is the one that catches people out: a declared string key is never
    written as "string".
"""

import json
import logging

from cpcommon import clients, config, ddl, errors, events, observability
from cpcommon.errors import TerminalError
from tbcommon import config as tb_config
from tbcommon import glue, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

_SHAPE_REASONS = {
    "source_is_view": "cannot_refresh_view",
    "source_not_external": "cannot_refresh_managed_table",
    "source_catalog_partitioned": "cannot_refresh_catalog_partitioned",
    "source_location_unsupported": "cannot_refresh_location_unsupported",
}

_DECLARED_TYPES = {"integer": "integer", "date": "date", "enum": "string"}


@observability.step("glue-get-table")
def _get_table(database: str, table: str) -> dict:
    """Reads the live table from the Glue catalog.

    **Call bound: exactly once per invocation** — one call in ``_load``, which ``handler`` calls
    once.

    The span shares its name with apply-refresh's pre-write read DELIBERATELY: it is the same
    operation against the same catalog, and the name is what makes a query group across the two
    verbs that perform it. It is not named ``load-table-definition``, which is this verb's own
    root span.

    Args:
      database: The target database.
      table: The target table name.

    Returns:
      The raw Glue table dict.

    Raises:
      TerminalError: ``table_not_found`` when the table does not exist.
      TransientError: On a retryable Glue fault.
      ClientError: Any deterministic Glue fault propagates.
    """
    client = clients.glue()
    try:
        return client.get_table(DatabaseName=database, Name=table)["Table"]
    except client.exceptions.EntityNotFoundException as err:
        raise TerminalError("table_not_found", f"{database}.{table}") from err
    except Exception as err:
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise


def _clone(table: dict) -> tuple[dict, dict, bool]:
    """Projects the live table into a reproducible definition, re-speaking its refusals.

    Args:
      table: The raw Glue table dict.

    Returns:
      The ``(definition, location, partitioned)`` tuple from the shared clone.

    Raises:
      TerminalError: A refresh-path shape reason, or the shared reason unchanged when it is
        not one this path maps.
    """
    try:
        return glue.clone_definition(table)
    except TerminalError as err:
        mapped = _SHAPE_REASONS.get(err.reason)
        if mapped is None:
            raise
        raise TerminalError(mapped, err.detail) from err


def _enforce_definition_cap(definition: dict, database: str, table: str) -> None:
    """Refuses a definition too large to ride the Step Functions state.

    Enforced up front as a whole-request terminal, because breaching the limit it protects raises
    ``States.DataLimitExceeded``, which escapes every Catch here (``States.ALL`` does not match it
    and none names it) — discovered later there is no recorded outcome and no notification at
    all.

    Args:
      definition: The projected table definition.
      database: The target database, for the failure detail.
      table: The target table name, for the failure detail.

    Returns:
      None.

    Raises:
      TerminalError: ``definition_too_large`` when the serialised definition exceeds the cap.
    """
    size = len(json.dumps(definition, separators=(",", ":")).encode())
    if size > tb_config.REFRESH_MAX_DEFINITION_BYTES:
        raise TerminalError(
            "definition_too_large",
            f"{database}.{table} definition is {size} bytes "
            f"(cap {tb_config.REFRESH_MAX_DEFINITION_BYTES})",
        )


def _authorized_root(space: dict, actor: str) -> tuple[str, str]:
    """Resolves the bucket and prefix root the table's own location must sit inside.

    Args:
      space: The request's space, carrying its kind and database.
      actor: The verified username.

    Returns:
      A ``(bucket, prefix root)`` tuple.

    Raises:
      TerminalError: ``forbidden`` on an unknown space kind.
    """
    kind = space.get("kind")
    if kind == "personal":
        return config.USER_SPACE_BUCKET, f"{actor}/"
    if kind == "shared":
        return config.SHARED_SPACE_BUCKET, f"{space.get('database')}/"
    raise TerminalError("forbidden", f"unknown space kind {kind!r}")


def _authorize_location(location: dict, space: dict, actor: str) -> None:
    """Checks the catalog's own location against the space the actor is authorized for.

    This mirrors the validate verb's space check, which already ran against the prefix the
    producer supplied. This runs against the prefix the catalog reports, and the two are not
    the same check: the catalog is not the authorization boundary, and a table whose location
    points into another user's prefix must be refused even though its bucket is one of the
    portal's own.

    Args:
      location: The parsed bucket and prefix from the table's storage descriptor.
      space: The request's space.
      actor: The verified username.

    Returns:
      None.

    Raises:
      TerminalError: ``table_outside_space`` when the bucket differs or the prefix escapes the
        authorized root; ``forbidden`` on an unknown space kind.
    """
    bucket, root = _authorized_root(space, actor)
    if location["bucket"] != bucket:
        raise TerminalError(
            "table_outside_space",
            f"table location bucket {location['bucket']!r} is not the {space.get('kind')} space's",
        )
    if not location["prefix"].startswith(root):
        raise TerminalError(
            "table_outside_space", f"table location escapes {root!r}"
        )


def _declared_key(name: str, properties: dict):
    """Rebuilds one declared partition key from a table's projection properties.

    Reconstruction is mandatory rather than cosmetic: Glue records the partitioning twice, as
    partition keys carrying a name and Hive type, and as these properties, and only the second
    carries what the DDL builder needs. The reconstruction emits the interval-unit spelling the
    renderer reads rather than the one the browser sends, so the round-trip holds.

    An enum key's values are split on commas because Athena itself splits that property on
    commas, so the split is the table's real behaviour — a value containing a comma is already
    two partitions to the engine, and nothing recorded anywhere could say otherwise.

    Args:
      name: The partition key name.
      properties: The table's full properties map.

    Returns:
      The declared key dict.

    Raises:
      TerminalError: ``projection_not_reconstructable`` when the projection type is not one
        this portal declares, a required property is absent, or a range or digit count is
        unreadable.
    """
    written = properties.get(f"projection.{name}.type")
    declared = _DECLARED_TYPES.get(written)
    if declared is None:
        raise TerminalError(
            "projection_not_reconstructable",
            f"{name}: projection type {written!r} is not one this portal declares",
        )

    def _required(suffix):
        """Reads a projection property that must be present.

        Args:
          suffix: The property suffix below ``projection.{name}.``.

        Returns:
          The property value.

        Raises:
          TerminalError: ``projection_not_reconstructable`` when it is absent.
        """
        value = properties.get(f"projection.{name}.{suffix}")
        if value is None:
            raise TerminalError(
                "projection_not_reconstructable", f"{name}: no projection.{name}.{suffix}"
            )
        return value

    def _range(cast):
        """Reads and parses the projection range as a min,max pair.

        Args:
          cast: The callable applied to each bound.

        Returns:
          The two parsed bounds as a list.

        Raises:
          TerminalError: ``projection_not_reconstructable`` when the range is absent, is not a
            pair, or does not parse.
        """
        parts = _required("range").split(",")
        if len(parts) != 2:
            raise TerminalError(
                "projection_not_reconstructable", f"{name}: range is not a min,max pair"
            )
        try:
            return [cast(part) for part in parts]
        except ValueError as err:
            raise TerminalError(
                "projection_not_reconstructable", f"{name}: unreadable range"
            ) from err

    key = {"name": name, "type": declared}
    if declared == "integer":
        key["range"] = _range(int)
        digits = properties.get(f"projection.{name}.digits")
        if digits is not None:
            try:
                key["digits"] = int(digits)
            except ValueError as err:
                raise TerminalError(
                    "projection_not_reconstructable", f"{name}: unreadable digits {digits!r}"
                ) from err
    elif declared == "date":
        key["range"] = _range(str)
        key["format"] = _required("format")
        for suffix, field in (("interval", "interval"), ("interval.unit", "interval.unit")):
            value = properties.get(f"projection.{name}.{suffix}")
            if value is not None:
                key[field] = value
    else:
        key["values"] = _required("values").split(",")
    return key


def _reconstruct_partition_keys(definition: dict) -> list[dict]:
    """Rebuilds every declared key, in the table's own partition-key order.

    Two checks, and neither is sufficient alone. The round-trip re-renders each key through the
    create path's own renderer and compares it to the properties it came from, so a dropped
    property, a rewritten one or an extra projection option all refuse rather than rebuild
    something subtly different. The column-type check exists because the round-trip sees only
    the projection properties, and Athena permits a projection on a wider set of column types
    than this builder writes — an integer projection is legal on a string column, which is
    exactly how a zero-padded partition is declared, and such a table round-trips perfectly and
    would then be rebuilt with a different column type while reporting success.

    A location template is refused outright: it is table-level, outside the namespace the
    per-key round-trip can see, it redirects where partitions read from entirely, and nothing
    in the declared shape can express it, so a rebuild would silently drop it.

    Args:
      definition: The projected table definition, carrying its partition keys and properties.

    Returns:
      The declared keys in granularity order.

    Raises:
      TerminalError: ``projection_not_reconstructable`` on a location template, a mismatched
        column type, a failed round-trip, or any per-key reconstruction failure.
    """
    properties = definition["tableProperties"]
    if definition["partitionKeys"] and "storage.location.template" in properties:
        raise TerminalError(
            "projection_not_reconstructable",
            "storage.location.template cannot be expressed in a declared partition key",
        )

    keys = []
    for glue_key in definition["partitionKeys"]:
        name = glue_key["name"]
        key = _declared_key(name, properties)

        expected_hive = ddl.partition_hive_type(key["type"])
        if glue_key["type"] != expected_hive:
            raise TerminalError(
                "projection_not_reconstructable",
                f"{name}: column is {glue_key['type']!r} but a {key['type']} key rebuilds "
                f"as {expected_hive!r}",
            )

        rendered = ddl.projection_properties(key)
        source = {
            prop: value
            for prop, value in properties.items()
            if prop.startswith(f"projection.{name}.")
        }
        if rendered != source:
            raise TerminalError(
                "projection_not_reconstructable",
                f"{name}: rebuilt properties {sorted(rendered)} do not match {sorted(source)}",
            )
        keys.append(key)
    return keys


@observability.traced("load-table-definition")
@notify.notifies_on_failure("load")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: reads the live table and normalises the refresh state.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The task input, carrying the space, table name and actor.
      context: The Lambda context, unused.

    Returns:
      The event normalised into the shape the shared create verbs expect.

    Raises:
      TerminalError: ``table_not_found``, a shape refusal, ``table_outside_space``,
        ``definition_too_large`` or ``projection_not_reconstructable``. The actor is notified
        before the SFN Catch records it.
      TransientError: On a Glue throttle, passed through un-notified for the SFN Retry.
    """
    return _load(event)


def _load(event: dict) -> dict:
    """Reads the table, authorizes its location, and rewrites the state for the shared spine.

    Authorization runs before any other verdict, so an out-of-space table is told it is out of
    space rather than that it is too large. Column comments ride along because a comment is the
    one piece of column metadata a user writes and inference cannot bring it back. The table's
    properties are deliberately not threaded: the in-place update reads them from the live
    table, so carrying them would be payload weight against the definition cap that nothing
    downstream reads — the capture itself is unchanged and the projection reconstruction still
    uses it.

    Column names are schema and are permitted in the record; column values, sampled rows and
    file contents are not and appear nowhere. A prefix rewrite is recorded because the request's
    prefix and the catalog's disagreeing is normal — the producer only believes, the catalog
    knows — but it is also the first thing to look at when a refresh inspects a folder the user
    did not expect.

    Args:
      event: The task input.

    Returns:
      The event with the space rewritten to the table's own location, plus the existing columns,
      reconstructed partition keys and storage descriptor.

    Raises:
      TerminalError: Any of the refresh refusals above.
      TransientError: On a Glue throttle.
    """
    database = events.require(event, "space", "database")
    table_name = events.require(event, "tableName")
    actor = events.require(event, "actor")
    space = event.get("space") or {}

    live_table = _get_table(database, table_name)
    definition, location, partitioned = _clone(live_table)
    _authorize_location(location, space, actor)
    _enforce_definition_cap(definition, database, table_name)
    partition_keys = _reconstruct_partition_keys(definition)

    columns = [
        {"name": c["name"], "type": c["type"], **({"comment": c["comment"]} if c.get("comment") else {})}
        for c in definition["columns"]
    ]
    serde = definition["serde"]

    out = dict(event)
    out["observedUpdateTime"] = glue.update_time(live_table)
    out["space"] = {**space, "bucket": location["bucket"], "prefix": location["prefix"]}
    out["location"] = f"s3://{location['bucket']}/{location['prefix']}"
    out["existingColumns"] = columns
    out["partitionKeys"] = partition_keys
    out["storage"] = {
        "serializationLibrary": serde["serializationLibrary"],
        "parameters": serde["parameters"],
        "inputFormat": definition["inputFormat"],
        "outputFormat": definition["outputFormat"],
    }

    logger.info("loaded %s.%s: %d columns, partitioned=%s", database, table_name, len(columns), partitioned)
    observability.info(
        "loaded table definition",
        mode=event.get("mode"),
        database=database,
        table=table_name,
        location=out["location"],
        column_count=len(columns),
        partition_key_count=len(partition_keys),
        partition_key_names=[k["name"] for k in partition_keys],
        prefix_rewritten=space.get("prefix") != location["prefix"],
    )
    return out
