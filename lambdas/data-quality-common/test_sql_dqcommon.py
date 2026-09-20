"""Unit tests for dqcommon.sql's statements: each dialect's escaping, and the profile query's size.

Pure: no AWS. Athena parses the three queries as Trino and the drop statement as Hive, and
``cpcommon.ddl`` keeps both dialects' escapers side by side, so every site that renders a value
here can reach for the wrong one. A string literal escaped by either rule is the same text unless
the value holds an apostrophe or a backslash, and an identifier's escaping differs only on a name
holding a quote, so the fixtures carry those characters: a plain one cannot tell a right escaper
from a wrong one.

A path parts from Hive's rule on exactly those two characters, both legal in an S3 key. Trino's
only escape in a plain string literal is a doubled quote, and a backslash is an ordinary
character. So the Hive form of an apostrophe, a backslash before the quote, ends the literal early
and leaves the rest of the path to be parsed as SQL; and the Hive form of a backslash, doubled, is
a different path that matches nothing, which Athena does not report — the file's lines just go
uncounted.

Every escaped expectation is spelled out by hand rather than built with an escaper, since a test
that escapes its own expectation agrees with whatever the code under test does.

Attributes:
  BUCKET: The source bucket every path is built in.
  DATABASE: The temp tables' database.
  TABLE: The typed temp table.
  RAW_TABLE: The raw-line temp table.
  COLUMNS: The unioned columns of every one-file manifest here.
  _ATHENA_QUERY_STRING_LIMIT: Athena's hard limit on a query string, in bytes. Spelled out rather
    than read from ``config.DQ_MAX_QUERY_BYTES``: the size test holds the query to Athena's limit,
    and one measured against the setting would pass however far a mistake raised it.
  _KEYS: An object key for each character the two literal escapers disagree on, paired with the
    Trino literal that equals that key's full object path.
"""

import pytest
from cpcommon.columns import MAX_COLUMN_NAME_LENGTH
from dqcommon import config, sql

BUCKET = "dq-user-bkt"
DATABASE = "alice"
TABLE = "dq_tmp_7f3ac19d2b4e4c8a9f016d5e3a7b8c02"
RAW_TABLE = "dq_tmp_raw_7f3ac19d2b4e4c8a9f016d5e3a7b8c02"
COLUMNS = [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}]
_ATHENA_QUERY_STRING_LIMIT = 262_144

_KEYS = pytest.mark.parametrize(
    ("key", "literal"),
    [
        (
            "alice/sales/it''s o'brien.csv",
            "'s3://dq-user-bkt/alice/sales/it''''s o''brien.csv'",
        ),
        ("alice/sales/q3\\final.csv", "'s3://dq-user-bkt/alice/sales/q3\\final.csv'"),
    ],
    ids=[
        "every apostrophe is doubled, never backslash-escaped",
        "a backslash is left alone, never doubled",
    ],
)


def _renders(path_filter: str | None, path: str) -> dict[str, str]:
    """Renders the three queries the start verb submits, over a manifest of one file.

    Args:
      path_filter: The single-file predicate's path, or None for a folder target.
      path: The file's full object path, which keys the ragged query's per-file branch.

    Returns:
      Each query's name mapped to its rendered statement.

    Raises:
      None.
    """
    return {
        "profile": sql.build_profile_query(
            DATABASE, TABLE, COLUMNS, [], "csv", path_filter
        ),
        "ragged": sql.build_ragged_query(
            DATABASE, RAW_TABLE, {path: len(COLUMNS)}, path_filter
        ),
        "duplicates": sql.build_duplicates_query(
            DATABASE, TABLE, COLUMNS, [], "csv", path_filter
        ),
    }


