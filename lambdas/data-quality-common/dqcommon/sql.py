"""Athena SQL generation for the data-quality checks (SPEC-111).

Two halves:

1. **The temp-table DDL** (FR-001/FR-002) — a typed external table over the source, and,
   for CSV only, a single-column raw-line table that makes ragged-row detection possible
   at 250 GB. Both are built on ``cpcommon.ddl``, which carries the shared assembly and
   the partition-projection machinery (consolidated from table-builder's SPEC-069 copy);
   only the storage clauses differ, and they differ on purpose — see ``HIVE_JSON_SERDE``
   and ``RAW_LINE_SERDE`` below.

2. **The three queries** (FR-003) — profile, ragged, duplicates. They are separate
   statements rather than one, because they fail differently and only one of them
   deserves to kill the check.

Everything here is PURE: it builds strings and touches no AWS. That is what lets the
golden-string tests assert the exact SQL, which matters more than usual in this module —
a subtly wrong query does not crash, it reports the wrong numbers about a user's data.
"""

from cpcommon import ddl

from . import config

# ── Temp-table identifiers (FR-001) ──────────────────────────────────────────
#
# dq_tmp_{hex32} where {hex32} is the request UUID WITH ITS HYPHENS STRIPPED.
#
# The obvious name does not work, and it fails LATE — after the table exists, at query
# time — which is why the shape is pinned by a test:
#
#   _dq_{requestId}  ->  a LEADING UNDERSCORE forces Athena to require backticks around
#                        the identifier everywhere it appears, and
#                    ->  a raw UUID's HYPHENS PARSE AS SUBTRACTION.
#
# dq_tmp_ + 32 hex characters needs no quoting, is unambiguously temporary, sorts away
# from a user's real tables in the Query workspace's schema rail, and is still a pure
# function of requestId — so a Step Functions Retry rebuilds the same name and
# drop-temp-tables can find the table even if the verb that created it never returned.
_TABLE_PREFIX = "dq_tmp_"
_RAW_TABLE_PREFIX = "dq_tmp_raw_"


def hex32(request_id: str) -> str:
    """Return the request UUID with hyphens stripped (see the naming note above).

    Public because it is also the stem of every Athena ``ClientRequestToken`` this arc
    submits (SPEC-111 FR-003) — the tokens must be pure functions of the requestId for a
    retry to re-attach to the original executions, and deriving them from the same helper
    is what keeps that true.
    """
    return request_id.replace("-", "")


def temp_table_name(request_id: str) -> str:
    """Name of the typed temp table over the source."""
    return f"{_TABLE_PREFIX}{hex32(request_id)}"


def raw_table_name(request_id: str) -> str:
    """Name of the single-column raw-line temp table (CSV only)."""
    return f"{_RAW_TABLE_PREFIX}{hex32(request_id)}"


# ── Storage clauses (the parts that diverge from table-builder) ──────────────

# JSON uses the HIVE SerDe, NOT the OpenX one table-builder writes.
#
# This is not a stylistic preference. AWS documents the OpenX SerDe as one that "can be
# non-deterministic" and can produce "unexpected null values when none are present". This
# arc's ENTIRE JSON story is "a null means the key was missing" — the key-drift check
# falls straight out of FR-003's null ratios — so a SerDe that invents nulls would poison
# every JSON report SILENTLY: the report would look clean, and be wrong. A wrong quality
# report is worse than no quality report, because the user acts on it.
HIVE_JSON_SERDE = ddl.Storage(
    "ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe' STORED AS TEXTFILE"
)

# The raw-line table's serde (FR-002).
#
# WHAT IT IS FOR: ragged rows — rows whose field count doesn't match the header — are
# INVISIBLE to a normal SQL read, because the serde has already parsed them away by the
# time any query sees them. A second table over the same folder, with ONE column and a
# delimiter that never occurs in the data, hands each physical line to SQL as a raw
# string that can be split and counted. The alternative — reading the bytes in a Lambda —
# is impossible here: the sources this arc targets run to 250 GB, against a 900-second
# function.
#
# '\001' IS AN ESCAPE SEQUENCE, NEVER A LITERAL CONTROL BYTE. An invisible 0x01 pasted
# into a .py file survives no diff review, no copy-paste and no editor round-trip — it
# silently becomes something else, and the ragged check then splits on a delimiter that
# DOES occur in the data. (This arc's own spec carried a literal 0x01 byte until review
# caught it.) The characters below are backslash-zero-zero-one.
#
# There is deliberately NO skip.header.line.count here: every physical line must arrive,
# INCLUDING the header, so the ragged query can exclude it explicitly and so the line
# count is the true physical count.
RAW_LINE_SERDE = ddl.Storage(
    "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe' "
    "WITH SERDEPROPERTIES ('field.delim'='\\001') STORED AS TEXTFILE"
)

