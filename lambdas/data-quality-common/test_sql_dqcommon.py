"""Golden-string tests for the data-quality SQL builders (SPEC-111).

Pure — no AWS. Golden strings rather than "contains" assertions wherever the exact SQL
matters, because a subtly wrong query in this module does not crash: it reports the wrong
numbers about a user's data, and the user acts on them.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest
from dqcommon import config, sql

REQUEST_ID = "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
HEX32 = "7f3ac19d2b4e4c8a9f016d5e3a7b8c02"
LOC = "s3://dat-prod-user-space/alice/sales/"


# ── Naming (FR-001) ──────────────────────────────────────────────────────────


def test_temp_table_name_matches_the_safe_identifier_shape():
    """^dq_tmp_[0-9a-f]{32}$ — the shape the spec pins by test.

    Both rejected alternatives fail LATE (after the table exists, at query time), which
    is why this is asserted rather than assumed: a leading underscore would force
    backticks everywhere, and a raw UUID's hyphens parse as subtraction.
    """
    name = sql.temp_table_name(REQUEST_ID)
    assert re.match(r"^dq_tmp_[0-9a-f]{32}$", name), name
    assert name == f"dq_tmp_{HEX32}"


def test_raw_table_name_matches_the_same_rule():
    name = sql.raw_table_name(REQUEST_ID)
    assert re.match(r"^dq_tmp_raw_[0-9a-f]{32}$", name), name


def test_table_names_carry_no_hyphens():
    """The specific defect the naming rule exists to prevent."""
    assert "-" not in sql.temp_table_name(REQUEST_ID)
    assert "-" not in sql.raw_table_name(REQUEST_ID)


def test_table_names_are_a_pure_function_of_the_request_id():
    """A Step Functions Retry must rebuild the SAME name, or cleanup loses the table."""
    assert sql.temp_table_name(REQUEST_ID) == sql.temp_table_name(REQUEST_ID)
    assert sql.temp_table_name(REQUEST_ID) != sql.temp_table_name("00000000-0000-0000-0000-000000000001")


# ── The typed table (FR-001) ─────────────────────────────────────────────────


def test_csv_temp_table_is_all_string_with_a_header_skip():
    ddl = sql.build_temp_table_ddl(
        "alice", "dq_tmp_x",
        [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        [], "csv", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`dq_tmp_x` "
        "(`order_id` string, `amount` string) "
        "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
        "WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') "
        "STORED AS TEXTFILE "
        "LOCATION 's3://dat-prod-user-space/alice/sales/' "
        "TBLPROPERTIES ('skip.header.line.count'='1')"
    )


def test_json_temp_table_uses_the_HIVE_serde_not_openx():
    """The one that would poison every JSON report silently if it regressed.

    AWS documents OpenX as potentially non-deterministic around nulls, and this arc's
    whole JSON story is "a null means the key was missing" — so a report built on OpenX
    would look clean and be wrong.
    """
    ddl = sql.build_temp_table_ddl(
        "alice", "dq_tmp_x", [{"name": "id", "type": "bigint"}], [], "json", LOC,
    )
    assert "org.apache.hive.hcatalog.data.JsonSerDe" in ddl
    assert "openx" not in ddl.lower()


def test_parquet_temp_table_is_stored_as_parquet():
    ddl = sql.build_temp_table_ddl(
        "alice", "dq_tmp_x", [{"name": "id", "type": "bigint"}], [], "parquet", LOC,
    )
    assert "STORED AS PARQUET" in ddl
    assert "ROW FORMAT SERDE" not in ddl


def test_partitioned_source_uses_projection_and_never_msck():
    keys = [{"name": "year", "values": ["2024", "2025"]}, {"name": "region", "values": ["eu"]}]
    ddl = sql.build_temp_table_ddl(
        "alice", "dq_tmp_x", [{"name": "id", "type": "string"}], keys, "csv", LOC,
    )
    assert "PARTITIONED BY (`year` string, `region` string)" in ddl
    assert "'projection.enabled'='true'" in ddl
    assert "'projection.year.type'='enum'" in ddl
    assert "'projection.year.values'='2024,2025'" in ddl
    assert "'projection.region.values'='eu'" in ddl
    assert "MSCK" not in ddl.upper()


def test_temp_table_creation_is_idempotent():
    """IF NOT EXISTS is what makes a Step Functions Retry a no-op."""
    ddl = sql.build_temp_table_ddl("alice", "t", [{"name": "id", "type": "string"}], [], "csv", LOC)
    assert ddl.startswith("CREATE EXTERNAL TABLE IF NOT EXISTS ")


def test_unknown_format_is_refused():
    with pytest.raises(ValueError, match="avro"):
        sql.build_temp_table_ddl("alice", "t", [{"name": "id", "type": "string"}], [], "avro", LOC)


# ── The raw-line table (FR-002) ──────────────────────────────────────────────


def test_raw_table_uses_lazysimple_with_an_soh_delimiter_and_no_header_skip():
    ddl = sql.build_raw_table_ddl("alice", "dq_tmp_raw_x", LOC)
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`dq_tmp_raw_x` (`line` string) "
        "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe' "
        "WITH SERDEPROPERTIES ('field.delim'='\\001') STORED AS TEXTFILE "
        "LOCATION 's3://dat-prod-user-space/alice/sales/'"
    )
    # No header skip: EVERY physical line must arrive, including the header, or the
    # ragged count is off by one and the "exclude the header" clause double-counts.
    assert "skip.header.line.count" not in ddl


def test_raw_table_delimiter_is_an_escape_sequence_never_a_literal_control_byte():
    """The defect this pins: an invisible 0x01 survives no diff review or copy-paste.

    If it degraded to a literal byte (or to something else entirely, which is the real
    failure mode), the ragged check would split on a delimiter that DOES occur in the
    data and every row would look ragged.
    """
    ddl = sql.build_raw_table_ddl("alice", "raw", LOC)
    assert "\\001" in ddl               # the four characters backslash-zero-zero-one
    assert "\x01" not in ddl            # never the actual control byte
    # And the same holds of the module source itself, which is where a bad paste lands.
    source = Path(sql.__file__).read_text(encoding="utf-8")
    assert "\x01" not in source


def test_raw_table_is_flat_even_when_the_source_is_partitioned():
    """Deliberately no projection: a flat external table reads every object recursively,
    which is exactly what "count every physical line" needs."""
    ddl = sql.build_raw_table_ddl("alice", "raw", LOC)
    assert "PARTITIONED BY" not in ddl
    assert "projection" not in ddl


# ── The column union + the width cap (FR-001) ────────────────────────────────


def test_union_columns_takes_every_files_columns_in_first_seen_order():
    files = [
        {"columns": [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}]},
        {"columns": [{"name": "b", "type": "string"}, {"name": "c", "type": "string"}]},
    ]
    assert [c["name"] for c in sql.union_columns(files)] == ["a", "b", "c"]


def test_union_columns_keeps_the_first_seen_type_on_a_conflict():
    files = [
        {"columns": [{"name": "id", "type": "bigint"}]},
        {"columns": [{"name": "id", "type": "string"}]},
    ]
    assert sql.union_columns(files) == [{"name": "id", "type": "bigint"}]


def test_union_columns_tolerates_a_file_with_no_columns():
    assert sql.union_columns([{"key": "a.csv"}]) == []


def test_column_count_cap_allows_exactly_the_limit():
    columns = [{"name": f"c{i}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS)]
    sql.check_column_count(columns)  # must not raise


def test_column_count_cap_rejects_one_over():
    columns = [{"name": f"c{i}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS + 1)]
    with pytest.raises(sql.TooManyColumnsError, match=str(config.DQ_MAX_COLUMNS)):
        sql.check_column_count(columns)


# ── The drop (FR-005) ────────────────────────────────────────────────────────


def test_drop_is_idempotent():
    assert sql.build_drop_table_ddl("alice", "dq_tmp_x") == "DROP TABLE IF EXISTS `alice`.`dq_tmp_x`"


# ── The profile query (FR-003) ───────────────────────────────────────────────

STR_COLS = [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}]


def test_profile_query_counts_failures_for_all_four_casts():
    q = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    for cast in ("BIGINT", "DOUBLE", "TIMESTAMP", "DATE"):
        assert f"TRY_CAST(c0 AS {cast}) IS NULL" in q
    assert "c0_not_bigint" in q and "c1_not_date" in q


def test_profile_query_counts_null_and_blank_as_missing():
    """The inner projection folds null-and-blank into one NULL, so the outer aggregate
    is a plain IS NULL — and every downstream predicate inherits the same definition."""
    q = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    assert 'NULLIF(TRIM("order_id"), \'\') AS c0' in q
    assert "COUNT_IF(c0 IS NULL) AS c0_missing" in q


def test_profile_query_uses_grouping_sets_for_per_file_and_total_counts():
    """A plain GROUP BY would give per-file counts and NO total — the false start the
    spec calls out."""
    q = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    assert 'GROUP BY GROUPING SETS ((), ("$path"))' in q
    assert '"$path" AS source_file' in q
    assert 'GROUPING("$path") AS is_total' in q
    assert "COUNT(*) AS row_count" in q


def test_profile_query_skips_type_checks_entirely_for_parquet():
    """VACUOUS, not merely redundant: Parquet enforces types in the format, so every
    TRY_CAST would trivially succeed — and prove it by scanning 250 GB.

    THE COLUMN HERE IS DELIBERATELY A STRING. With a bigint column this test passes for
    the WRONG REASON — the non-string rule already suppresses the casts, so the Parquet
    branch is never exercised and deleting it changes nothing. (That is exactly what
    happened: mutation-testing `type_checked = fmt != "parquet"` to `True` left the
    original version of this test green.) A string column is the only shape that isolates
    the format rule from the type rule.
    """
    q = sql.build_profile_query("alice", "t", [{"name": "note", "type": "string"}], "parquet")
    assert "TRY_CAST" not in q
    assert "sample_non_numeric" not in q
    # Missing counts and row counts still land — those are not vacuous for Parquet.
    assert "c0_missing" in q
    assert "COUNT(*) AS row_count" in q


def test_the_same_string_column_IS_type_checked_for_csv():
    """The other half of the pair: identical column, different format, opposite outcome.

    Without this, the test above could pass because the builder emits no casts at all.
    """
    q = sql.build_profile_query("alice", "t", [{"name": "note", "type": "string"}], "csv")
    assert "TRY_CAST(c0 AS BIGINT)" in q
    assert "c0_sample_non_numeric" in q


def test_profile_query_skips_type_checks_for_non_string_columns():
    """A bigint column cannot hold a value that fails TRY_CAST to BIGINT."""
    q = sql.build_profile_query(
        "alice", "t", [{"name": "id", "type": "bigint"}, {"name": "note", "type": "string"}], "json"
    )
    assert "TRY_CAST(c0 AS BIGINT)" not in q   # the bigint column
    assert "TRY_CAST(c1 AS BIGINT)" in q       # the string column
    # A non-string column is projected through untouched — TRIM is a string function —
    # but still gets a missing count. For JSON that IS the key-drift check, since the
    # Hive SerDe yields null for a missing key.
    assert '"id" AS c0' in q
    assert "COUNT_IF(c0 IS NULL) AS c0_missing" in q


def test_profile_query_sample_aggregate_is_bounded():
    """max_by(v, k, N) holds N values; array_agg-then-slice accumulates O(rows) and
    fails the query on a badly-typed 250 GB column instead of sampling it."""
    q = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    assert "max_by(" in q
    assert f", {config.DQ_OFFENDING_VALUE_SAMPLE})" in q
    assert "array_agg" not in q


def test_profile_query_emits_both_sample_families():
    q = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    assert "c0_sample_non_numeric" in q
    assert "c0_sample_non_temporal" in q


def test_profile_query_aliases_columns_positionally():
    """Positional aliases: a user's column name can need quoting or collide after
    normalisation, and neither would show up until the report was assembled."""
    q = sql.build_profile_query("alice", "t", [{"name": "weird name!", "type": "string"}], "csv")
    assert "c0_missing" in q
    assert "weird name!_missing" not in q


def test_profile_query_stays_under_athenas_query_string_cap_at_the_column_cap():
    """The cap exists to keep this true — assert it rather than trust the arithmetic.

    Athena rejects a query string over 262,144 bytes, and it does so AFTER all the
    inspection work is done.
    """
    columns = [{"name": f"column_number_{i:03d}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS)]
    q = sql.build_profile_query("alice", "dq_tmp_x", columns, "csv")
    assert len(q.encode()) < config.DQ_MAX_QUERY_BYTES, len(q.encode())


# ── The ragged query (FR-003) ────────────────────────────────────────────────


ONE_FILE = {"s3://bkt/alice/sales/jan.csv": 5}


def test_ragged_query_counts_rows_whose_field_count_differs():
    q = sql.build_ragged_query("alice", "dq_tmp_raw_x", ONE_FILE)
    assert q == (
        'SELECT COUNT_IF("line" IS NOT NULL AND "line" <> \'\' AND CASE "$path" '
        "WHEN 's3://bkt/alice/sales/jan.csv' THEN cardinality(split(\"line\", ',')) <> 5 "
        "ELSE false END) AS ragged_rows, "
        'COUNT_IF("line" IS NOT NULL AND "line" <> \'\') AS total_lines '
        'FROM "alice"."dq_tmp_raw_x"'
    )


def test_ragged_query_compares_each_line_against_its_own_files_count():
    """SPEC-142 FR-001 — the bug this replaced compared every line against the UNION count,
    so every data row of a narrower file, AND every file's header, was counted ragged."""
    q = sql.build_ragged_query(
        "alice", "raw", {"s3://bkt/a.csv": 3, "s3://bkt/b.csv": 5}
    )
    assert "WHEN 's3://bkt/a.csv' THEN cardinality(split(\"line\", ',')) <> 3" in q
    assert "WHEN 's3://bkt/b.csv' THEN cardinality(split(\"line\", ',')) <> 5" in q


