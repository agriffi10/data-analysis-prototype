"""Athena SQL generation for the data-quality checks.

Two halves. The temp-table DDL builds a typed external table over the source and, for CSV only,
a single-column raw-line table that makes ragged-row detection possible at scale; both are built
on the shared DDL assembly, and only the storage clauses differ, on purpose. The three queries —
profile, ragged and duplicates — are separate statements rather than one, because they fail
differently and only one of them deserves to kill the check.

Everything here is pure: it builds strings and touches no AWS, so the exact SQL a check will run
can be asserted without an engine. That matters more than usual in this module — a subtly wrong
query does not crash, it reports the wrong numbers about a user's data.

The honest scan cost of the three-statement split: the typed table is read once for the profile
and again for duplicates, and the raw-line table once for ragged. The second typed-table scan is
the price of not letting a full-shuffle failure destroy the report.

Attributes:
  _TABLE_PREFIX: The typed temp table's prefix. The obvious name does not work, and it fails
    late — after the table exists, at query time — which is why the shape is pinned by a test: a
    leading underscore forces Athena to require quoting everywhere the identifier appears, and a
    raw UUID's hyphens parse as subtraction. This form needs no quoting, is unambiguously
    temporary, sorts away from a user's real tables in the schema rail, and is still a pure
    function of the request id, so a retry rebuilds the same name and the drop verb can find the
    table even if the verb that created it never returned.
  _RAW_TABLE_PREFIX: The raw-line table's prefix, same reasoning.
  HIVE_JSON_SERDE: The JSON storage clause. Uses the Hive SerDe, not the OpenX one table-builder
    writes, and not as a stylistic preference: AWS documents OpenX as potentially
    non-deterministic and able to produce unexpected nulls. This arc's entire JSON story is that
    a null means the key was missing, so a SerDe that invents nulls would poison every JSON
    report silently — the report would look clean and be wrong, which is worse than no report,
    because the user acts on it.
  RAW_LINE_SERDE: The raw-line table's storage clause. Ragged rows are invisible to a normal read
    because the SerDe has already parsed them away, so a second table over the same folder with
    one column and a delimiter that never occurs in the data hands each physical line to SQL as a
    raw string. The delimiter is the four characters backslash-zero-zero-one — an escape
    sequence, never a literal control byte: an invisible 0x01 pasted into a source file survives
    no diff review, no copy-paste and no editor round-trip, and the ragged check would then split
    on a delimiter that does occur in the data. That is not hypothetical; this arc's own spec
    carried a literal 0x01 until review caught it. There is deliberately no header-skip property
    — every physical line must arrive, including the header, so the ragged query can exclude it
    explicitly and the line count is the true physical count.
  RAW_LINE_COLUMN: The raw-line table's single column.
  _STORAGE: Format to storage clause for the typed table. CSV is all-string under OpenCSVSerde,
    matching table-builder's shipped behaviour, and reading everything as string is what makes
    the type-consistency checks possible at all — a column typed by the catalog can never hold a
    value that fails to cast, so a typed CSV table would make the headline check vacuous.
  RAGGED_QUERY_TOO_LARGE: Marker the caller puts on a degraded ragged block so the report can
    pick the right user-facing sentence. A code rather than matched text, unlike the
    line-too-long case: that one has to read Athena's own wording, this one is a string we write
    ourselves.
  _COLUMN_ALIAS: Result-column prefix per profiled column; the report maps each alias back to the
    corresponding entry of ``profiled_columns``, never of the bare union. Positional rather than
    name-based on purpose — a user's column name can contain characters needing quoting in a
    result alias, or collide after normalisation, and neither failure would be visible until the
    report was assembled.
  _CHECKED_TYPE: A column is type-checked only when the catalog says it is a string. Anywhere
    else the check is vacuous, not merely redundant: a typed column cannot hold a value that
    fails to cast, because the catalog or the SerDe already guaranteed it.
  _CAST_TYPES: The casts the type-consistency check tries, in report order.
"""

from cpcommon import columns as columns_mod
from cpcommon import ddl
from cpcommon.errors import TerminalError

from . import config, messages

_TABLE_PREFIX = "dq_tmp_"
_RAW_TABLE_PREFIX = "dq_tmp_raw_"


