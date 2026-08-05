"""Pure CREATE EXTERNAL TABLE DDL generation for the control-plane arcs (SPEC-111).

Consolidated from ``table-builder-infer-schema/ddl.py`` (SPEC-069), which was the only
copy until the data-quality arc needed the same assembly with different storage clauses.
Same move as ``cpcommon.type_mapping`` (PR #229): the projection-props logic is fiddly,
easy to get subtly wrong, and must not exist twice.

What is SHARED and lives here: identifier quoting, the column body, ``PARTITIONED BY``,
the Athena partition-projection ``TBLPROPERTIES``, and the statement assembly.

What is NOT shared is the STORAGE CLAUSE, and that is deliberate — the two arcs disagree
on purpose:

- table-builder writes JSON with the **OpenX** SerDe (its shipped behaviour, unchanged
  here); data-quality writes it with the **Hive** SerDe, because AWS documents OpenX as
  potentially non-deterministic around nulls and the whole data-quality JSON story is
  "a null means the key was missing" (SPEC-111 FR-001).
- data-quality also builds a single-column raw-line table with ``LazySimpleSerDe`` that
  has no analogue here at all.

So ``storage`` is injectable. Pass nothing and you get the table-builder defaults that
were here before this module moved; pass a ``Storage`` and you get exactly your clause
plus your properties. A domain's SerDe choice belongs in that domain's layer, next to the
comment explaining why — not in a shared ``if fmt ==`` ladder that reads as if one of the
two arcs is wrong.
"""

from typing import NamedTuple

# Hive type for each declared partition-key projection type.
_PARTITION_HIVE = {"integer": "int", "date": "date", "string": "string"}

# ── Storage clauses (the shared ones; domains add their own) ─────────────────
# OpenCSVSerde escapeChar is a single backslash; written as '\\' in DDL (two chars).
CSV_OPEN_SERDE = (
    "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
    "WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') "
    "STORED AS TEXTFILE"
)
JSON_OPENX_SERDE = "ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe' STORED AS TEXTFILE"
PARQUET_STORED = "STORED AS PARQUET"

#: Skip the CSV header row. A TBLPROPERTY, not part of the SerDe clause, because the
#: data-quality raw-line table uses a CSV-ish serde and must NOT skip the header (it
#: counts every physical line, SPEC-111 FR-002).
CSV_SKIP_HEADER = ("skip.header.line.count", "1")

#: "This portal created this table" — a durable, queryable answer available from the first
#: table created after SPEC-143 (greenfield with no production users is exactly when to
#: start writing it). NOT the refresh eligibility test, and it must never become one: every
#: table predating this spec lacks it, and TBLPROPERTIES are user-writable through ALTER
#: TABLE, so it can be trusted neither as a permission nor as a fact. Eligibility turns on
#: SHAPE (cpcommon.glue.clone_definition), and a test enforces that no verb reads this.
#:
#: NOTE 'portal.managed' (this, a table TBLPROPERTY, dotted) is NOT 'portal-managed' (the
#: Lake Formation tag on DATABASES, hyphenated — infra/modules/analytics/lakeformation.tf).
#: Unrelated jobs, one character apart.
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


#: The table-builder defaults (SPEC-069), unchanged. ``build_create_table_ddl`` falls back
#: to these when no ``storage`` is passed, which is what keeps that arc's golden-string
#: tests meaningful across this move.
_DEFAULT_STORAGE = {
    "parquet": Storage(PARQUET_STORED),
    "csv": Storage(CSV_OPEN_SERDE, (CSV_SKIP_HEADER,)),
    "json": Storage(JSON_OPENX_SERDE),
}


def mark_managed(parameters: dict) -> dict:
    """Return ``parameters`` with the portal's creation marker asserted.

    EXISTS SO THE MARKER KEEPS EXACTLY TWO HOMES. Until SPEC-149 the only writer was
    ``build_create_table_ddl``, so no verb ever had to name it — and a test scans the whole
    Lambda tree for exactly that, because the moment a verb can name the property it can
    branch on it, and TBLPROPERTIES are user-writable through ALTER TABLE (SPEC-143 FR-007).
    ``apply-refresh`` writes Glue ``Parameters`` directly rather than DDL, so it needs the
    marker without needing the constant; this is that door.

    A copy, not a mutation: the caller's dict is often the LIVE table's parameters.
    """
    return {**parameters, PORTAL_MANAGED[0]: PORTAL_MANAGED[1]}