def test_ragged_query_renders_branches_in_sorted_order():
    """The query must be a PURE FUNCTION of its inputs: every submission carries a
    ClientRequestToken derived from the requestId, and Athena rejects a token replayed with
    different text — so a Retry that re-rendered the branches in another order would fail
    the resubmission instead of re-attaching to the original execution."""
    # EQUAL counts, deliberately: with 3-and-5 any sort key that happens to be total-ordered
    # on the fixture passes, so a refactor keying the sort on the COUNT would slip through —
    # and files that agree about their columns are the ordinary case.
    forward = sql.build_ragged_query("alice", "raw", {"s3://bkt/a.csv": 3, "s3://bkt/b.csv": 3})
    reversed_ = sql.build_ragged_query("alice", "raw", {"s3://bkt/b.csv": 3, "s3://bkt/a.csv": 3})
    assert forward == reversed_
    assert forward.index("a.csv") < forward.index("b.csv")


# ── Evaluating the emitted rule (SPEC-142 FR-004/FR-005) ────────────────────
#
# A golden string proves the query is the one we meant to write. It does NOT prove the
# query counts the right lines — and that is the whole of SPEC-142. So these helpers parse
# the emitted predicate back out and apply it to physical lines the way the SQL does.
#
# EVERY CLAUSE IS DERIVED FROM THE QUERY, NEVER ASSUMED — the per-path counts, the
# fallback, AND the blank-line exclusion. Two earlier revisions each hard-coded one clause
# and each became untestable in exactly the same way: the first assumed "unmapped means not
# ragged", so `ELSE true` left the FR-004 test green; the second assumed blank lines are
# skipped, so deleting the exclusion from the query left every derived test green. A helper
# that models a clause instead of reading it is the same tautology as a test that feeds in
# its own answer, and it is worth restating because this file has now made that mistake
# twice.
#
# The parse is also what makes these fail against the pre-fix builder, which took a scalar
# and rendered no branches at all: `_rendered_rule` returns an empty mapping there.