def hex32(request_id: str) -> str:
    """Returns the request UUID with its hyphens stripped.

    Public because it is also the stem of every Athena idempotency token this arc submits: the
    tokens must be pure functions of the request id for a retry to re-attach to the original
    executions, and deriving them from the same helper is what keeps that true.

    Args:
      request_id: The run's request id.

    Returns:
      The hyphen-free hex string.

    Raises:
      None.
    """
    return request_id.replace("-", "")


def temp_table_name(request_id: str) -> str:
    """Names the typed temp table over the source.

    Args:
      request_id: The run's request id.

    Returns:
      The table name.

    Raises:
      None.
    """
    return f"{_TABLE_PREFIX}{hex32(request_id)}"


def raw_table_name(request_id: str) -> str:
    """Names the single-column raw-line temp table, used for CSV only.

    Args:
      request_id: The run's request id.

    Returns:
      The table name.

    Raises:
      None.
    """
    return f"{_RAW_TABLE_PREFIX}{hex32(request_id)}"


def temp_database(space: dict, actor: str | None) -> str | None:
    """Resolves the Glue database a run's temp tables live in.

    Beside the two name builders because the three together are the whole identity of a run's
    temp tables, and both the verb that creates them and the verb that drops them need all
    three. A second copy of this mapping is what would let the drop verb look for a table in a
    database the create verb never used.

    The space is the database: a personal check uses the actor's own database, since a username
    is a database name, and a shared check uses the space's prefix. Both are re-derived from the
    state the validate verb already proved the actor may use — the request body never carried a
    database, and it must not start being trusted for one here.

    Answers None rather than raising, because one of its two callers is cleanup, which must never
    raise. The caller that needs a terminal builds it.

    **A blank-but-present value answers None, and that is not incidental.** This replaced a pair
    of ``events.require`` calls, which reject a whitespace-only string before they return it; a
    plain truthiness test does not, and would hand back ``"   "`` as a Glue database name. The
    value is returned UNSTRIPPED, exactly as ``require`` did, so a legitimate name crosses this
    function byte-identical — the strip decides admission, never the answer. A slash-only shared
    prefix answers None too, where the old pair returned an EMPTY database name and built a
    statement quoting nothing against it.

    Nothing reachable relies on this: the validate verb has already pinned the personal prefix to
    the actor and loaded the shared space from the registry, so a blank of either kind cannot get
    this far. It is the check the old code got for free, and dropping it silently on a refactor is
    how a free check disappears.

    Args:
      space: The request's space object, carrying its kind and prefix.
      actor: The verified username.

    Returns:
      The database name, or None when the space kind is unknown, or the field it needs is
      missing, empty or blank.

    Raises:
      None.
    """
    kind = (space or {}).get("kind")
    if kind == "personal":
        return actor if (actor or "").strip() else None
    if kind == "shared":
        prefix = ((space or {}).get("prefix") or "").strip("/")
        return prefix if prefix.strip() else None
    return None


HIVE_JSON_SERDE = ddl.Storage(
    "ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe' STORED AS TEXTFILE"
)

RAW_LINE_SERDE = ddl.Storage(
    "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe' "
    "WITH SERDEPROPERTIES ('field.delim'='\\001') STORED AS TEXTFILE"
)

RAW_LINE_COLUMN = "line"

_STORAGE = {
    "csv": ddl.Storage(ddl.CSV_OPEN_SERDE, (ddl.CSV_SKIP_HEADER,)),
    "json": HIVE_JSON_SERDE,
    "parquet": ddl.Storage(ddl.PARQUET_STORED),
}


class TooManyColumnsError(ValueError):
    """The source is wider than the column cap; the caller raises the terminal."""


class RaggedQueryTooLargeError(ValueError):
    """The rendered ragged query exceeds Athena's query-string cap.

    Not a terminal, and deliberately its own type rather than a truncated query: the per-path
    comparison is one branch per file, so a manifest of long keys can outgrow the cap. Silently
    dropping the branches that do not fit would re-introduce the exact bug the per-file
    comparison fixes — every line of a dropped file judged against somebody else's column count —
    on a subset nobody could see. The caller degrades the figure instead, and the rest of the
    report still lands.
    """


RAGGED_QUERY_TOO_LARGE = "ragged_query_too_large"


