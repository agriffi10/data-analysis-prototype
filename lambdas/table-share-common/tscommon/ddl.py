"""Render the recipient CREATE EXTERNAL TABLE from a cloned definition (SPEC-092).

The clone (tscommon.glue.clone_definition) carried the source's columns, partition
keys, SerDe/formats, and TBLPROPERTIES (projection.* included) verbatim; this module
re-renders them as a single ``CREATE EXTERNAL TABLE IF NOT EXISTS`` statement with
LOCATION repointed to the recipient's shared_tables prefix — an exact clone, so a
projection-partitioned table is queryable immediately (no MSCK) and a flat table
selects the copied rows as-is (docs/architecture.md, Control Planes -> Table Share).
"""


def _q(identifier: str) -> str:
    """Backtick-quote a catalog identifier (db / table / column)."""
    return f"`{identifier}`"


def _lit(value: str) -> str:
    """Single-quoted DDL string literal with backslash/quote escapes."""
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _column(col: dict) -> str:
    rendered = f"{_q(col['name'])} {col['type']}"
    if col.get("comment"):
        rendered += f" COMMENT {_lit(col['comment'])}"
    return rendered


def _storage_clause(definition: dict) -> str:
    """ROW FORMAT SERDE (+ SERDEPROPERTIES) and the explicit INPUT/OUTPUTFORMAT pair.

    The clone always carries the resolved Hive classes (Glue stores them even for
    tables created with STORED AS shorthand), so the explicit form reproduces any
    source format without a per-format table.
    """
    serde = definition.get("serde") or {}
    parts = []
    library = serde.get("serializationLibrary")
    if library:
        clause = f"ROW FORMAT SERDE {_lit(library)}"
        params = serde.get("parameters") or {}
        if params:
            rendered = ", ".join(f"{_lit(k)}={_lit(v)}" for k, v in sorted(params.items()))
            clause += f" WITH SERDEPROPERTIES ({rendered})"
        parts.append(clause)
    parts.append(
        "STORED AS INPUTFORMAT "
        f"{_lit(definition['inputFormat'])} OUTPUTFORMAT {_lit(definition['outputFormat'])}"
    )
    return " ".join(parts)


def render_create_external(
    definition: dict,
    database: str,
    table_name: str,
    location: str,
) -> str:
    """Build the recipient's CREATE EXTERNAL TABLE IF NOT EXISTS statement.

    ``definition`` is the cloned source definition; ``location`` the recipient's
    ``s3://{bucket}/{prefix}`` destination. IF NOT EXISTS + the SPEC-091 conflict
    guard make a Step Function replay a no-op success.
    """
    body = ", ".join(_column(c) for c in definition["columns"])
    stmt = f"CREATE EXTERNAL TABLE IF NOT EXISTS {_q(database)}.{_q(table_name)} ({body})"

    partition_keys = definition.get("partitionKeys") or []
    if partition_keys:
        stmt += f" PARTITIONED BY ({', '.join(_column(k) for k in partition_keys)})"

    stmt += f" {_storage_clause(definition)} LOCATION {_lit(location)}"

    properties = definition.get("tableProperties") or {}
    if properties:
        rendered = ", ".join(f"{_lit(k)}={_lit(v)}" for k, v in sorted(properties.items()))
        stmt += f" TBLPROPERTIES ({rendered})"

    return stmt
