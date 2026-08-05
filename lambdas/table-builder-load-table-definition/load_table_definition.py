"""load-table-definition — the refresh branch's entry task (SPEC-143).

The mirror image of check-table-absent: where a create refuses to proceed if the table
exists, a refresh refuses to proceed unless it does — and unless it is a table this
pipeline can faithfully rebuild. It answers one question, *can this table be rebuilt from
its own definition plus a fresh look at its files?*, from what Glue reports rather than
from any marker. A marker would be the obvious design and is the wrong one: every table
created before this spec lacks it, and TBLPROPERTIES are user-writable through ALTER
TABLE, so it could be trusted neither as a permission nor as a fact.

Its second job is why this verb exists at all rather than the branch running straight into
inspect-source: THE SHARED SPINE EXPECTS A CREATE'S INPUTS. inspect-source lists
space.bucket + space.prefix and treats location as an output; infer-schema hands
partitionKeys straight to build_create_table_ddl, which requires the SPEC-069 DECLARED
shape and raises a bare ValueError on a Glue-shaped key. So this verb normalises — it
rewrites the prefix to the table's own location and reconstructs the declared keys from the
projection properties — and both shared verbs stay free of any mode branch.

Read-only: one Glue GetTable, no S3, no DDL.
"""

import json
import logging

from cpcommon import clients, config, ddl, errors, events, glue, observability
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")

#: clone_definition's shape refusals -> this path's vocabulary. An explicit table, not a
#: prefix substitution: the stems differ, so no string surgery produces both sets. Every
#: key is asserted against cpcommon.glue's own list in the tests, because registration
#: makes the source codes globally VALID — so an unmapped one would no longer fail loudly,
#: it would reach the user as the generic unexpected_error.
_SHAPE_REASONS = {
    "source_is_view": "cannot_refresh_view",
    "source_not_external": "cannot_refresh_managed_table",
    "source_catalog_partitioned": "cannot_refresh_catalog_partitioned",
    "source_location_unsupported": "cannot_refresh_location_unsupported",
}

#: projection.{name}.type as WRITTEN -> the declared type it was written from. `enum` is
#: the one that catches people out: a declared `string` key is never written as "string".
_DECLARED_TYPES = {"integer": "integer", "date": "date", "enum": "string"}


def _get_table(database: str, table: str) -> dict:
    """Return the raw Glue Table; absent is terminal, a throttle is retryable."""
    client = clients.glue()
    try:
        return client.get_table(DatabaseName=database, Name=table)["Table"]
    except client.exceptions.EntityNotFoundException as err:
        raise TerminalError("table_not_found", f"{database}.{table}") from err
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise


def _clone(table: dict) -> tuple[dict, dict, bool]:
    """clone_definition, with its refusals re-spoken in the refresh path's vocabulary."""
    try:
        return glue.clone_definition(table)
    except TerminalError as err:
        mapped = _SHAPE_REASONS.get(err.reason)
        if mapped is None:
            raise
        raise TerminalError(mapped, err.detail) from err


def _enforce_definition_cap(definition: dict, database: str, table: str) -> None:
    """Refuse a definition too large to ride the Step Functions state.

    Up front, as a whole-request terminal, because the limit it protects
    (States.DataLimitExceeded) is raised OUTSIDE every Catch — discovered later there is no
    recorded outcome and no notification at all.
    """
    size = len(json.dumps(definition, separators=(",", ":")).encode())
    if size > config.REFRESH_MAX_DEFINITION_BYTES:
        raise TerminalError(
            "definition_too_large",
            f"{database}.{table} definition is {size} bytes "
            f"(cap {config.REFRESH_MAX_DEFINITION_BYTES})",
        )


def _authorized_root(space: dict, actor: str) -> tuple[str, str]:
    """The (bucket, prefix root) the table's own location must sit inside.

    Mirrors validate_authorize._authorize_space, which already ran against the prefix the
    PRODUCER supplied. This runs against the prefix the CATALOG reports, and the two are
    not the same check: the catalog is not the authorization boundary, and a table whose
    LOCATION points into another user's prefix must be refused even though its bucket is
    one of the portal's own.
    """
    kind = space.get("kind")
    if kind == "personal":
        return config.USER_SPACE_BUCKET, f"{actor}/"
    if kind == "shared":
        return config.SHARED_SPACE_BUCKET, f"{space.get('database')}/"
    raise TerminalError("forbidden", f"unknown space kind {kind!r}")