def _spellings(files: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Groups every probed column across the files under the name Athena gives it.

    The one place the folder's columns are keyed, so the union the table declares and the
    spellings the report discloses cannot disagree about which headers are one column.

    Args:
      files: The manifest's file entries, each carrying the columns its header probe produced.

    Returns:
      Each folded name, in first-seen order, to every ``(name, type)`` that folds to it, in the
      order the files list them.

    Raises:
      KeyError: If a probed column is missing its name or type.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for entry in files:
        for column in entry.get("columns") or []:
            groups.setdefault(columns_mod.fold(column["name"]), []).append(
                (column["name"], column["type"])
            )
    return groups


def union_columns(files: list[dict]) -> list[dict]:
    """Unions every probed file's columns by the name Athena gives them, first-seen winning.

    The union rather than one file's list is what the external table must declare, because a
    column present in only some files still has to be readable.

    Names are matched through ``columns.fold``, so ``CustomerID`` in one file and ``customerid``
    in another are one column, declared under the first-seen spelling. Athena lowercases every
    column it creates, so declaring both would be the collision the name rule refuses, and no
    single file carries it — refusing would stop a folder that table-builder, reading one sample
    header, builds without complaint. The merge reads correctly in every format: a CSV is read by
    position, so the name never reaches the file, and Parquet and JSON are matched by name with the
    catalog's lowercase against the file's own spelling, which a single file with a mixed-case
    column already depends on. A collision INSIDE one file is still refused, by the caller, before
    a table is built from this list: merged here, it would declare a CSV one column short and read
    every later column from its neighbour's field.

    The honest consequence of first-seen-type-wins is worth stating: for Parquet, where the
    format enforces types, two files disagreeing about a column's type will make the profile
    query fail on the odd file out. That disagreement is exactly what the cross-file drift check
    exists to report, and it is computed from this same manifest rather than in SQL — an external
    table has one schema for the whole folder and would hide the disagreement. CSV cannot hit
    this, since every column is a string, and the Hive JSON SerDe is tolerant; Parquet is the
    real case, and two spellings of one column with two types is that case too.

    Args:
      files: The manifest's file entries, each carrying the columns its header probe produced.

    Returns:
      The unioned columns.

    Raises:
      KeyError: If a probed column is missing its name or type.
    """
    return [{"name": group[0][0], "type": group[0][1]} for group in _spellings(files).values()]


def other_spellings(files: list[dict]) -> dict[str, list[str]]:
    """The spellings each unioned column was merged from, beyond the one it is declared under.

    What the report discloses for a merged column. Nothing needs repairing — Athena reads the
    spellings as one column — but a user whose other tools match names exactly would otherwise
    find ``customerid`` missing from a report over files that plainly carry it.

    Args:
      files: The manifest's file entries, each carrying the columns its header probe produced.

    Returns:
      Each unioned column's declared name to its other distinct spellings, in first-seen order;
      a column with one spelling is absent.

    Raises:
      KeyError: If a probed column is missing its name or type.
    """
    merged: dict[str, list[str]] = {}
    for group in _spellings(files).values():
        declared = group[0][0]
        others = list(dict.fromkeys(name for name, _type in group if name != declared))
        if others:
            merged[declared] = others
    return merged


def profiled_columns(
    columns: list[dict], partition_keys: list[dict], fmt: str | None
) -> list[dict]:
    """Maps the unioned columns to the ones the typed temp table actually declares.

    The one list every per-column figure is computed and reported over: the profile query
    numbers its aliases by position in it, the report reads them back by the same position, and
    the duplicates grouping names it before the partition keys. A column naming a partition key
    is declared under its ``ddl.declare_columns`` name in a CSV, so its figures are the file's and
    carry that name. In JSON and Parquet it is not in the list, because the temp table leaves it
    out — and projecting the name anyway would not fail, it would bind to the partition column
    and report the folder's value under the user's column name. Mapping after numbering on
    either side, or on one side only, attaches every later column's figures to its neighbour's
    name.

    The file's own header still counts that column under the file's name wherever the FILE is
    what is read: cross-file agreement and the ragged comparison both take their columns from the
    manifest, not from here.

    Args:
      columns: The unioned columns.
      partition_keys: The manifest's detected partition keys.
      fmt: The source format, which decides whether such a column is renamed or left out. The
        profile query, the duplicates grouping and the report must each pass the same one.

    Returns:
      The columns the temp table declares, in union order.

    Raises:
      KeyError: If a column or partition key is missing its name.
    """
    return ddl.body_columns(columns, partition_keys, fmt)


def check_column_count(columns: list[dict]) -> None:
    """Refuses a source wider than the column cap.

    Athena caps a query string, and the profile query emits several casts plus aggregates per
    column, so a pathological source would otherwise build a query Athena cannot parse — and the
    user would get a raw engine error about query length instead of a clear message about the
    folder being too wide to check.

    Args:
      columns: The unioned columns.

    Returns:
      None.

    Raises:
      TooManyColumnsError: When the source exceeds the cap.
    """
    if len(columns) > config.DQ_MAX_COLUMNS:
        raise TooManyColumnsError(
            f"{len(columns)} columns, over DQ_MAX_COLUMNS={config.DQ_MAX_COLUMNS}"
        )


def _projection_keys(partition_keys: list[dict]) -> list[dict]:
    """Converts manifest partition keys into the shared declared-key shape.

    This arc detects keys and their observed values from the object paths, rather than having the
    user declare them, so every key is an enum over the values actually seen. Athena's partition
    projection then resolves each partition path directly, and no repair step exists anywhere in
    this arc.

    Args:
      partition_keys: The manifest's detected keys, each carrying its observed values.

    Returns:
      The declared keys the DDL builder expects.

    Raises:
      KeyError: If a key is missing its name or values.
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
    """Builds the typed temp table's create statement.

    The idempotent form is what makes a Step Functions retry a no-op rather than an error. The
    portal's managed marker is not written: a temp table dropped at the end of this run is not
    something the portal manages, and the marker is a durable claim about a user's table.

    Args:
      database: The target database.
      table_name: The temp table's name.
      columns: The unioned columns.
      partition_keys: The manifest's detected partition keys.
      fmt: The source format.
      location: The ``s3://`` folder the table reads.

    Returns:
      The full statement.

    Raises:
      ValueError: On an unknown format, or an unrenderable partition key.
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
        mark=False,
    )


