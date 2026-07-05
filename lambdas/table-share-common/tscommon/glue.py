"""Glue catalog reads for the table-share source (SPEC-090).

get_table fetches the source table; clone_definition validates it is a shareable
shape (base EXTERNAL_TABLE, flat or partition-projection) and captures its
definition verbatim — columns, partition keys, SerDe/formats, carried
TBLPROPERTIES — with LOCATION and catalog identity stripped (the recipient step
sets its own, docs/table-share-architecture.md §4).
"""

from . import clients, config
from .errors import TerminalError, TransientError

# Source-only parameters never carried into the clone: Hive bookkeeping and the
# implicit EXTERNAL flag (the recipient CREATE re-establishes it).
_EXCLUDED_PARAMETERS = frozenset({"transient_lastDdlTime", "EXTERNAL"})


def get_table(database: str, table: str) -> dict:
    """Return the raw Glue Table for ``database.table``; terminal when unreadable."""
    client = clients.glue()
    try:
        return client.get_table(DatabaseName=database, Name=table)["Table"]
    except Exception as exc:  # noqa: BLE001 - mapped by error code below
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code == "EntityNotFoundException":
            raise TerminalError("source_not_found", f"{database}.{table}") from exc
        if code == "AccessDeniedException":
            # LF gates the catalog; the execution role's LF-admin wiring is SPEC-092.
            raise TerminalError("source_not_readable", f"{database}.{table}: {exc}") from exc
        raise TransientError(f"GetTable failed for {database}.{table}: {exc}") from exc


def table_exists(database: str, table: str) -> bool:
    """True iff ``database.table`` exists — the recipient conflict check (SPEC-091).

    A denied read is terminal (the recipient DB should be readable once the role is
    an LF admin, SPEC-092); anything else transient so the SFN retries rather than
    mis-reporting a throttle as a conflict verdict.
    """
    client = clients.glue()
    try:
        client.get_table(DatabaseName=database, Name=table)
        return True
    except Exception as exc:  # noqa: BLE001 - mapped by error code below
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code == "EntityNotFoundException":
            return False
        if code == "AccessDeniedException":
            raise TerminalError("target_not_readable", f"{database}.{table}: {exc}") from exc
        raise TransientError(f"GetTable failed for {database}.{table}: {exc}") from exc


def _parse_location(location: str) -> dict:
    """Resolve the table LOCATION to a single listable prefix in a known bucket.

    The rule (architecture §12, nailed here): it must parse as s3://bucket/prefix,
    the bucket must be one of the two LF-registered data buckets, and the prefix is
    normalized to a trailing slash (an object-level LOCATION simply lists empty and
    fails as source_empty downstream).
    """
    if not isinstance(location, str) or not location.startswith("s3://"):
        raise TerminalError("source_location_unsupported", f"unresolvable LOCATION {location!r}")
    rest = location[len("s3://"):]
    bucket, _, prefix = rest.partition("/")
    if not bucket or not prefix:
        raise TerminalError("source_location_unsupported", f"unresolvable LOCATION {location!r}")
    if bucket not in (config.USER_SPACE_BUCKET, config.SHARED_SPACE_BUCKET):
        raise TerminalError(
            "source_location_unsupported",
            f"LOCATION bucket {bucket!r} is outside the portal's data buckets",
        )
    if not prefix.endswith("/"):
        prefix += "/"
    return {"bucket": bucket, "prefix": prefix}


def clone_definition(table: dict) -> tuple[dict, dict, bool]:
    """Validate the source shape and return (tableDefinition, location, partitioned).

    Rejections are whole-request terminal failures: views (no data files), managed/
    non-external tables, and catalog-partitioned sources (partition keys without
    projection props — the clone would declare partitions with zero registered
    entries and return nothing; copying partition metadata is deferred).
    """
    name = table.get("Name", "?")
    table_type = table.get("TableType", "")
    if table_type == "VIRTUAL_VIEW":
        raise TerminalError("source_is_view", f"{name}: views can't be shared (no data files)")
    if table_type != "EXTERNAL_TABLE":
        raise TerminalError(
            "source_not_external",
            f"{name}: only base external tables can be shared (TableType {table_type or 'unset'!r})",
        )

    sd = table.get("StorageDescriptor") or {}
    location = _parse_location(sd.get("Location"))

    parameters = {
        k: v for k, v in (table.get("Parameters") or {}).items() if k not in _EXCLUDED_PARAMETERS
    }
    partition_keys = table.get("PartitionKeys") or []
    projection = parameters.get("projection.enabled", "").lower() == "true"
    if partition_keys and not projection:
        raise TerminalError(
            "source_catalog_partitioned",
            f"{name}: only flat or partition-projection tables can be shared; "
            "catalog-registered partitions are not supported (v1)",
        )

    def _columns(cols):
        return [
            {"name": c.get("Name"), "type": c.get("Type"), **({"comment": c["Comment"]} if c.get("Comment") else {})}
            for c in cols
        ]

    serde = sd.get("SerdeInfo") or {}
    definition = {
        "columns": _columns(sd.get("Columns") or []),
        "partitionKeys": _columns(partition_keys),
        "serde": {
            "serializationLibrary": serde.get("SerializationLibrary"),
            "parameters": serde.get("Parameters") or {},
        },
        "inputFormat": sd.get("InputFormat"),
        "outputFormat": sd.get("OutputFormat"),
        "tableType": "EXTERNAL_TABLE",
        "tableProperties": parameters,
    }
    return definition, location, bool(partition_keys)
