"""Pure CREATE EXTERNAL TABLE DDL generation shared by the control-plane arcs.

Identifier quoting, the column body, ``PARTITIONED BY``, the Athena partition-projection
``TBLPROPERTIES`` and the statement assembly are shared. The storage clause is not: the
table-builder and data-quality arcs deliberately choose different SerDes, so ``storage`` is
injectable and a domain's SerDe choice stays in that domain's layer. See
``docs/lambda-rationale.md``.

Attributes:
  CSV_OPEN_SERDE: OpenCSVSerde storage clause. Its ``escapeChar`` is a single backslash,
    which is four characters in this source and two in the emitted DDL.
  JSON_OPENX_SERDE: OpenX JSON SerDe storage clause, the table-builder's shipped choice.
  PARQUET_STORED: Parquet storage clause.
  CSV_SKIP_HEADER: Header-skip property. A TBLPROPERTY rather than part of the SerDe
    clause, because the data-quality raw-line table uses a CSV-ish SerDe and must not skip
    the header — it counts every physical line.
  PORTAL_MANAGED: The "this portal created this table" marker. Not the refresh eligibility
    test and it must never become one: tables predating the marker lack it and TBLPROPERTIES are
    user-writable through ALTER TABLE. Note ``portal.managed`` (this, a table property,
    dotted) is not ``portal-managed`` (the Lake Formation tag on databases, hyphenated).
  SERDE_FORMATS: SerDe library to the format key this repo's inference reports. Both JSON
    SerDes are listed because the two arcs disagree on which to write and a refresh may
    meet either.
  _PARTITION_HIVE: Declared partition type to the Hive column type ``PARTITIONED BY`` renders.
    A type absent from here reaches this map before any validation raises, so an unknown
    declared type surfaces as a ``KeyError`` — see ``build_create_table_ddl``.
  _DEFAULT_STORAGE: The table-builder defaults, unchanged since the consolidation.
    ``build_create_table_ddl`` falls back to these when no storage is passed, which is what
    keeps that arc's golden-string tests meaningful across the move.
"""

from typing import NamedTuple

_PARTITION_HIVE = {"integer": "int", "date": "date", "string": "string"}

CSV_OPEN_SERDE = (
    "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
    "WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') "
    "STORED AS TEXTFILE"
)
JSON_OPENX_SERDE = "ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe' STORED AS TEXTFILE"
PARQUET_STORED = "STORED AS PARQUET"

CSV_SKIP_HEADER = ("skip.header.line.count", "1")

PORTAL_MANAGED = ("portal.managed", "true")


class Storage(NamedTuple):
    """A format's storage clause plus the TBLPROPERTIES that clause requires.

    Attributes:
      clause: The ``ROW FORMAT …``/``STORED AS …`` fragment, inserted verbatim.
      tblproperties: Ordered (key, value) pairs emitted BEFORE the projection
          properties, so a caller's format props and Athena's projection props keep a
          stable, testable order.
    """

    clause: str
    tblproperties: tuple[tuple[str, str], ...] = ()


_DEFAULT_STORAGE = {
    "parquet": Storage(PARQUET_STORED),
    "csv": Storage(CSV_OPEN_SERDE, (CSV_SKIP_HEADER,)),
    "json": Storage(JSON_OPENX_SERDE),
}


def mark_managed(parameters: dict) -> dict:
    """Asserts the portal's creation marker on a copy of a table's Glue parameters.

    Exists so the marker keeps exactly two homes. A test scans the whole Lambda tree to
    confirm no verb names the property, because the moment a verb can name it, it can
    branch on it — and TBLPROPERTIES are user-writable. ``apply-refresh`` writes Glue
    parameters directly rather than DDL, so it needs the marker without the constant.

    Args:
      parameters: A table's existing Glue ``Parameters``, often the live table's.

    Returns:
      A new dict with the marker asserted; the argument is never mutated.

    Raises:
      None.
    """
    return {**parameters, PORTAL_MANAGED[0]: PORTAL_MANAGED[1]}


def quote(identifier: str) -> str:
    """Backtick-quotes a catalog identifier for a DDL statement, never for a query.

    Athena parses CREATE/DROP with Hive syntax, where backticks are the identifier quote,
    but parses SELECT with Trino syntax, where they are not. Use ``quote_dml`` inside a
    query.

    Args:
      identifier: A database, table or column name.

    Returns:
      The identifier wrapped in backticks.

    Raises:
      None.
    """
    return f"`{identifier}`"