def build_raw_table_ddl(database: str, table_name: str, location: str) -> str:
    """Builds the CSV raw-line table's create statement.

    Deliberately flat — no partition columns and no projection, even when the source is
    partitioned. A non-partitioned external table reads every object under its location
    recursively, which is precisely what the ragged-row count needs: every physical line,
    wherever it sits. Mirroring the typed table's projection here would add an enum list and a
    second way to be wrong for no gain. The two tables still see the same object universe,
    because inspect-source refuses a source whose objects disagree about their layout. It must
    emit no table properties at all, so the marker is off.

    Args:
      database: The target database.
      table_name: The raw table's name.
      location: The ``s3://`` folder the table reads.

    Returns:
      The full statement.

    Raises:
      None.
    """
    return ddl.build_create_table_ddl(
        database,
        table_name,
        [{"name": RAW_LINE_COLUMN, "type": "string"}],
        [],
        "csv",
        location,
        storage=RAW_LINE_SERDE,
        mark=False,
    )


def build_drop_table_ddl(database: str, table_name: str) -> str:
    """Builds an idempotent drop statement.

    The if-exists form is the whole of the drop verb's idempotence: it is reached on the success
    path and, via the state machine's Catch, on every failure path — including failures that
    happened before the create verb ran, where the table never existed.

    Args:
      database: The target database.
      table_name: The table to drop.

    Returns:
      The full statement.

    Raises:
      None.
    """
    return f"DROP TABLE IF EXISTS {ddl.quote(database)}.{ddl.quote(table_name)}"


_COLUMN_ALIAS = "c{index}"

_CHECKED_TYPE = "string"

_CAST_TYPES = ("bigint", "double", "timestamp", "date")


