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
            DATABASE, TABLE, COLUMNS, [], path_filter
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
        "duplicates": (
            f'(SELECT COUNT(*) AS cnt FROM "team""data"."{TABLE}" '
            'GROUP BY "he said ""hi""", "n""1", "the ""year""" HAVING'
        ),
    }

    rendered = {
        "profile": sql.build_profile_query(
            database, TABLE, columns, partition_keys, "csv"
        ),
        "ragged": sql.build_ragged_query(database, RAW_TABLE, {}),
        "duplicates": sql.build_duplicates_query(
            database, TABLE, columns, partition_keys
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