#: The raw-line table's single column.
RAW_LINE_COLUMN = "line"

_STORAGE = {
    # All-string columns under OpenCSVSerde — matching table-builder's shipped CSV
    # behaviour. Reading everything as string is what makes FR-003's TRY_CAST checks
    # possible at all: a column typed by the catalog can never hold a value that fails
    # to cast, so a typed CSV table would make the headline check vacuous.
    "csv": ddl.Storage(ddl.CSV_OPEN_SERDE, (ddl.CSV_SKIP_HEADER,)),
    "json": HIVE_JSON_SERDE,
    "parquet": ddl.Storage(ddl.PARQUET_STORED),
}


class TooManyColumnsError(ValueError):
    """The source is wider than ``DQ_MAX_COLUMNS``; the caller raises the terminal."""


def union_columns(files: list[dict]) -> list[dict]:
    """Union every probed file's columns, first-seen order, first-seen type wins.

    ``files`` is the manifest's ``files`` array (SPEC-110), each carrying the
    ``[{name, type}]`` its header probe produced. The union — not one file's list — is
    what the external table must declare, because a column present in only some files
    still has to be readable.

    FIRST-SEEN TYPE WINS on a cross-file conflict, and the honest consequence is worth
    stating: for Parquet, where the format enforces types, two files that disagree about
    a column's type will make the profile query fail on the odd file out. That
    disagreement is exactly what SPEC-112 FR-002's cross-file drift check exists to
    report, and it is computed from this same manifest rather than in SQL — an external
    table has ONE schema for the whole folder and would hide the disagreement. CSV cannot
    hit this (every column is string under the OpenCSVSerde) and the Hive JSON SerDe is
    tolerant; Parquet is the real case.
    """
    seen: dict[str, str] = {}
    for entry in files:
        for column in entry.get("columns") or []:
            seen.setdefault(column["name"], column["type"])
    return [{"name": name, "type": type_} for name, type_ in seen.items()]


def check_column_count(columns: list[dict]) -> None:
    """Raise ``TooManyColumnsError`` when the source is wider than the cap.

    THE DISASTER THIS PREVENTS: Athena caps a query STRING at 262,144 bytes. FR-003's
    profile query emits four TRY_CASTs plus a null-ratio and a bounded sample aggregate
    PER COLUMN, so a pathological source would otherwise build a query Athena cannot
    parse — and the user would get a raw engine error about query length instead of a
    clear "this folder is too wide to check".
    """
    if len(columns) > config.DQ_MAX_COLUMNS:
        raise TooManyColumnsError(
            f"{len(columns)} columns, over DQ_MAX_COLUMNS={config.DQ_MAX_COLUMNS}"
        )


def _projection_keys(partition_keys: list[dict]) -> list[dict]:
    """Manifest partition keys -> cpcommon.ddl's declared-key shape.

    SPEC-110 DETECTS keys and their observed values from the object paths (table-builder
    has the user declare them in a modal instead), so every key here is an ENUM over the
    values actually seen. Athena partition projection then resolves LOCATION/{key}={value}/
    directly — no MSCK REPAIR anywhere in this arc.
    """
    return [
        {"name": key["name"], "type": "string", "values": key["values"]}
        for key in partition_keys
    ]


def build_temp_table_ddl(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str,
    location: str,
) -> str:
    """Build the typed temp table's CREATE EXTERNAL TABLE IF NOT EXISTS.

    ``IF NOT EXISTS`` is what makes a Step Functions Retry a no-op rather than an error —
    the same natural idempotence table-builder's execute-ddl relies on.
    """
    try:
        storage = _STORAGE[fmt]
    except KeyError:
        raise ValueError(f"unknown format {fmt!r}") from None

    return ddl.build_create_table_ddl(
        database,
        table_name,
        columns,
        _projection_keys(partition_keys),
        fmt,
        location,
        storage=storage,
    )