_BRANCH = re.compile(
    r"WHEN '((?:[^']|'')+)' THEN cardinality\(split\(\"line\", ','\)\) <> (\d+)"
)
_FALLBACK = re.compile(r"ELSE (true|false) END")
#: The blank-line exclusion, as the builder emits it.
_PRESENT = "\"line\" IS NOT NULL AND \"line\" <> ''"

JAN = "s3://bkt/alice/sales/jan.csv"
FEB = "s3://bkt/alice/sales/feb.csv"


def _rendered_rule(query: str) -> tuple[dict, bool]:
    """The emitted predicate: ``({s3 path: expected field count}, fallback)``.

    The path is un-escaped back from Trino's doubled quote, so a key containing an
    apostrophe round-trips rather than parsing into a silently wrong key.

    ``fallback`` is read from the ``ELSE`` branch — or, when the builder emitted no ``CASE``
    at all (the empty-mapping shape), from the bare boolean it emitted instead.
    """
    branches = {
        path.replace("''", "'"): int(count) for path, count in _BRANCH.findall(query)
    }
    found = _FALLBACK.search(query)
    fallback = found.group(1) if found else ("true" if "AND true)" in query else "false")
    return branches, fallback == "true"


def _ragged_lines(query: str, lines_by_path: dict) -> int:
    """Apply the emitted predicate to physical lines the way the SQL does.

    Takes the QUERY, not a pre-parsed rule, so all three clauses come out of the emitted
    text: the blank-line exclusion, the per-path expected count, and whatever the fallback
    says about a path with no branch. Passing a rule in would let a caller supply semantics
    the query does not have.
    """
    branches, fallback = _rendered_rule(query)
    skips_blank = _PRESENT in query
    counted = 0
    for path, lines in lines_by_path.items():
        for line in lines:
            if skips_blank and not line:
                continue
            if path in branches:
                counted += len(line.split(",")) != branches[path]
            else:
                counted += fallback
    return counted