def quote(identifier: str) -> str:
    """Backtick-quote a catalog identifier for a DDL statement (db / table / column).

    DDL ONLY. Athena parses ``CREATE``/``DROP`` with Hive syntax, where backticks are the
    identifier quote — but it parses ``SELECT`` with Trino syntax, where they are not.
    Use ``quote_dml`` inside a query (SPEC-111).
    """
    return f"`{identifier}`"


def literal(value: str) -> str:
    """Single-quoted DDL string literal with backslash/quote escapes.

    The same rule ``tscommon.ddl._lit`` applies to a cloned column comment — a comment is
    free text a user wrote, so an apostrophe in it must not end the literal and turn the
    rest of the statement into syntax.
    """
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def quote_dml(identifier: str) -> str:
    """Double-quote a catalog identifier for a DML statement (SELECT and friends).

    ATHENA'S TWO DIALECTS ARE A REAL TRAP, and it fails at query time rather than at build
    time: DDL is Hive (backticks), DML is Trino (double quotes), and AWS documents that
    backticks in a DML query are an error. A query built with the DDL quoter looks
    perfectly reasonable in a diff and in a golden-string test, then fails against the
    engine — after the temp tables exist and the scan has been paid for.

    An embedded double quote is escaped by doubling, so a column named ``he said "hi"``
    still produces a parseable identifier rather than a syntax error (or, worse, a
    statement that parses into something else).
    """
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def default_storage(fmt: str) -> Storage:
    """Return the table-builder storage for ``fmt``.

    Raises:
        ValueError: on an unknown format — a typo must not silently produce a table with
            no storage clause.
    """
    try:
        return _DEFAULT_STORAGE[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}") from None


def _column(column: dict) -> str:
    """One column body entry, carrying its COMMENT when it has one.

    A comment is the one piece of column metadata a USER writes, and a DROP + CREATE
    rebuild is where it would silently disappear (SPEC-144). The create path never sets
    one — inference has nothing to say about a column's meaning — so this renders
    identically for every table this repo has created so far.
    """
    rendered = f"{quote(column['name'])} {column['type']}"
    if column.get("comment"):
        rendered += f" COMMENT {literal(column['comment'])}"
    return rendered


def _projection_props(key):
    """Athena projection.* TBLPROPERTIES for one declared partition key."""
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
        # BOTH spellings accepted (SPEC-151 FR-007). The browser's type declares
        # `intervalUnit` (tableBuild.types.ts) while this renderer has always read
        # `interval.unit`, so the field the browser says it sends was silently dropped.
        # Latent today — no UI path populates it — but a trap for the next change, and
        # already flagged at load_table_definition.py. Accepting both here means neither
        # the browser's spelling nor the catalog's can go missing.
        # `or`, not a `get` DEFAULT: an explicit `"interval.unit": None` alongside a real
        # `intervalUnit` would make `dict.get(k, fallback)` return the present None and
        # silently drop the property — the same class of silent drop this line fixes.
        unit = key.get("interval.unit") or key.get("intervalUnit")
        if unit is not None:
            props.append((f"projection.{name}.interval.unit", str(unit)))
    elif ptype == "string":
        values = key["values"]
        # Asserted rather than left to `",".join`, which raises a bare TypeError from
        # inside the renderer — surfacing to the user as "something went wrong" instead of
        # a partition-key validation message (SPEC-151 FR-006).
        if not all(isinstance(v, str) for v in values):
            raise ValueError(f"partition key {name!r}: every enum value must be a string")
        props.append((f"projection.{name}.type", "enum"))
        props.append((f"projection.{name}.values", ",".join(values)))
    else:
        raise ValueError(f"unknown partition type {ptype!r} for {name!r}")
    return props


def partition_hive_type(declared_type: str) -> str | None:
    """The Hive column type ``PARTITIONED BY`` renders for a declared partition type.

    The refresh path needs this to check the OTHER direction (SPEC-143 FR-005): Athena
    lets a projection sit on a wider set of column types than this builder writes — an
    `integer` projection is legal on a `string` column, and zero-padded partitions are
    exactly why someone would declare one that way. Such a table reconstructs cleanly from
    its projection properties alone and would then be REBUILT with a different column
    type, silently, so the refresh path compares the live column type against this.
    """
    return _PARTITION_HIVE.get(declared_type)