def _sample_expr(column: str, predicate: str, size: int) -> str:
    """Builds a bounded sample of the values matching a predicate.

    Trino's n-ary max-by keeps only the requested number of entries in its accumulator, which is
    what makes this safe on a huge column where every value offends. A naive collect-then-slice
    accumulates every row and fails the query instead of sampling it.

    The key is the value itself, so the sample is the lexicographically largest offenders —
    deterministic, which matters because a retry re-runs the query and a random sample would
    silently change the report between attempts. The aggregate ignores rows whose key is null, so
    the conditional doubles as the filter.

    The result is rendered as JSON, and that is a correctness fix rather than a formatting
    preference: Athena writes an array into its CSV result file with unquoted elements, so an
    offending value containing a comma is unrecoverable when the report parses the cell back and
    splits into two wrong examples. These samples are drawn from exactly the badly-formed values
    most likely to contain one — a thousands-separated number in a numeric column is a canonical
    CSV defect, and the reason the column was flagged at all. JSON round-trips with commas,
    quotes and newlines intact.

    Args:
      column: The already-aliased column expression.
      predicate: The condition an offending value satisfies.
      size: How many examples to keep.

    Returns:
      The SQL expression.

    Raises:
      None.
    """
    keyed = f"CASE WHEN {predicate} THEN {column} END"
    return f"json_format(CAST(max_by({keyed}, {keyed}, {size}) AS JSON))"


def _projection(index: int, column: dict) -> str:
    """Builds the inner select item that normalises one source column to a short alias.

    Two jobs, and the second is why this inner select exists at all. It normalises missingness
    once, folding null and blank into a single null so every aggregate outside can just test for
    null — and for JSON that is the key-drift check, since the SerDe yields null for a missing key
    and a key that stops being written shows up as a rising missing count with no extra
    machinery. And it shortens the identifier, so every aggregate outside refers to a two- to
    four-character alias rather than repeating a possibly-long quoted column name many times.
    That is not cosmetic: Athena rejects an over-length query string, and the naive form —
    aggregating directly over the quoted name — repeats every name, and the null-or-blank folding
    around it, in every aggregate. At the column cap that runs past Athena's 262,144-byte limit
    even with ten-character names, so every wide check would have failed with a raw engine error
    about query length. A test renders the query at the column cap with every name as long as the
    column rule admits and holds it under the limit, so this cannot regress.

    A non-string column is passed through untouched: trimming is a string operation, and the
    format already guarantees the value's type.

    Args:
      index: The column's position, which names its alias.
      column: The column's name and type.

    Returns:
      The select item.

    Raises:
      KeyError: If the column is missing its name or type.
    """
    name = ddl.quote_dml(column["name"])
    alias = _COLUMN_ALIAS.format(index=index)
    if column["type"] == _CHECKED_TYPE:
        return f"NULLIF(TRIM({name}), '') AS {alias}"
    return f"{name} AS {alias}"


def _column_aggregates(index: int, column: dict, type_checked: bool) -> list[str]:
    """Builds the outer select items for one source column, over its alias.

    Two samples are emitted, not four and not one. The report picks the one matching the column's
    dominant type family: a numeric-dominant column wants examples of values that are not
    numbers, a temporal-dominant one wants values that are not dates. One combined "fails every
    cast" sample would miss the common case of a stray decimal in an integer column, which parses
    as a float, and four per-cast samples would cost query-string budget for detail nobody reads.

    The sample predicates carry no null guard: the inner projection already turned null-or-blank
    into null, and the aggregate ignores rows whose key is null, so a missing value can never
    appear as an example of a badly-typed one.

    Args:
      index: The column's position, which names its alias.
      column: The column's name and type.
      type_checked: Whether this source's format warrants type-consistency checks at all.

    Returns:
      The select items for this column.

    Raises:
      KeyError: If the column is missing its type.
    """
    alias = _COLUMN_ALIAS.format(index=index)
    items = [f"COUNT_IF({alias} IS NULL) AS {alias}_missing"]

    if not (type_checked and column["type"] == _CHECKED_TYPE):
        return items

    for cast in _CAST_TYPES:
        items.append(
            f"COUNT_IF({alias} IS NOT NULL AND TRY_CAST({alias} AS {cast.upper()}) IS NULL) "
            f"AS {alias}_not_{cast}"
        )

    non_numeric = f"TRY_CAST({alias} AS BIGINT) IS NULL AND TRY_CAST({alias} AS DOUBLE) IS NULL"
    non_temporal = f"TRY_CAST({alias} AS TIMESTAMP) IS NULL AND TRY_CAST({alias} AS DATE) IS NULL"
    size = config.DQ_OFFENDING_VALUE_SAMPLE
    items.append(f"{_sample_expr(alias, non_numeric, size)} AS {alias}_sample_non_numeric")
    items.append(f"{_sample_expr(alias, non_temporal, size)} AS {alias}_sample_non_temporal")
    return items