def test_a_scanned_path_with_no_manifest_entry_is_never_ragged():
    """FR-004 — the raw-line table scans the folder while the mapping comes from the
    manifest, so the two can disagree: an object written between the inspection and the
    query, or one whose header could not be probed. There is no expected count for such a
    line and therefore no basis on which to judge it; unjudgeable is not ragged.

    The fallback is READ FROM THE QUERY, so an `ELSE true` regression fails this rather
    than sliding past it — which is the whole difference between this and an assertion that
    the string `ELSE false END` appears somewhere.
    """
    q = sql.build_ragged_query("alice", "raw", {JAN: 3})
    assert _rendered_rule(q) == ({JAN: 3}, False)

    stray = "s3://bkt/alice/sales/appeared-late.csv"
    counted = _ragged_lines(
        q, {JAN: ["id,amount,region", "1,10,north"], stray: ["a,b,c,d,e,f", "x", "y,z"]}
    )
    assert counted == 0, "an unmapped path must fall to the ELSE branch, however malformed"

    # The negative control, on a query carrying the OPPOSITE fallback. Without it the
    # assertion above would hold just as well if nothing were being read at all.
    assert _ragged_lines(q.replace("ELSE false", "ELSE true"), {stray: ["a,b,c", "x"]}) == 2


def test_a_key_containing_an_apostrophe_round_trips_through_the_rule():
    """The escape and the parse have to agree, or a later test using these helpers gets a
    silently wrong mapping rather than an error."""
    key = "s3://bkt/alice/o'brien.csv"
    branches, fallback = _rendered_rule(sql.build_ragged_query("alice", "raw", {key: 4}))

    assert branches == {key: 4}
    assert fallback is False