@_KEYS
def test_a_single_file_check_compares_the_path_as_a_trino_literal(key, literal):
    """Narrows each of the three queries with a predicate Trino reads as the selected file's path.

    The path comes from ``single_file_path``, the decision inspect-source makes and the start verb
    carries to the queries, so the test covers the route from a selected key to the rendered
    clause. The predicate must also be the ONLY
    difference from the folder render: a clause that carried a stray quote after the right literal
    would otherwise pass on the strength of containing it.

    Args:
      key: The selected object's key.
      literal: The Trino literal its full object path must render as.

    Returns:
      None.

    Raises:
      None.
    """
    files = [{"key": key, "size": 1, "columns": COLUMNS}]
    path = f"s3://{BUCKET}/{key}"
    clause = f' WHERE "$path" = {literal}'
    folder = _renders(None, path)

    narrowed = _renders(sql.single_file_path(BUCKET, files, key), path)

    for name, query in narrowed.items():
        assert clause in query, name
        assert query.replace(clause, "", 1) == folder[name], name


@_KEYS
def test_a_ragged_branch_is_keyed_by_the_path_as_a_trino_literal(key, literal):
    """Keys the ragged query's per-file branch with a literal Trino reads as that file's path.

    The branch is how a line is judged against its own file's header. One keyed by a doubled
    backslash is never taken, so every line of that file falls to the ELSE and is counted as not
    ragged whatever its field count. A folder check is the case to drive, because there the branch
    is the only place the path is rendered at all.

    Args:
      key: An object key in the checked folder.
      literal: The Trino literal its full object path must render as.

    Returns:
      None.

    Raises:
      None.
    """
    path = f"s3://{BUCKET}/{key}"

    query = sql.build_ragged_query(DATABASE, RAW_TABLE, {path: len(COLUMNS)})

    assert f'CASE "$path" WHEN {literal} THEN ' in query


def test_every_identifier_in_the_three_queries_is_quoted_for_trino():
    """Double-quotes each database, table, column and partition-key name, doubling a quote inside.

    Athena documents double quotes for an identifier in a SELECT and backticks only for DDL, so
    the DDL quoter at any of these sites breaks the query when it runs, not when it is built. The
    database, both columns and the partition key each carry a double quote for the escaping, and
    the generated table names are plain. One column is typed because the projection renders a
    typed column on a branch of its own. create-temp-tables refuses such a column or partition-key
    name before any query is built, while a shared check's database is the space's own name. The
    renderer is held to its own escaping whichever of them can arrive, because one that is only
    safe while an earlier step validates is a refactor away from not being safe.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    database = 'team"data'
    columns = [
        {"name": 'he said "hi"', "type": "string"},
        {"name": 'n"1', "type": "bigint"},
    ]
    partition_keys = [{"name": 'the "year"', "values": ["2026"]}]
    expected = {
        "profile": (
            '(SELECT "$path", NULLIF(TRIM("he said ""hi"""), \'\') AS c0, "n""1" AS c1 '
            f'FROM "team""data"."{TABLE}")'
        ),
        "ragged": (
            'COUNT_IF("line" IS NOT NULL AND "line" <> \'\') AS total_lines '
            f'FROM "team""data"."{RAW_TABLE}"'
        ),
        # Each grouped name is rendered TWICE now — once aliased into the projection the samples
        # read, once in the grouping — so the fragment covers both sites rather than the older one.
        "duplicates": (
            '(SELECT COUNT(*) AS cnt, "he said ""hi""" AS c0, "n""1" AS c1, '
            f'"the ""year""" AS c2 FROM "team""data"."{TABLE}" '
            'GROUP BY "he said ""hi""", "n""1", "the ""year""" HAVING'
        ),
    }

    rendered = {
        "profile": sql.build_profile_query(
            database, TABLE, columns, partition_keys, "csv"
        ),
        "ragged": sql.build_ragged_query(database, RAW_TABLE, {}),
        "duplicates": sql.build_duplicates_query(
            database, TABLE, columns, partition_keys, "csv"
        ),
    }

    for name, fragment in expected.items():
        assert fragment in rendered[name], name