def build_raw_table_ddl(database: str, table_name: str, location: str) -> str:
    """Build the CSV raw-line table's CREATE EXTERNAL TABLE IF NOT EXISTS.

    DELIBERATELY FLAT — no partition columns and no projection, even when the source IS
    partitioned. A non-partitioned Athena external table reads every object under its
    LOCATION recursively, which is precisely what the ragged-row count needs (every
    physical line, wherever it sits). Mirroring the typed table's projection here would
    add an enum list and a second way to be wrong for no gain. The two tables still see
    the same object universe, because inspect-source refuses a source whose objects
    disagree about their Hive layout (SPEC-110's partition_layout_mismatch).
    """
    return ddl.build_create_table_ddl(
        database,
        table_name,
        [{"name": RAW_LINE_COLUMN, "type": "string"}],
        [],
        "csv",
        location,
        storage=RAW_LINE_SERDE,
    )


def build_drop_table_ddl(database: str, table_name: str) -> str:
    """Build an idempotent DROP.

    ``IF EXISTS`` is the whole of drop-temp-tables' idempotence: the verb is reached on
    the success path AND, via the state machine's Catch, on every failure path — including
    failures that happened BEFORE create-temp-tables ran, where the table never existed.
    """
    return f"DROP TABLE IF EXISTS {ddl.quote(database)}.{ddl.quote(table_name)}"


# ── The three queries (FR-003) ───────────────────────────────────────────────
#
# THREE STATEMENTS, NOT ONE, and the split is the point. They fail differently, and only
# one of them deserves to kill the check:
#
#   profile     — the backbone. Its failure is TERMINAL.
#   ragged      — reads the raw-line table. A single pathological line (Athena caps one
#                 line of text at 200 MB) kills it. Degrades to not_computed.
#   duplicates  — GROUP BY over EVERY column is a full shuffle, the most expensive thing
#                 Athena does and a realistic way to exhaust query resources. It also
#                 simply cannot run over a JSON source with a MAP-typed column, which is
#                 not groupable in Trino. Degrades to not_computed.
#
# Folded into one statement, either of the last two would take EVERY OTHER FINDING down
# with it. Isolated, the user still gets their report.
#
# The honest scan cost: the typed table is read once for the profile and AGAIN for
# duplicates, and the raw-line table once for ragged. The second typed-table scan is the
# price of not letting a full-shuffle failure destroy the report.

#: Result-column prefix per source column — the report maps c{i}_* back to the i-th entry
#: of union_columns(). Positional rather than name-based on purpose: a user's column name
#: can contain characters that would need quoting in a result alias, or collide after
#: normalisation, and neither failure would be visible until the report was assembled.
_COLUMN_ALIAS = "c{index}"

#: A column is type-checked only when the catalog says it is a string. Anywhere else the
#: check is VACUOUS, not merely redundant: a bigint column cannot hold a value that fails
#: TRY_CAST to BIGINT, because the catalog (Parquet) or the SerDe already guaranteed it.
_CHECKED_TYPE = "string"

#: The casts the type-consistency check tries, in report order.
_CAST_TYPES = ("bigint", "double", "timestamp", "date")


def _sample_expr(column: str, predicate: str, size: int) -> str:
    """A BOUNDED sample of values matching ``predicate``.

    Trino's n-ary ``max_by(value, key, n)`` keeps only ``n`` entries in its accumulator,
    which is what makes this safe on a 250 GB column where every value offends. The naive
    ``array_agg`` then slice accumulates O(rows) and fails the query instead of sampling
    it.

    The key is the value itself, so the sample is the N lexicographically largest
    offenders — DETERMINISTIC, which matters because a Step Functions Retry re-runs the
    query and a random sample would silently change the report between attempts.
    ``max_by`` ignores rows whose KEY is null, so the CASE doubles as the filter.

    THE RESULT IS RENDERED AS JSON, and that is a correctness fix rather than a formatting
    preference (SPEC-112). Athena writes an ARRAY into its CSV result file as
    ``[N/A, -, 1,024]`` — the ELEMENTS are unquoted, so an offending value containing a
    comma is unrecoverable when assemble-report parses the cell back, and it splits into
    two wrong examples. These samples are drawn from exactly the badly-formed values most
    likely to contain one (``1,024`` in a numeric column is a canonical CSV defect, and the
    reason the column was flagged at all). ``json_format`` emits ``["N/A","-","1,024"]``,
    which round-trips through ``json.loads`` with commas, quotes and newlines intact.
    """
    keyed = f"CASE WHEN {predicate} THEN {column} END"
    return f"json_format(CAST(max_by({keyed}, {keyed}, {size}) AS JSON))"