def build_profile_query(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str,
    path_filter: str | None = None,
) -> str:
    """Builds the profile query — the check's backbone.

    Computes, exactly and at any scale: per-column missing counts, per-column type-consistency
    counts with bounded offending-value samples, and row counts both in total and per file.

    The columns profiled are ``profiled_columns``, so a column naming a partition key is profiled
    under its new name in a CSV and gets no figures in JSON or Parquet, never the partition's, and
    the aliases are numbered over that list, which is the one the report numbers them back over.

    Type consistency is skipped entirely for Parquet, and the report records that it was. The
    check is vacuous there, not merely redundant: Parquet enforces types in the format, so a
    numeric column cannot contain stray text and every cast would trivially succeed — emitting
    them over a huge dataset would scan the whole thing to prove something the file format
    already guarantees. Parquet sources still get missing counts, duplicates, row counts, and the
    one that matters most for Parquet, cross-file schema drift.

    Grouping sets rather than a plain grouping: one total row plus one row per source file, in a
    single statement and a single scan, with a flag telling the reader which is which. The path
    pseudo-column must be carried through the inner select to stay groupable outside — drop it
    and the grouping fails at query time, not build time. The cost this accepts, stated plainly,
    is that every per-column aggregate is computed per file as well as globally, so the aggregate
    count scales with the file count — bounded by the object cap, and the alternative of a second
    statement means a second full scan.

    Args:
      database: The target database.
      table_name: The typed temp table.
      columns: The unioned columns, before ``profiled_columns`` maps them.
      partition_keys: The detected partition keys.
      fmt: The source format, which decides whether type consistency is checked.
      path_filter: Restricts the scan to one file. It is what makes a single-file check describe
        the file the user picked: the table's location is the parent folder, because Athena needs
        a prefix and a location is read recursively — so without it every figure here described
        the whole folder while the per-file counts described the one file, and the delivered
        report satisfied neither the user's selection nor its own arithmetic.

    Returns:
      The full statement. Its result set is bounded by files times columns, never by rows, which
      is what makes it safe for the report verb to read whole.

    Raises:
      KeyError: If a column is missing its name or type, or a partition key its name.
    """
    type_checked = fmt != "parquet"
    columns = profiled_columns(columns, partition_keys, fmt)

    projected = ", ".join(
        ['"$path"'] + [_projection(i, column) for i, column in enumerate(columns)]
    )
    items = ['"$path" AS source_file', 'GROUPING("$path") AS is_total', "COUNT(*) AS row_count"]
    for index, column in enumerate(columns):
        items.extend(_column_aggregates(index, column, type_checked))

    selected = ", ".join(items)
    table = f"{ddl.quote_dml(database)}.{ddl.quote_dml(table_name)}"
    return (
        f"SELECT {selected} FROM (SELECT {projected} FROM {table}{_where(path_filter)}) "
        'GROUP BY GROUPING SETS ((), ("$path"))'
    )


def single_file_path(bucket: str, files: list[dict], location: str) -> str | None:
    """Decides whether this check targets exactly one file, and names it if so.

    The single definition of that question, and it is evaluated exactly ONCE per run: by
    inspect-source, over the same in-memory file list the manifest is written from. The
    create verb promotes the location to the parent folder, because an external table's location
    is a prefix and pointing it at an object key gives a table over nothing — but Athena reads a
    location recursively, so that table also covers every sibling in the folder. The queries are
    what re-narrow it, and if the two verbs disagreed about which case this is, the report would
    describe the folder while claiming to describe the file.

    **One definition was not enough; a second READ is a second decision.** Both verbs used to call
    this over the manifest they each loaded, and the manifest sits at a key a caller can predict,
    under a prefix a caller could write. Overwriting it between the two loads with a two-file list
    left the table promoted and the queries unnarrowed — for a file at the space root, a report
    over the whole space. So the answer rides the state as ``pathFilter``, and both verbs read it
    through ``carried_path_filter`` rather than re-deriving it.

    The returned form is not a choice made here: it is what Athena's path pseudo-column returns,
    which is why the ragged mapping is keyed that way and the report reverses it.

    Args:
      bucket: The source bucket.
      files: The manifest's file entries.
      location: The request's target location.

    Returns:
      The full object path, or None for a folder target, a multi-file manifest, or a manifest
      whose single file is not the location itself — in all of which the table's location already
      matches the manifest and no predicate is wanted.

    Raises:
      None.
    """
    keys = [entry["key"] for entry in files if entry.get("key")]
    prefix = location.rstrip("/")
    if keys == [prefix]:
        return f"s3://{bucket}/{prefix}"
    return None