def test_the_drop_statement_quotes_each_name_for_hive():
    """Quotes the drop statement's names in Hive's backticks, doubling one inside.

    The mirror of the queries: Athena documents backticks for an identifier in DDL, and a DROP is
    DDL, so here the backtick is the right quote. The database carries a backtick for the
    escaping, since a plain name cannot tell an escaped quote from a bare one.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    database = "team`data"

    statement = sql.build_drop_table_ddl(database, TABLE)

    assert statement == f"DROP TABLE IF EXISTS `team``data`.`{TABLE}`"


def test_the_profile_query_fits_athenas_query_string_limit_at_the_column_cap():
    """Holds a profile query at the column cap within the query-string limit Athena enforces.

    Athena refuses an over-length statement only when it runs, after every step before it has
    been paid for, so the column cap keeps a check out of that failure only while the query it
    admits still fits. Every part the checked files can lengthen is at its longest: every column a
    string in a type-checked format, so each carries its cast counts and both samples; every name
    as long as the column rule admits; and a single-file predicate over an object key of S3's
    maximum length, made of apostrophes because the literal doubles each one. The database and
    bucket names stay short, since each appears once and is bounded far inside the headroom. Every
    column is counted in the result before the size is trusted, since a query that lost columns
    would fit for the wrong reason.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    widest = [
        {
            "name": f"{index:03d}".ljust(MAX_COLUMN_NAME_LENGTH, "x"),
            "type": "string",
        }
        for index in range(config.DQ_MAX_COLUMNS)
    ]
    path_filter = f"s3://{BUCKET}/" + "'" * 1024

    query = sql.build_profile_query(DATABASE, TABLE, widest, [], "csv", path_filter)

    assert query.count("_sample_non_temporal") == config.DQ_MAX_COLUMNS
    assert len(query.encode()) <= _ATHENA_QUERY_STRING_LIMIT, len(query.encode())


# ── The duplicates statement's samples ──────────────────────────────────────

_SAMPLE_COLUMNS = [
    {"name": "name", "type": "string"},
    {"name": "cnt", "type": "string"},
    {"name": "duplicate_rows", "type": "bigint"},
]
_SAMPLE_KEYS = [{"name": "year", "values": ["2026"]}]


def _duplicates(columns, partition_keys, fmt, path_filter=None) -> str:
    """Renders the duplicates statement over one source shape.

    Args:
      columns: The unioned columns.
      partition_keys: The detected partition keys.
      fmt: The source format.
      path_filter: The single-file predicate's path, or None.

    Returns:
      The rendered statement.

    Raises:
      None.
    """
    return sql.build_duplicates_query(
        DATABASE, TABLE, columns, partition_keys, fmt, path_filter
    )


def test_the_duplicates_statement_samples_rows_under_names_no_source_column_can_hold():
    """Pins the whole statement, over a source whose columns are named after its own outputs.

    Spelled out as one string rather than probed for fragments: the criterion is that no layer's
    output name is a source column's, and a fragment test cannot see a name that appears in a
    layer it did not quote. The source is named adversarially — ``name``, and the statement's own
    ``cnt`` and ``duplicate_rows`` — because a builder that projected a grouped column under its own
    name would render a statement Athena still parses, with two columns called ``cnt`` and the
    sample reading whichever one the engine bound.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    query = _duplicates(_SAMPLE_COLUMNS, _SAMPLE_KEYS, "csv")

    assert query == (
        "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows, "
        "json_format(CAST(max_by(sample, sample_key, 5) AS JSON)) AS duplicate_samples FROM "
        "(SELECT cnt, sample, lpad(CAST(cnt AS varchar), 19, '0') "
        "|| json_format(CAST(sample AS JSON)) AS sample_key FROM "
        "(SELECT cnt, ARRAY[CAST(cnt AS varchar), "
        "substr(CAST(c0 AS varchar), 1, 201), "
        "substr(CAST(c1 AS varchar), 1, 201), "
        "substr(CAST(c2 AS varchar), 1, 201), "
        "substr(CAST(c3 AS varchar), 1, 201)] AS sample FROM "
        '(SELECT COUNT(*) AS cnt, "name" AS c0, "cnt" AS c1, "duplicate_rows" AS c2, '
        f'"year" AS c3 FROM "{DATABASE}"."{TABLE}" '
        'GROUP BY "name", "cnt", "duplicate_rows", "year" HAVING COUNT(*) > 1)))'
    )
    # The names are projected INTO the statement and never out of it: each appears only as the
    # right-hand side of an alias, so nothing downstream can bind to a source column's own name.
    for name in ('"name" AS', '"cnt" AS', '"duplicate_rows" AS'):
        assert query.count(name) == 1, name
    assert ' AS "' not in query


def test_the_duplicates_statement_keeps_a_bounded_accumulator():
    """Holds the sample to an n-ary max-by, which is the only aggregate here that is bounded.

    ``array_agg`` over the same rows would accumulate every duplicate GROUP — every column of it —
    on exactly the datasets that have the most duplicates, and fail the query instead of sampling
    it. The absence is asserted rather than assumed because the two read almost identically at the
    call site, and the failure only appears at a scale no test runs at.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    query = _duplicates(_SAMPLE_COLUMNS, _SAMPLE_KEYS, "csv")

    assert query.count("max_by(") == 1
    assert "array_agg(" not in query