def _authorize_location(location: dict, space: dict, actor: str) -> None:
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
    """Rebuild one SPEC-069 declared key from a table's projection.* properties.

    Reconstruction is mandatory rather than cosmetic: Glue records the partitioning twice,
    as PartitionKeys (name + Hive type) and as these properties, and only the second
    carries what build_create_table_ddl needs.

    NOTE the key name ``interval.unit``: build_create_table_ddl reads ``key["interval.unit"]``
    while the browser sends ``intervalUnit`` (tableBuild.types.ts). The reconstruction emits
    what the RENDERER reads, so the round-trip below holds; the mismatch is pre-existing and
    named here so it is fixed deliberately rather than by accident from this side.
    """
    written = properties.get(f"projection.{name}.type")
    declared = _DECLARED_TYPES.get(written)
    if declared is None:
        raise TerminalError(
            "projection_not_reconstructable",
            f"{name}: projection type {written!r} is not one this portal declares",
        )

    def _required(suffix):
        value = properties.get(f"projection.{name}.{suffix}")
        if value is None:
            raise TerminalError(
                "projection_not_reconstructable", f"{name}: no projection.{name}.{suffix}"
            )
        return value

    def _range(cast):
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
        # Athena itself splits this property on commas, so the split IS the table's real
        # behaviour — a value containing a comma is already two partitions to the engine,
        # and nothing recorded anywhere could tell us otherwise.
        key["values"] = _required("values").split(",")
    return key


def _reconstruct_partition_keys(definition: dict) -> list[dict]:
    """Every declared key, in the table's own PartitionKeys order (= granularity order).

    Two checks, and NEITHER is sufficient alone.

    The round-trip: each key is re-rendered through the create path's own renderer and
    compared to the properties it came from, so a dropped property, a rewritten one (a
    zero-padded bound, an interval this shape cannot express) or an extra ``projection.*``
    option all refuse rather than rebuild something subtly different.

    The column type: the round-trip sees only ``projection.*``, and Athena permits a
    projection on a WIDER set of column types than this builder writes — an ``integer``
    projection is legal on a ``string`` column, which is exactly how you would declare a
    zero-padded partition. Such a table round-trips perfectly and would then be rebuilt
    with ``int``, changing the column's type while reporting success.
    """
    properties = definition["tableProperties"]
    # Table-level, outside the projection.* namespace the per-key round-trip can see, and
    # it redirects where partitions read from entirely. Nothing in the declared shape can
    # express it, so a rebuild would silently drop it.
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


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("load-table-definition")
@notify.notifies_on_failure("load")
def handler(event: dict, context) -> dict:
    """SFN entry point: read the live table, decide refreshability, normalise the state.

    Delegates to ``_load`` and notifies the actor on a terminal failure (best-effort)
    before the SFN ``Catch`` records it. A Glue throttle maps to ``TransientError`` and
    passes through un-notified for the SFN ``Retry``.
    """
    return _load(event)


def _load(event: dict) -> dict:
    database = events.require(event, "space", "database")
    table_name = events.require(event, "tableName")
    actor = events.require(event, "actor")
    space = event.get("space") or {}

    definition, location, partitioned = _clone(_get_table(database, table_name))
    # Authorization before any other verdict, so an out-of-space table is told it is out of
    # space rather than that it is too large.
    _authorize_location(location, space, actor)
    _enforce_definition_cap(definition, database, table_name)
    partition_keys = _reconstruct_partition_keys(definition)

    # The COMMENT rides along: it is the one piece of column metadata a user writes, and a
    # refresh rebuilds by DROP + CREATE, so anything not carried here is destroyed
    # (SPEC-144). Types and names come back from inference; comments cannot.
    columns = [
        {"name": c["name"], "type": c["type"], **({"comment": c["comment"]} if c.get("comment") else {})}
        for c in definition["columns"]
    ]
    serde = definition["serde"]

    out = dict(event)
    # THE LOCATION COMES FROM THE TABLE, not from the request. Rewriting space here is what
    # lets inspect-source — which lists space.bucket + space.prefix — run unchanged.
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
    # `tableProperties` is NOT threaded (SPEC-149). It existed for SPEC-144's rebuild, which
    # carried the captured properties into a regenerated CREATE; the in-place update reads
    # them from the LIVE table instead, so threading them would be payload weight against the
    # definition cap that nothing downstream reads. The capture itself is unchanged — the
    # projection reconstruction above still uses it.

    logger.info("loaded %s.%s: %d columns, partitioned=%s", database, table_name, len(columns), partitioned)
    # Column NAMES are schema and are permitted; column VALUES, sampled rows and file
    # contents are not and appear nowhere (the field rule, decisions.md). `request_id` and
    # `verb` ride as baggage from @traced rather than as fields here.
    observability.info(
        "loaded table definition",
        mode=event.get("mode"),
        database=database,
        table=table_name,
        location=out["location"],
        column_count=len(columns),
        partition_key_count=len(partition_keys),
        partition_key_names=[k["name"] for k in partition_keys],
        # The request's prefix and the catalog's disagreeing is NORMAL (the producer only
        # believes; the catalog knows) — but it is also the first thing to look at when a
        # refresh inspects a folder the user did not expect.
        prefix_rewritten=space.get("prefix") != location["prefix"],
    )
    return out