def projection_properties(key) -> dict:
    """The ``projection.*`` properties one declared partition key renders to, as a dict.

    The public door onto ``_projection_props`` for the refresh path, which has to go the
    OTHER way — reading a live table's projection properties back into a declared key
    (SPEC-143 FR-005). That reconstruction is only trustworthy if it re-renders to exactly
    the properties it read, and it can only check that against the renderer the create path
    actually uses. A second copy of this mapping in the refresh verb is the one thing that
    would make the check meaningless.
    """
    return dict(_projection_props(key))


#: SerDe library -> the format key this repo's inference reports. The refresh path compares
#: the two: a folder that now holds JSON under a table declared with OpenCSVSerde has
#: changed in a way re-deriving columns cannot fix (SPEC-143 FR-006). Both JSON SerDes are
#: listed because the two arcs deliberately disagree on which to write (see the module
#: docstring) and a refresh may meet either.
SERDE_FORMATS = {
    "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe": "parquet",
    "org.apache.hadoop.hive.serde2.OpenCSVSerde": "csv",
    "org.openx.data.jsonserde.JsonSerDe": "json",
    "org.apache.hive.hcatalog.data.JsonSerDe": "json",
}


def format_of_serde(library) -> str | None:
    """The format ``library`` corresponds to, or None if it is not one this repo writes."""
    return SERDE_FORMATS.get(library)


def _tblproperties(storage, partition_keys, *, mark):
    """Ordered (k, v) TBLPROPERTIES: the marker, the storage's own props, then projection.

    The marker leads; the storage-then-projection order the golden strings pin is
    unchanged either way, so this is a reading choice — identity before behaviour.

    DE-DUPLICATED BY KEY, first occurrence winning. Defensive rather than load-bearing now
    that nothing merges captured properties in (SPEC-149 removed the rebuild that did): a
    format contributing a key twice is cheap to tolerate and expensive to debug, because
    emitting one twice inside a single ``TBLPROPERTIES (…)`` is at best redundant and at
    worst rejected.
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
    """Build a valid CREATE EXTERNAL TABLE IF NOT EXISTS statement (string).

    ``columns`` is the ordered [{name, type}] (Hive types) data body;
    ``partition_keys`` are the declared keys ([] = flat). A data column that collides
    with a partition-key name is dropped from the body (the partition key wins) so the
    DDL stays valid.

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
            defaults; supply one when the domain's SerDe choice differs (data-quality's
            Hive JSON SerDe, its raw-line LazySimpleSerDe — SPEC-111 FR-001/FR-002).
        mark: Whether to emit the ``portal.managed`` marker (SPEC-143 FR-007). Default on,
            and A SEPARATE ARGUMENT FROM ``storage`` DELIBERATELY. Inferring it from
            ``storage is None`` would read correctly against today's two callers and be
            wrong for the next one: SPEC-144's ``apply-refresh`` supplies a Storage rebuilt
            from the live table, so an inferred rule would strip the marker from every
            table a refresh touches — erasing exactly what FR-007 exists to record, on the
            tables most likely to be asked about. Pass ``False`` for a table that is not a
            durable user table (data-quality's ``dq_tmp_*``, dropped in the same run).

    Returns:
        The full statement as one line.
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

    # Through literal(), not an f-string quote (SPEC-151 FR-006). An S3 key may contain an
    # apostrophe — a folder named `o'brien` is an ordinary thing for a user to create — and
    # a raw '{location}' ends the literal there and turns the rest of the statement into
    # syntax. The sharpest path is data-quality, where the LOCATION and the partition
    # values both come from S3 KEY SEGMENTS, so a folder named `year=2024'` broke the
    # temp-table DDL and the whole check died as `query_failed`.
    stmt += f" {resolved.clause} LOCATION {literal(location)}"

    props = _tblproperties(resolved, partition_keys, mark=mark)
    if props:
        # Both sides escaped: a partition enum value of `eu','projection.enabled'='false`
        # rendered as `'projection.region.values'='eu','projection.enabled'='false'`,
        # INJECTING a property that switched partition projection off. Self-scoped (a user
        # can only reach a table in their own database, and Athena rejects multi-statement
        # DDL), so this is robustness rather than cross-tenant escalation — but the
        # escaper has sat in this module all along and is already used for column comments.
        rendered = ", ".join(f"{literal(k)}={literal(v)}" for k, v in props)
        stmt += f" TBLPROPERTIES ({rendered})"

    return stmt