def test_the_duplicates_count_and_grouping_are_unchanged_by_the_samples():
    """Holds the count, grouping and filter byte-identical to the statement that shipped before.

    The samples are an addition, and the figure they sit beside is the one users already act on.
    Each clause is spelled out here rather than compared against another call of the builder, since
    a builder compared with itself agrees however both halves moved.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    query = _duplicates(_SAMPLE_COLUMNS, _SAMPLE_KEYS, "csv")

    assert "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows" in query
    assert (
        'GROUP BY "name", "cnt", "duplicate_rows", "year" HAVING COUNT(*) > 1' in query
    )
    assert "SELECT COUNT(*) AS cnt," in query

    narrowed = _duplicates(
        _SAMPLE_COLUMNS, _SAMPLE_KEYS, "csv", "s3://b/alice/sales/jan.csv"
    )

    assert ' WHERE "$path" = \'s3://b/alice/sales/jan.csv\' GROUP BY "name"' in narrowed


@pytest.mark.parametrize(
    "column_type", ["string", "bigint", "date", "timestamp", "decimal(10,2)"]
)
def test_every_scalar_type_is_rendered_through_one_cast_to_varchar(column_type):
    """Renders each scalar column's value as Trino's own text, whatever its declared type.

    One cast covers every scalar family, which is what lets the sample show what the engine holds
    rather than a reformatted number — a ``double`` reads ``1.5E0`` here, as it does in the Data
    Explorer. Parametrised over the families the temp table can declare, since a builder that
    branched on type would work for the one a hand-written test happened to pick.

    Args:
      column_type: The column's declared type.

    Returns:
      None.

    Raises:
      None.
    """
    query = _duplicates([{"name": "v", "type": column_type}], [], "csv")

    assert "substr(CAST(c0 AS varchar), 1, 201)" in query


@pytest.mark.parametrize(
    "nested_type",
    ["array<string>", "struct<a:string,b:bigint>"],
    ids=["a list column", "an object column"],
)
def test_a_nested_column_keeps_the_statement_that_already_worked(nested_type):
    """Leaves a source holding a list or an object with today's statement, byte for byte.

    Trino documents no cast from an array or a row to varchar, and a cast the engine refuses fails
    the whole statement — which would trade the duplicate count that works today for a sample. The
    expected string is written out rather than taken from a second builder call, so a change that
    moved both arms together would still be visible here.

    Both nested families are exercised, because ``_NESTED_TYPES`` names two prefixes and a test of
    one cannot see the other go missing: dropping ``struct<`` sends a Parquet source with an object
    column down the sampling arm, where ``CAST(struct AS varchar)`` fails the whole statement and
    takes the duplicate count with it.

    Args:
      nested_type: The declared type of the column the statement must refuse to render.

    Returns:
      None.

    Raises:
      None.
    """
    nested = [
        {"name": "id", "type": "bigint"},
        {"name": "tags", "type": nested_type},
    ]

    query = _duplicates(nested, _SAMPLE_KEYS, "json")

    assert query == (
        "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM "
        f'(SELECT COUNT(*) AS cnt FROM "{DATABASE}"."{TABLE}" '
        'GROUP BY "id", "tags", "year" HAVING COUNT(*) > 1)'
    )
    assert "duplicate_samples" not in query


@pytest.mark.parametrize(
    ("fmt", "expected", "grouped"),
    [
        ("json", ["id", "year", "Month"], '"id", "year", "Month"'),
        (
            "csv",
            ["id", "month_in_file", "year_in_file", "year", "Month"],
            '"id", "month_in_file", "year_in_file", "year", "Month"',
        ),
    ],
    ids=[
        "json drops a column naming a partition",
        "csv keeps it in place under a new name",
    ],
)
def test_the_grouped_names_and_the_statement_agree_on_a_partition_named_column(
    fmt, expected, grouped
):
    """Holds the exported grouping list and the rendered GROUP BY to the same answer.

    The list exists so the report can head its sample columns with it, and the only thing that
    makes that safe is that the statement groups by exactly it. Asserted together, in one test,
    because the failure this guards against is the two agreeing separately with two different
    lists — each half passing its own test while a value sits under its neighbour's header.

    The inputs are a source whose header names its own partitions: ``month`` beside the key
    ``Month``, ``Year`` beside ``year``. A CSV is read by position so both are kept under new
    names; JSON is read by name so both are left out and the keys stand in their place.

    Args:
      fmt: The source format.
      expected: The names ``grouped_column_names`` must return.
      grouped: The GROUP BY clause the statement must render.

    Returns:
      None.

    Raises:
      None.
    """
    columns = [
        {"name": "id", "type": "bigint"},
        {"name": "month", "type": "string"},
        {"name": "Year", "type": "string"},
    ]
    partition_keys = [
        {"name": "year", "values": ["2026"]},
        {"name": "Month", "values": ["01"]},
    ]

    assert sql.grouped_column_names(columns, partition_keys, fmt) == expected
    assert f"GROUP BY {grouped} HAVING" in _duplicates(columns, partition_keys, fmt)


def test_the_duplicates_query_fits_athenas_query_string_limit_at_the_column_cap():
    """Holds a duplicates query at the column cap within the query-string limit Athena enforces.

    The sibling of the profile query's size test, and owed for the same reason: the samples take
    every column from ONE rendering to four — the quoted name twice, in the projection and the
    GROUP BY, and the positional alias twice, in the array and nowhere else — and Athena refuses
    an over-length statement only when it runs, after every step before it has been paid for. Every
    part the checked source can lengthen is at its longest — every name as long as the column rule
    admits, the cap's worth of them, two partition keys, and a single-file predicate over an object
    key of S3's maximum length made of apostrophes, because the literal doubles each one.

    The column count is asserted before the size, since a query that lost columns would fit for the
    wrong reason.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    widest = [
        {"name": f"{index:03d}".ljust(MAX_COLUMN_NAME_LENGTH, "x"), "type": "string"}
        for index in range(config.DQ_MAX_COLUMNS)
    ]
    keys = [
        {"name": f"k{index}".ljust(MAX_COLUMN_NAME_LENGTH, "z"), "values": ["2026"]}
        for index in range(2)
    ]
    path_filter = f"s3://{BUCKET}/" + "'" * 1024

    query = _duplicates(widest, keys, "csv", path_filter)

    assert query.count("substr(CAST(c") == config.DQ_MAX_COLUMNS + len(keys)
    assert len(query.encode()) <= _ATHENA_QUERY_STRING_LIMIT, len(query.encode())