def carried_path_filter(event: dict) -> str | None:
    """Reads the single-file decision inspect-source carried on the state.

    Beside ``single_file_path`` because it is the only way the verbs downstream of inspect-source
    may learn that answer. **A missing key is refused, never read as "a folder".** Every run that
    reaches create went through inspect-source, which always writes the key, so an absent one
    means the state was built by something else — and defaulting it to None is the failure that
    matters, because the promoted table would then be queried with no predicate at all.

    The value is bounded: an ``s3://`` URI over the request's location, which the API caps at
    S3's own key limit, so it rides the state rather than a pointer.

    Args:
      event: The task input.

    Returns:
      The full object path for a single-file check, or None for a folder.

    Raises:
      TerminalError: ``invalid_request`` when the key is absent, or holds anything but None or
        a non-blank string.
    """
    if "pathFilter" not in event:
        raise TerminalError(messages.INVALID_REQUEST, "missing required field 'pathFilter'")
    value = event["pathFilter"]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TerminalError(messages.INVALID_REQUEST, "malformed field 'pathFilter'")
    return value


def _where(path_filter: str | None) -> str:
    """Renders the path restriction, or nothing at all.

    Empty for a folder target, whose table location is already the folder. Each builder takes the
    path filter only through here, so narrowing a check to one file adds this clause to its
    statement and changes nothing else.

    Args:
      path_filter: The single file's path, or None.

    Returns:
      The clause, or "".

    Raises:
      None.
    """
    return f' WHERE "$path" = {_literal_dml(path_filter)}' if path_filter else ""