def literal(value: str) -> str:
    """Renders a value as a single-quoted DDL string literal with backslash escapes.

    Applies to every literal in a statement — column comments, TBLPROPERTIES keys and
    values, and LOCATION. Free text a user wrote may contain an apostrophe, which would
    otherwise end the literal and turn the rest of the statement into syntax.

    This is the Hive/DDL escaper. Two others exist and must never be confused with it:
    ``dqcommon.sql._literal_dml`` doubles the quote for Trino, and ``tscommon.ddl._lit`` is a
    byte-identical twin of this one serving table-share's own renderer.

    Args:
      value: The value to render; coerced with ``str``.

    Returns:
      The escaped value wrapped in single quotes.

    Raises:
      None.
    """
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def quote_dml(identifier: str) -> str:
    """Double-quotes a catalog identifier for a DML statement, never for DDL.

    Athena's two dialects fail at query time rather than build time: DDL is Hive
    (backticks), DML is Trino (double quotes), and backticks in a DML query are an error. A
    query built with the DDL quoter looks correct in a diff and in a golden-string test,
    then fails against the engine after the scan has been paid for. An embedded double
    quote is escaped by doubling.

    Args:
      identifier: A database, table or column name.

    Returns:
      The identifier wrapped in double quotes, inner quotes doubled.

    Raises:
      None.
    """
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def default_storage(fmt: str) -> Storage:
    """Returns the table-builder's default storage clause for a format key.

    Args:
      fmt: One of ``parquet``, ``csv`` or ``json``.

    Returns:
      The ``Storage`` for that format.

    Raises:
      ValueError: On an unknown format — a typo must not silently produce a table with no
        storage clause.
    """
    try:
        return _DEFAULT_STORAGE[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}") from None


def _column(column: dict) -> str:
    """Renders one column body entry, carrying its COMMENT when it has one.

    A comment is the one piece of column metadata a user writes, and a rebuild is where it
    would silently disappear. The create path never sets one, so this renders identically
    for every table this repo has created so far.

    Args:
      column: A column dict with ``name`` and ``type``, optionally ``comment``.

    Returns:
      The quoted name, type, and COMMENT clause if present.

    Raises:
      KeyError: If ``name`` or ``type`` is absent.
    """
    rendered = f"{quote(column['name'])} {column['type']}"
    if column.get("comment"):
        rendered += f" COMMENT {literal(column['comment'])}"
    return rendered


def _projection_props(key):
    """Renders the Athena projection.* TBLPROPERTIES for one declared partition key.

    Both the browser's ``intervalUnit`` and the catalog's ``interval.unit`` spellings are
    accepted, because the renderer only ever read the latter while the browser's type
    declares the former. Read with ``or`` rather than a ``get`` default: an explicit
    ``None`` alongside a real value would otherwise be returned and silently drop the
    property.

    Args:
      key: A declared partition key — ``name`` and ``type``, plus ``range`` and optional
        ``digits`` for integer, ``range``/``format``/optional interval for date, or
        ``values`` for string.

    Returns:
      An ordered list of (property name, value) pairs.

    Raises:
      ValueError: On an unknown partition type, or a string key whose enum values are not
        all strings. Asserted rather than left to ``",".join``, whose bare TypeError
        surfaces to the user as "something went wrong" instead of a validation message.
      KeyError: If a type-specific field the projection requires is absent.
    """
    name = key["name"]
    ptype = key["type"]
    props = []
    if ptype == "integer":
        lo, hi = key["range"]
        props.append((f"projection.{name}.type", "integer"))
        props.append((f"projection.{name}.range", f"{lo},{hi}"))
        if key.get("digits") is not None:
            props.append((f"projection.{name}.digits", str(key["digits"])))
    elif ptype == "date":
        lo, hi = key["range"]
        props.append((f"projection.{name}.type", "date"))
        props.append((f"projection.{name}.range", f"{lo},{hi}"))
        props.append((f"projection.{name}.format", key["format"]))
        if key.get("interval") is not None:
            props.append((f"projection.{name}.interval", str(key["interval"])))
        unit = key.get("interval.unit") or key.get("intervalUnit")
        if unit is not None:
            props.append((f"projection.{name}.interval.unit", str(unit)))
    elif ptype == "string":
        values = key["values"]
        if not all(isinstance(v, str) for v in values):
            raise ValueError(f"partition key {name!r}: every enum value must be a string")
        props.append((f"projection.{name}.type", "enum"))
        props.append((f"projection.{name}.values", ",".join(values)))
    else:
        raise ValueError(f"unknown partition type {ptype!r} for {name!r}")
    return props


def partition_hive_type(declared_type: str) -> str | None:
    """Returns the Hive column type PARTITIONED BY renders for a declared partition type.

    The refresh path needs the other direction: Athena allows a projection on a wider set
    of column types than this builder writes — an integer projection is legal on a string
    column, which is exactly how zero-padded partitions are declared. Such a table
    reconstructs cleanly from its projection properties alone and would then be rebuilt
    with a different column type, silently, so the refresh path compares against this.

    Args:
      declared_type: One of ``integer``, ``date`` or ``string``.

    Returns:
      The Hive type, or None if the declared type is not one this builder writes.

    Raises:
      None.
    """
    return _PARTITION_HIVE.get(declared_type)


def projection_properties(key) -> dict:
    """Returns the projection.* properties one declared partition key renders to, as a dict.

    The public door onto the renderer for the refresh path, which goes the other way —
    reading a live table's projection properties back into a declared key. That
    reconstruction is only trustworthy if it re-renders to exactly the properties it read,
    and it can only be checked against the renderer the create path actually uses. A second
    copy of this mapping in the refresh verb is the one thing that would make the check
    meaningless.

    Args:
      key: A declared partition key, as for ``_projection_props``.

    Returns:
      The rendered properties keyed by property name.

    Raises:
      ValueError: On an unknown partition type or a non-string enum value.
      KeyError: If a type-specific field the projection requires is absent.
    """
    return dict(_projection_props(key))