def _projection(index: int, column: dict) -> str:
    """The INNER SELECT item that normalises one source column to a short alias.

    Two jobs, and the second one is why this inner select exists at all:

    1. **Normalise missingness once.** ``NULLIF(TRIM(col), '')`` folds "null" and "blank"
       into a single NULL, so every aggregate outside can just test ``IS NULL``. For JSON
       that IS the key-drift check — the Hive SerDe yields null for a missing key, so a
       key that stops being written shows up as a rising missing count with no extra
       machinery.
    2. **Shorten the identifier.** Every aggregate outside refers to ``c0`` rather than
       repeating a possibly-64-character quoted column name up to eight times. That is
       not cosmetic: ATHENA REJECTS A QUERY STRING OVER 262,144 BYTES, and the naive form
       (aggregating directly over the quoted name) measured 324 KB at DQ_MAX_COLUMNS=200 —
       over the cap, i.e. every wide check would have failed with a raw engine error about
       query length. A test pins the rendered size at the cap so this cannot regress.

    A non-string column is passed through untouched: ``TRIM`` is a string function, and
    the format already guarantees the value's type.
    """
    name = ddl.quote_dml(column["name"])
    alias = _COLUMN_ALIAS.format(index=index)
    if column["type"] == _CHECKED_TYPE:
        return f"NULLIF(TRIM({name}), '') AS {alias}"
    return f"{name} AS {alias}"


def _column_aggregates(index: int, column: dict, type_checked: bool) -> list[str]:
    """The OUTER SELECT items for one source column, over its ``c{index}`` alias."""
    alias = _COLUMN_ALIAS.format(index=index)
    items = [f"COUNT_IF({alias} IS NULL) AS {alias}_missing"]

    if not (type_checked and column["type"] == _CHECKED_TYPE):
        return items

    for cast in _CAST_TYPES:
        items.append(
            f"COUNT_IF({alias} IS NOT NULL AND TRY_CAST({alias} AS {cast.upper()}) IS NULL) "
            f"AS {alias}_not_{cast}"
        )

    # TWO samples, not four and not one. The report picks the one matching the column's
    # dominant type FAMILY (SPEC-112): a numeric-dominant column wants examples of values
    # that are not numbers, a temporal-dominant one wants values that are not dates. One
    # combined "fails all four casts" sample would miss the common case of a stray "3.7"
    # in an integer column (it parses as DOUBLE), and four per-cast samples would cost
    # query-string budget for detail nobody reads.
    #
    # No "is not null" guard in these predicates: the inner projection already turned
    # null-or-blank into NULL, and max_by ignores rows whose KEY is null — so a missing
    # value can never appear as an example of a badly-typed one.
    non_numeric = f"TRY_CAST({alias} AS BIGINT) IS NULL AND TRY_CAST({alias} AS DOUBLE) IS NULL"
    non_temporal = f"TRY_CAST({alias} AS TIMESTAMP) IS NULL AND TRY_CAST({alias} AS DATE) IS NULL"
    size = config.DQ_OFFENDING_VALUE_SAMPLE
    items.append(f"{_sample_expr(alias, non_numeric, size)} AS {alias}_sample_non_numeric")
    items.append(f"{_sample_expr(alias, non_temporal, size)} AS {alias}_sample_non_temporal")
    return items