def test_a_folder_whose_files_disagree_reports_ZERO_ragged_rows():
    """THE BUG SPEC-142 EXISTS FOR (FR-005), pinned where it actually lives.

    Two files that disagree about their columns, every line well-formed WITHIN ITS OWN
    FILE. The union column count is 3; under the old comparison every line of the narrower
    file — its two data rows AND its header — came back ragged, so the user was handed a
    count of 3 for a folder with nothing malformed in it, next to a cross-file finding that
    had already told them the truth.
    """
    # feb.csv carries a trailing blank line — the ordinary shape of a text export, and the
    # clause whose coverage was otherwise a golden string away from being lost.
    jan_lines = ["id,amount,region", "1,10,north", "2,20,south"]
    feb_lines = ["id,amount", "3,30", "4,40", ""]

    q = sql.build_ragged_query("alice", "raw", {JAN: 3, FEB: 2})

    # Each file's own header count — NOT the union's 3 for both.
    assert _rendered_rule(q) == ({JAN: 3, FEB: 2}, False)
    assert _ragged_lines(q, {JAN: jan_lines, FEB: feb_lines}) == 0

    # And what the union comparison produced, so the regression is legible rather than
    # asserted-by-assertion: the whole of feb.csv, header included. The blank line is
    # excluded here for the same reason the query excludes it — the old comparison carried
    # that clause too, so counting it would overstate the bug.
    union = len({"id", "amount", "region"})
    assert sum(1 for line in feb_lines if line and len(line.split(",")) != union) == 3


