"""Renders the recipient CREATE EXTERNAL TABLE from a cloned source definition.

The clone carried the source's columns, partition keys, SerDe, formats and table properties
verbatim; this module re-renders them as a single statement with the location repointed to the
recipient's own prefix. An exact clone, so a projection-partitioned table is queryable
immediately and a flat table selects the copied rows as-is.
"""


def _q(identifier: str) -> str:
    """Backtick-quotes a catalog identifier for DDL.

    Args:
      identifier: A database, table or column name.

    Returns:
      The identifier wrapped in backticks.

    Raises:
      None.
    """
    return f"`{identifier}`"


def _lit(value: str) -> str:
    """Renders a value as a single-quoted DDL literal with backslash escapes.

    Args:
      value: The value to render; coerced with ``str``.

    Returns:
      The escaped value wrapped in single quotes.

    Raises:
      None.
    """
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _column(col: dict) -> str:
    """Renders one column entry, carrying its comment when the source had one.

    Args:
      col: A cloned column dict with a name and type, optionally a comment.

    Returns:
      The quoted name, type and COMMENT clause if present.

    Raises:
      KeyError: If the column has no name or type.
    """
    rendered = f"{_q(col['name'])} {col['type']}"
    if col.get("comment"):
        rendered += f" COMMENT {_lit(col['comment'])}"
    return rendered


def _storage_clause(definition: dict) -> str:
    """Renders the SerDe clause and the explicit input and output format pair.

    The clone always carries the resolved Hive classes — Glue stores them even for tables
    created with the shorthand — so the explicit form reproduces any source format without a
    per-format table.

    Args:
      definition: The cloned definition, carrying its SerDe and format classes.

    Returns:
      The storage fragment of the statement.

    Raises:
      KeyError: If the definition has no input or output format.
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
    """Builds the recipient's CREATE EXTERNAL TABLE IF NOT EXISTS statement.

    The idempotent form plus the conflict guard make a Step Function replay a no-op success.

    Args:
      definition: The cloned source definition.
      database: The recipient's database.
      table_name: The recipient's table name.
      location: The recipient's ``s3://bucket/prefix`` destination.

    Returns:
      The full statement as one line.

    Raises:
      KeyError: If the definition is missing its columns or format classes.
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