def build_profile_query(database: str, table_name: str, columns: list[dict], fmt: str) -> str:
    """Build the profile query — the check's backbone (FR-003).

    Computes, exactly and at any scale: per-column missing counts, per-column
    type-consistency counts with bounded offending-value samples, and row counts both in
    total and PER FILE.

    TYPE CONSISTENCY IS SKIPPED ENTIRELY FOR PARQUET, and the report records that it was
    (SPEC-112). The reasoning is that the check is VACUOUS there, not merely redundant:
    Parquet enforces types in the format, so a numeric column CANNOT contain stray text
    and every TRY_CAST would trivially succeed. Emitting four casts per column over
    250 GB of Parquet would scan the whole dataset to prove something the file format
    already guarantees. Parquet sources still get missing counts, duplicates, row counts,
    and — the one that matters most for Parquet — cross-file schema drift (SPEC-112 FR-002).

    GROUPING SETS, not a plain GROUP BY: ((), ("$path")) yields ONE total row plus one row
    per source file in a single statement and a single scan. The grouping flag tells the
    reader which is which. The cost this accepts, stated plainly: every per-column
    aggregate is computed per file as well as globally, so the aggregate count scales with
    the file count — bounded by DQ_MAX_OBJECTS, and the alternative (a second statement,
    hence a second scan of up to 250 GB) is worse.

    The result set is O(files x columns) — never O(rows), which is what makes it safe for
    assemble-report to read whole (SPEC-112).
    """
    type_checked = fmt != "parquet"

    # The inner select normalises each column to a short alias (see _projection); the
    # outer one aggregates over those aliases. "$path" must be carried through the inner
    # select to stay groupable outside.
    projected = ", ".join(
        ['"$path"'] + [_projection(i, column) for i, column in enumerate(columns)]
    )
    items = ['"$path" AS source_file', 'GROUPING("$path") AS is_total', "COUNT(*) AS row_count"]
    for index, column in enumerate(columns):
        items.extend(_column_aggregates(index, column, type_checked))

    selected = ", ".join(items)
    table = f"{ddl.quote_dml(database)}.{ddl.quote_dml(table_name)}"
    return (
        f"SELECT {selected} FROM (SELECT {projected} FROM {table}) "
        'GROUP BY GROUPING SETS ((), ("$path"))'
    )


def build_ragged_query(database: str, raw_table_name_: str, header_column_count: int) -> str:
    """Build the ragged-rows query over the raw-line table (CSV only, FR-003).

    A row is ragged when its field count doesn't match the header's. Splitting the raw
    line is the only way to see that — by the time the normal SerDe is involved, the
    ragged row has already been parsed away.

    THE COUNT IS APPROXIMATE, for TWO reasons, and SPEC-112 must label it with both:

      1. ``split(line, ',')`` OVER-REPORTS on a QUOTED COMMA — `"Smith, John"` is one
         field but splits into two.
      2. It also over-reports on an EMBEDDED NEWLINE inside a quoted field, which makes
         one logical row arrive as two physical lines, each with the wrong field count.

    Blank lines are excluded explicitly. A blank line splits to a single empty field, so
    on any source with more than one column every blank line would otherwise be counted as
    ragged — one stray blank line in the middle of a file would put a false "ragged rows"
    finding in front of the user.

    The header itself is not excluded by a filter because it does not need to be: it has
    exactly ``header_column_count`` fields by definition, so it is never ragged. It IS
    counted in ``total_lines``, which is why that figure is named for LINES and not rows.
    """
    line = ddl.quote_dml(RAW_LINE_COLUMN)
    present = f"{line} IS NOT NULL AND {line} <> ''"
    return (
        f"SELECT COUNT_IF({present} AND cardinality(split({line}, ',')) <> {header_column_count}) "
        f"AS ragged_rows, COUNT_IF({present}) AS total_lines "
        f"FROM {ddl.quote_dml(database)}.{ddl.quote_dml(raw_table_name_)}"
    )


def build_duplicates_query(
    database: str, table_name: str, columns: list[dict], partition_keys: list[dict]
) -> str:
    """Build the duplicate-rows query (FR-003).

    ITS OWN STATEMENT, NEVER MERGED INTO THE PROFILE QUERY. A ``GROUP BY`` over every
    column of a 250 GB table is a FULL SHUFFLE — the single most expensive operation
    Athena offers, and a realistic way to exhaust query resources. Isolated, its failure
    degrades the report to ``duplicates: not_computed``; merged, it would destroy every
    other finding along with itself.

    THE RESULT SHAPE IS PINNED TO EXACTLY ONE ROW, which is what lets assemble-report read
    the result file whole without a bound.

    Partition columns are included in the grouping because they are part of the row: two
    otherwise-identical rows in different partitions are different rows, not duplicates.
    """
    part_names = {key["name"] for key in partition_keys}
    grouped = [ddl.quote_dml(c["name"]) for c in columns if c["name"] not in part_names]
    grouped.extend(ddl.quote_dml(key["name"]) for key in partition_keys)
    all_columns = ", ".join(grouped)
    table = f"{ddl.quote_dml(database)}.{ddl.quote_dml(table_name)}"

    return (
        "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM "
        f"(SELECT COUNT(*) AS cnt FROM {table} GROUP BY {all_columns} HAVING COUNT(*) > 1)"
    )