def test_the_common_path_is_unchanged_when_every_file_agrees():
    """FR-001's first criterion — this fix must be INVISIBLE where the files agree, and a
    genuinely ragged row must still be counted."""
    q = sql.build_ragged_query("alice", "raw", {JAN: 3, FEB: 3})

    assert _ragged_lines(q, {JAN: ["id,amount,region", "1,10,north"]}) == 0
    assert _ragged_lines(q, {FEB: ["id,amount,region", "2,20"]}) == 1


def test_ragged_query_with_no_files_judges_nothing():
    """A CASE with no WHEN is a syntax error, and there is nothing to compare against."""
    q = sql.build_ragged_query("alice", "raw", {})
    assert "CASE" not in q
    assert "AND false) AS ragged_rows" in q
    # Exercises _rendered_rule's no-CASE arm, which nothing else reaches.
    assert _rendered_rule(q) == ({}, False)


def test_ragged_query_escapes_a_quote_in_an_s3_key():
    """Trino's ONLY string escape is doubling the quote — tscommon's Hive-style backslash
    would render a backslash into the path, and a branch that never matches produces no
    error, just a file's lines silently falling to the ELSE and going uncounted."""
    q = sql.build_ragged_query("alice", "raw", {"s3://bkt/alice/o'brien.csv": 4})
    assert "'s3://bkt/alice/o''brien.csv'" in q
    assert "\\" not in q


def test_ragged_query_excludes_blank_lines():
    """A blank line splits to ONE empty field, so on any multi-column source every blank
    line would otherwise be counted as ragged — a false finding in front of the user."""
    q = sql.build_ragged_query("alice", "raw", ONE_FILE)
    assert '"line" IS NOT NULL AND "line" <> \'\'' in q


def test_ragged_query_returns_one_row():
    """assemble-report reads the result file whole; this is what makes that safe."""
    q = sql.build_ragged_query("alice", "raw", ONE_FILE)
    assert "GROUP BY" not in q
    assert "ragged_rows" in q and "total_lines" in q