def _literal_dml(value: str) -> str:
    """Renders a string literal for a DML statement, in Trino's dialect.

    Deliberately not the DDL escaper, and the difference is not stylistic: that one escapes with
    backslashes, which is Hive's rule. Trino has no backslash escape in a plain string literal —
    the only escape is doubling the quote — so the Hive form would render a backslash into the S3
    path being matched and the branch would simply never fire. A path that never matches produces
    no error, just a file's lines silently falling through and going uncounted.

    Args:
      value: The literal to render.

    Returns:
      The quoted, escaped literal.

    Raises:
      None.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def build_ragged_query(
    database: str,
    raw_table_name_: str,
    expected_by_path: dict[str, int],
    path_filter: str | None = None,
) -> str:
    """Builds the ragged-rows query over the raw-line table. CSV only.

    A row is ragged when its field count does not match the header of the file the row came from.
    Splitting the raw line is the only way to see that: by the time the normal SerDe is involved,
    the ragged row has already been parsed away. Comparing against a single union column count
    was the earlier bug — on a folder whose files disagree, every data row of a narrower file was
    counted ragged, and so was every file's header, so the user saw one problem reported twice,
    the second time as a large number describing nothing real. Cross-file disagreement has its own
    finding and remains its only home.

    The count is approximate for two reasons the report must label: splitting on the delimiter
    over-reports a quoted delimiter inside a field, and over-reports an embedded newline inside a
    quoted field, which makes one logical row arrive as two physical lines each with the wrong
    count. A third, inside the same caveat: the expected count comes from a quoting-aware parse
    while this query splits raw text, so a header containing a quoted delimiter counts as ragged
    on a folder where nothing is wrong.

    Blank lines are excluded explicitly. A blank line splits to a single empty field, so on any
    multi-column source every blank line would otherwise be counted ragged, and one stray blank
    line would put a false finding in front of the user. The header itself needs no filter: it
    has its own file's column count by definition, so it is never ragged. It is counted in the
    total, which is why that figure is named for lines rather than rows.

    A path in the scan with no mapping entry is never counted ragged. The raw-line table reads the
    folder while the mapping comes from the manifest, so the two can disagree — an object written
    between the inspection and the query, or one whose header could not be probed. There is no
    expected count for such a line and therefore no basis on which to judge it, and an unjudgeable
    line is not a ragged one. It still counts toward the total.

    Branches are rendered in sorted path order so the query is a pure function of its inputs.
    Every submission carries an idempotency token derived from the request id, and Athena rejects
    a token replayed with different query text — so a retry that re-rendered the branches in
    another order would fail the resubmission instead of re-attaching to the original execution.

    Args:
      database: The target database.
      raw_table_name_: The raw-line temp table.
      expected_by_path: Full object path to that file's own header column count.
      path_filter: Restricts the scan to one file. It bounds both figures, and the total is the
        reason it is needed here: the branch logic already limits which lines can be judged
        ragged, but the denominator counted every line in the folder, so a single-file check
        reported its ragged count against a total describing the file's neighbours.

    Returns:
      The full statement.

    Raises:
      RaggedQueryTooLargeError: When the rendered statement exceeds the query-string cap. The
        guard is on the rendered bytes, never on a file count: an S3 key can be a thousand
        characters or forty, so a count is a poor proxy for the length that actually matters.
    """
    line = ddl.quote_dml(RAW_LINE_COLUMN)
    present = f"{line} IS NOT NULL AND {line} <> ''"
    fields = f"cardinality(split({line}, ','))"

    if expected_by_path:
        branches = " ".join(
            f"WHEN {_literal_dml(path)} THEN {fields} <> {count}"
            for path, count in sorted(expected_by_path.items())
        )
        ragged = f'CASE "$path" {branches} ELSE false END'
    else:
        ragged = "false"

    query = (
        f"SELECT COUNT_IF({present} AND {ragged}) AS ragged_rows, "
        f"COUNT_IF({present}) AS total_lines "
        f"FROM {ddl.quote_dml(database)}.{ddl.quote_dml(raw_table_name_)}"
        f"{_where(path_filter)}"
    )

    rendered = len(query.encode())
    if rendered > config.DQ_MAX_QUERY_BYTES:
        raise RaggedQueryTooLargeError(
            f"ragged query is {rendered} bytes over {len(expected_by_path)} mapped files, "
            f"past DQ_MAX_QUERY_BYTES={config.DQ_MAX_QUERY_BYTES}"
        )
    return query


def build_duplicates_query(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str | None,
    path_filter: str | None = None,
) -> str:
    """Builds the duplicate-rows query.

    Its own statement, never merged into the profile query. Grouping over every column of a huge
    table is a full shuffle — the single most expensive operation Athena offers, and a realistic
    way to exhaust query resources. It also simply cannot run over a JSON source with a
    MAP-typed column, which is not groupable in Trino, so that degradation is expected on any
    JSON source carrying a nested object rather than a sign of a bug. Isolated, either failure
    degrades one figure of the report; merged, it would destroy every other finding with it.

    The result shape is pinned to exactly one row, which is what lets the report verb read the
    result file whole without a bound. Partition columns are included in the grouping because
    they are part of the row: two otherwise-identical rows in different partitions are different
    rows, not duplicates. The data columns are ``profiled_columns``, the list the temp table's DDL
    declares, so a data column naming a partition key is grouped under its new name in a CSV and
    left out in JSON or Parquet, and the grouping never names one column under two spellings.

    Args:
      database: The target database.
      table_name: The typed temp table.
      columns: The unioned columns.
      partition_keys: The detected partition keys.
      fmt: The source format, passed to ``profiled_columns``.
      path_filter: Restricts the scan to one file. Without it a single-file check reported
        duplicates found between that file and its neighbours, which is not a duplicate the user
        can act on.

    Returns:
      The full statement.

    Raises:
      KeyError: If a column or partition key is missing its name.
    """
    grouped = [ddl.quote_dml(c["name"]) for c in profiled_columns(columns, partition_keys, fmt)]
    grouped.extend(ddl.quote_dml(key["name"]) for key in partition_keys)
    all_columns = ", ".join(grouped)
    table = f"{ddl.quote_dml(database)}.{ddl.quote_dml(table_name)}"

    return (
        "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM "
        f"(SELECT COUNT(*) AS cnt FROM {table}{_where(path_filter)} "
        f"GROUP BY {all_columns} HAVING COUNT(*) > 1)"
    )