SERDE_FORMATS = {
    "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe": "parquet",
    "org.apache.hadoop.hive.serde2.OpenCSVSerde": "csv",
    "org.openx.data.jsonserde.JsonSerDe": "json",
    "org.apache.hive.hcatalog.data.JsonSerDe": "json",
}


def format_of_serde(library) -> str | None:
    """Maps a SerDe library name to the format key this repo's inference reports.

    The refresh path compares the two: a folder that now holds JSON under a table declared
    with OpenCSVSerde has changed in a way re-deriving columns cannot fix.

    Args:
      library: The SerDe library name from a live table's storage descriptor.

    Returns:
      The format key, or None if it is not a SerDe this repo writes.

    Raises:
      None.
    """
    return SERDE_FORMATS.get(library)


def _tblproperties(storage, partition_keys, *, mark):
    """Assembles the ordered TBLPROPERTIES: marker, the storage's own props, projection.

    The marker leads; the storage-then-projection order the golden strings pin is unchanged
    either way, so leading with identity is a reading choice. Duplicate keys are dropped,
    first occurrence winning — defensive rather than load-bearing now that nothing merges
    captured properties in, but a key emitted twice inside one ``TBLPROPERTIES (…)`` is at
    best redundant and at worst rejected.

    Args:
      storage: The resolved ``Storage`` whose own properties are included.
      partition_keys: Declared partition keys; empty means no projection properties.
      mark: Whether to lead with the ``portal.managed`` marker.

    Returns:
      An ordered, de-duplicated list of (key, value) pairs.

    Raises:
      ValueError: On an unknown partition type or a non-string enum value.
    """
    props = [PORTAL_MANAGED] if mark else []
    props += list(storage.tblproperties)
    if partition_keys:
        props.append(("projection.enabled", "true"))
        for key in partition_keys:
            props.extend(_projection_props(key))

    seen, deduped = set(), []
    for key, value in props:
        if key in seen:
            continue
        seen.add(key)
        deduped.append((key, value))
    return deduped


def build_create_table_ddl(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str,
    location: str,
    storage: Storage | None = None,
    mark: bool = True,
) -> str:
    """Builds a complete CREATE EXTERNAL TABLE IF NOT EXISTS statement as one line.

    A data column colliding with a partition-key name is dropped from the body — the
    partition key wins — so the DDL stays valid. The LOCATION and every TBLPROPERTY go
    through ``literal``: an S3 key may contain an apostrophe, and a partition enum value
    could otherwise inject a property that switched partition projection off.

    Args:
      database: Target Glue/Athena database.
      table_name: Target table name (already validated by the caller).
      columns: Ordered [{name, type}] data columns, Hive types.
      partition_keys: Declared partition keys ([] = flat), each
          {name, type, …} per ``_projection_props``.
      fmt: Format key used only to pick the DEFAULT storage; ignored when ``storage``
          is supplied.
      location: ``s3://…/`` folder the external table reads.
      storage: Explicit storage clause + its properties. Omit for the table-builder
          defaults; supply one when the domain's SerDe choice differs.
      mark: Whether to emit the ``portal.managed`` marker. Default on, and a separate
          argument from ``storage`` deliberately — inferring it from ``storage is None``
          would strip the marker from every table a refresh touches, since the refresh
          path supplies a Storage rebuilt from the live table. Pass ``False`` for a table
          that is not a durable user table, such as data-quality's temporary tables.

    Returns:
      The full statement as one line.

    Raises:
      ValueError: On an unknown format when ``storage`` is omitted, or a non-string partition
          enum value.
      KeyError: If a column or partition key is missing a required field, or a partition key
          declares a type this builder does not render. That last case reaches the Hive-type
          lookup before it ever reaches ``_projection_props``' ``ValueError``, so an unknown
          partition type surfaces here as a ``KeyError`` — callers validate the declared type
          up front rather than relying on either.
    """
    resolved = storage if storage is not None else default_storage(fmt)

    part_names = {k["name"] for k in partition_keys}
    body = ", ".join(_column(c) for c in columns if c["name"] not in part_names)

    stmt = f"CREATE EXTERNAL TABLE IF NOT EXISTS {quote(database)}.{quote(table_name)} ({body})"

    if partition_keys:
        part_cols = ", ".join(
            f"{quote(k['name'])} {_PARTITION_HIVE[k['type']]}" for k in partition_keys
        )
        stmt += f" PARTITIONED BY ({part_cols})"

    stmt += f" {resolved.clause} LOCATION {literal(location)}"

    props = _tblproperties(resolved, partition_keys, mark=mark)
    if props:
        rendered = ", ".join(f"{literal(k)}={literal(v)}" for k, v in props)
        stmt += f" TBLPROPERTIES ({rendered})"

    return stmt