def test_the_ragged_query_refuses_rather_than_truncating_when_it_will_not_fit():
    """FR-003 — a guard that dropped the branches that did not fit would re-introduce
    SPEC-142's own bug on a subset, invisibly. Built from keys long enough to breach the
    cap rather than by monkey-patching the constant, because the file COUNT is a poor proxy
    for the length that actually matters."""
    long_key = "a" * 900
    mapping = {f"s3://bkt/{long_key}/{i:04d}.csv": 5 for i in range(config.DQ_MAX_OBJECTS)}

    with pytest.raises(sql.RaggedQueryTooLargeError):
        sql.build_ragged_query("alice", "raw", mapping)


def test_the_ragged_query_fits_at_a_realistic_file_count():
    """The guard must not be tripping on ordinary sources — a thousand files with keys of
    a plausible length has to render, or the check would degrade for everybody."""
    mapping = {f"s3://bkt/alice/sales/2026/part-{i:05d}.csv": 12 for i in range(config.DQ_MAX_OBJECTS)}
    q = sql.build_ragged_query("alice", "raw", mapping)
    assert len(q.encode()) <= config.DQ_MAX_QUERY_BYTES


# ── The duplicates query (FR-003) ────────────────────────────────────────────


def test_duplicates_query_shape_is_pinned_to_one_row():
    q = sql.build_duplicates_query("alice", "t", STR_COLS, [])
    assert q == (
        'SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM '
        '(SELECT COUNT(*) AS cnt FROM "alice"."t" '
        'GROUP BY "order_id", "amount" HAVING COUNT(*) > 1)'
    )


def test_duplicates_query_groups_by_partition_columns_too():
    """Two otherwise-identical rows in different partitions are different rows."""
    q = sql.build_duplicates_query(
        "alice", "t", [{"name": "id", "type": "string"}], [{"name": "year", "values": ["2024"]}]
    )
    assert 'GROUP BY "id", "year"' in q


def test_duplicates_query_does_not_double_count_a_partition_named_column():
    """cpcommon.ddl drops a body column colliding with a partition key, so the grouping
    must too — a repeated GROUP BY column is a syntax-level inconsistency waiting to bite."""
    q = sql.build_duplicates_query(
        "alice", "t",
        [{"name": "year", "type": "string"}, {"name": "id", "type": "string"}],
        [{"name": "year", "values": ["2024"]}],
    )
    assert q.count('"year"') == 1
    assert 'GROUP BY "id", "year"' in q


def test_no_query_uses_hive_backtick_quoting():
    """THE DIALECT TRAP, asserted across all three queries at once.

    Athena parses DDL with Hive (backticks) and DML with Trino (double quotes), and AWS
    documents backticks in a DML query as an error. A query built with the DDL quoter
    looks perfectly reasonable in a diff AND in a golden-string test, then fails against
    the engine — after the temp tables exist and the scan has been paid for. The DDL
    builders above still use backticks, correctly; these must not.
    """
    queries = [
        sql.build_profile_query("alice", "t", STR_COLS, "csv"),
        sql.build_ragged_query("alice", "raw", ONE_FILE),
        sql.build_duplicates_query("alice", "t", STR_COLS, []),
    ]
    for q in queries:
        assert "`" not in q, q[:120]
    # And the DDL side genuinely still uses them, so this is a real distinction and not
    # just "nothing anywhere is backticked".
    assert "`" in sql.build_temp_table_ddl("alice", "t", STR_COLS, [], "csv", LOC)
    assert "`" in sql.build_drop_table_ddl("alice", "t")


def test_duplicates_query_is_separate_from_the_profile_query():
    """Never merged: a GROUP BY over every column is a full shuffle, and merged its
    failure would destroy every other finding."""
    profile = sql.build_profile_query("alice", "t", STR_COLS, "csv")
    assert "duplicate_rows" not in profile
    assert "HAVING COUNT(*) > 1" not in profile
