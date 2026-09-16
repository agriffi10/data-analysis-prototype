"""Unit tests for dqcommon.report (SPEC-112 FR-002/FR-003).

Pure: no AWS anywhere. The point of these is that a subtly wrong report does not crash —
it tells a user something false about their data and they act on it — so the assertions are
on exact wording and exact numbers, not on shape.
"""

import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from dqcommon import config, report, sql

COMPLETED = "2026-07-20T14:32:11Z"


def _csv(rows: list[dict]) -> bytes:
    """Render rows the way Athena renders a result file: header, then quoted fields."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def _rows(rows: list[dict]) -> list[dict]:
    """Round-trip fixture rows through a real CSV render + parse.

    NOT cosmetic. Athena hands back a file, so every value the report code sees is a STRING
    — a fixture of Python ints would let an int-only bug (or an int-only assumption) pass
    here and fail in production on the first real run. Building the rows as CSV and parsing
    them back means these tests exercise parse_result on the way in, exactly as deployed.
    """
    return report.parse_result(_csv(rows)) if rows else []


def _profile_row(row_count, columns, is_total=1, source_file=""):
    """One profile result row. ``columns`` is a list of per-column figure dicts."""
    row = {"source_file": source_file, "is_total": is_total, "row_count": row_count}
    for index, figures in enumerate(columns):
        alias = f"c{index}"
        row[f"{alias}_missing"] = figures.get("missing", 0)
        for cast in ("bigint", "double", "timestamp", "date"):
            row[f"{alias}_not_{cast}"] = figures.get(f"not_{cast}", row_count)
        row[f"{alias}_sample_non_numeric"] = figures.get("sample_non_numeric", "")
        row[f"{alias}_sample_non_temporal"] = figures.get("sample_non_temporal", "")
    return row


def _manifest(files, fmt="csv"):
    return {"format": fmt, "fileCount": len(files), "files": files}


def _file(key, columns, size=100):
    return {"key": key, "size": size, "columns": [{"name": c, "type": "string"} for c in columns]}


def _request(**overrides):
    request = {
        "requestId": "req-1",
        "actor": "alice",
        "location": "alice/sales/",
        "format": "csv",
        "ragged": {"queryExecutionId": "q2", "status": "SUCCEEDED", "resultLocation": "s3://b/r/"},
        "duplicates": {"queryExecutionId": "q3", "status": "SUCCEEDED", "resultLocation": "s3://b/d/"},
    }
    request.update(overrides)
    return request


def _encoding(**overrides):
    block = {
        "invalidUtf8Sequences": 0,
        "sampleOffsets": [],
        "bytesExamined": 300,
        "bytesTotal": 300,
        "coverage": "complete",
        "filesScanned": 1,
        "filesSkipped": 0,
    }
    block.update(overrides)
    return block


def _build(request=None, manifest=None, profile=None, ragged=None, dupes=None, encoding=None):
    return report.build(
        request or _request(),
        manifest or _manifest([_file("alice/sales/a.csv", ["id", "amount"])]),
        _rows(profile if profile is not None else [_profile_row(100, [{}, {}])]),
        _rows(ragged if ragged is not None else [{"ragged_rows": 0, "total_lines": 101}]),
        _rows(dupes if dupes is not None else [{"duplicate_rows": 0}]),
        # `is not None`, not `or`: an EMPTY block is a case under test, and `or` would
        # silently swap in the healthy default and assert nothing.
        encoding if encoding is not None else _encoding(),
        completed_at=COMPLETED,
    )


# ── Parsing Athena's result files ────────────────────────────────────────────


def test_parse_result_maps_rows_by_header():
    body = _csv([{"a": "1", "b": "2"}, {"a": "3", "b": "4"}])

    assert report.parse_result(body) == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_a_sample_value_containing_a_comma_survives_the_round_trip():
    """The reason the query renders samples with json_format.

    Athena's bare array rendering leaves elements unquoted, so `1,024` — the canonical CSV
    defect, and often the very reason the column was flagged — would split into two wrong
    examples. Nothing would look broken; the report would just be lying.
    """
    total = _profile_row(1000, [{"not_bigint": 5, "sample_non_numeric": '["N/A","1,024","a\\nb"]'}])
    document = _build(profile=[total])

    assert document["exact"]["columns"][0]["sampleOffending"] == ["N/A", "1,024", "a\nb"]


@pytest.mark.parametrize("cell", ["", "null", "not json at all", '{"a": 1}'])
def test_a_missing_or_unparseable_sample_becomes_an_empty_list(cell):
    """`null` is the real case, not a hypothetical: Trino's max_by returns NULL when no row
    matched, and json_format renders that as the string "null". Passed through unguarded it
    would put `sampleOffending: null` into the report, where SPEC-113 expects a list."""
    total = _profile_row(1000, [{"not_bigint": 5, "sample_non_numeric": cell}])

    assert _build(profile=[total])["exact"]["columns"][0]["sampleOffending"] == []


# ── Cross-file column agreement (FR-002) ─────────────────────────────────────


def test_a_single_file_source_agrees_trivially():
    result = report.cross_file([_file("a.csv", ["id"])], "csv", [])

    assert result == {"columnsAgree": True, "disagreements": []}


_YEAR = [{"name": "year", "values": ["2025"]}]
_YEAR_MONTH = [{"name": "year", "values": ["2025"]}, {"name": "month", "values": ["01"]}]


@pytest.mark.parametrize(
    ("fmt", "headers", "partition_keys", "expected"),
    [
        pytest.param(
            "csv",
            [["id", "amount"], ["id", "amount"], ["amount", "id"]],
            [],
            [{"file": "f2.csv", "missing": [], "extra": [], "shifted": True}],
            id="a-csv-swap-is-read-under-the-wrong-names",
        ),
        pytest.param(
            "parquet",
            [["id", "amount"], ["id", "amount"], ["amount", "id"]],
            [],
            [],
            id="parquet-is-matched-by-name-so-order-is-not-compared",
        ),
        pytest.param(
            "csv",
            [["id", "amount", "Year", "month"], ["id", "amount", "month", "Year"]],
            _YEAR_MONTH,
            [],
            id="trailing-partition-columns-are-never-read-so-their-order-is-not-a-finding",
        ),
        pytest.param(
            "csv",
            [["id", "amount", "Year"], ["id", "Year", "amount"]],
            _YEAR,
            [{"file": "f1.csv", "missing": [], "extra": [], "shifted": True}],
            id="a-partition-column-moved-before-a-kept-one-is-a-finding",
        ),
        pytest.param(
            "csv",
            [["id", "amount"], ["id", "amount"], ["amount", "id", "note"]],
            [],
            [{"file": "f2.csv", "missing": [], "extra": ["note"], "shifted": True}],
            id="an-extra-column-and-a-swap-are-named-together",
        ),
        pytest.param(
            "csv",
            [["id", "amount", "region"], ["id", "amount", "region"], ["id", "discount", "amount", "region"]],
            [],
            [{"file": "f2.csv", "missing": [], "extra": ["discount"], "shifted": True}],
            id="a-column-inserted-mid-header-shifts-every-column-after-it",
        ),
        pytest.param(
            "csv",
            [["id", "amount"], ["id", "amount"], ["id", "amount", "note"], ["id", "amount", "region"]],
            [],
            [
                {"file": "f2.csv", "missing": [], "extra": ["note"], "shifted": False},
                {"file": "f3.csv", "missing": [], "extra": ["region"], "shifted": True},
            ],
            id="two-files-adding-different-trailing-columns-read-one-under-the-others-name",
        ),
        pytest.param(
            "csv",
            [["amount", "id"], ["id", "amount"], ["id", "amount"]],
            [],
            [
                {"file": "f1.csv", "missing": [], "extra": [], "shifted": True},
                {"file": "f2.csv", "missing": [], "extra": [], "shifted": True},
            ],
            id="the-files-named-are-the-ones-misread-even-when-the-first-file-is-the-odd-one",
        ),
        pytest.param(
            "csv",
            [["CustomerID", "Region"], ["customerid", "region"], ["CUSTOMERID", "Region"]],
            [],
            [],
            id="headers-differing-only-by-case-are-one-column-and-line-up",
        ),
        pytest.param(
            "csv",
            [["id", "Amount", "Note"], ["id", "Amount", "Note"], ["ID", "amount"]],
            [],
            [{"file": "f2.csv", "missing": ["Note"], "extra": [], "shifted": False}],
            id="a-missing-column-is-named-in-the-spelling-the-report-columns-show",
        ),
        pytest.param(
            "csv",
            [["Id", "amount"], ["id", "Amount"], ["ID", "AMOUNT"], ["id", "amount", "Surprise"], ["id", "amount", "SURPRISE"]],
            [],
            [
                {"file": "f3.csv", "missing": [], "extra": ["Surprise"], "shifted": False},
                {"file": "f4.csv", "missing": [], "extra": ["SURPRISE"], "shifted": False},
            ],
            id="an-extra-column-is-named-in-the-files-own-spelling",
        ),
    ],
)
def test_a_csv_is_checked_against_the_columns_its_table_declares(fmt, headers, partition_keys, expected):
    """OpenCSVSerde reads field ``i`` of every file as the table's column ``i``, the folder's union
    in first-seen order without its partition columns, so a file whose fields do not line up is
    counted under the wrong names with nothing failing; Parquet and JSON are matched by name. A
    trailing partition column is past the declared columns and never read, so where it sits is
    not a finding, and it is matched on Athena's fold, so ``Year`` is the key ``year``. The files
    named are the ones this report misreads, which is not the minority when the minority is
    listed first."""
    files = [_file(f"f{index}.csv", header) for index, header in enumerate(headers)]

    result = report.cross_file(files, fmt, partition_keys)

    assert result == {"columnsAgree": not expected, "disagreements": expected}


def test_a_drifting_file_is_named_with_its_missing_columns():
    files = [
        _file("alice/s/part-0.csv", ["id", "amount", "note"]),
        _file("alice/s/part-1.csv", ["id", "amount", "note"]),
        _file("alice/s/part-2.csv", ["id", "amount"]),
    ]

    result = report.cross_file(files, "csv", [])

    assert result["columnsAgree"] is False
    assert result["disagreements"] == [
        {"file": "alice/s/part-2.csv", "missing": ["note"], "extra": [], "shifted": False}
    ]


def test_the_odd_file_is_named_even_when_it_is_the_FIRST_one():
    """The baseline must be the modal set, not file 0's.

    With the first file as baseline, a folder whose very first object is the broken one
    reports the OTHER 999 files as each missing a column — burying the single real finding
    under 999 false ones, and pointing the user at every file except the one to fix.
    """
    files = [
        _file("alice/s/part-0.csv", ["id", "amount"]),
        _file("alice/s/part-1.csv", ["id", "amount", "note"]),
        _file("alice/s/part-2.csv", ["id", "amount", "note"]),
    ]

    assert report.cross_file(files, "csv", [])["disagreements"] == [
        {"file": "alice/s/part-0.csv", "missing": ["note"], "extra": [], "shifted": False}
    ]


def test_a_source_with_no_files_agrees_rather_than_raising():
    assert report.cross_file([], "csv", []) == {"columnsAgree": True, "disagreements": []}


def test_an_extra_column_is_reported_as_extra_not_as_everyone_else_missing_one():
    """The baseline is the MODAL column set. Using the union would render every
    disagreement as a missing column and never an extra one; using the FIRST file's would
    blame all 999 others whenever file 0 is the odd one out."""
    files = [
        _file("a.csv", ["id"]),
        _file("b.csv", ["id"]),
        _file("c.csv", ["id", "surprise"]),
    ]

    assert report.cross_file(files, "csv", [])["disagreements"] == [
        {"file": "c.csv", "missing": [], "extra": ["surprise"], "shifted": False}
    ]


# ── Type consistency (FR-003) ────────────────────────────────────────────────


def test_a_dominant_numeric_column_reports_its_stragglers():
    total = _profile_row(
        1000,
        [{"not_bigint": 5, "not_double": 5, "sample_non_numeric": '["N/A","-"]'}],
    )

    column = _build(profile=[total])["exact"]["columns"][0]

    assert column["dominantType"] == "BIGINT"
    assert column["nonParsingValues"] == 5
    assert column["sampleOffending"] == ["N/A", "-"]


def test_a_mostly_text_column_is_not_reported_as_a_broken_numeric_one():
    """40% numeric is free text that happens to contain numbers. Reporting the other 60% as
    'offending' would be noise the user has to wade past to reach a real finding."""
    total = _profile_row(1000, [{"not_bigint": 600, "not_double": 600}])

    column = _build(profile=[total])["exact"]["columns"][0]

    assert column["dominantType"] == "text"
    assert column["nonParsingValues"] == 0


def test_a_temporal_column_gets_the_temporal_sample_not_the_numeric_one():
    total = _profile_row(
        1000,
        [{
            "not_timestamp": 3,
            "not_date": 3,
            "sample_non_numeric": '["2026-01-01"]',
            "sample_non_temporal": '["not-a-date"]',
        }],
    )

    column = _build(profile=[total])["exact"]["columns"][0]

    assert column["dominantType"] == "TIMESTAMP"
    assert column["sampleOffending"] == ["not-a-date"]


def test_a_wholly_null_column_is_text_rather_than_a_clean_number():
    total = _profile_row(1000, [{"missing": 1000}])

    column = _build(profile=[total])["exact"]["columns"][0]

    assert column["dominantType"] == "text"
    assert column["nullBlankRatio"] == 1.0


def test_parquet_type_consistency_is_skipped_and_never_a_green_pass():
    manifest = _manifest(
        [{"key": "a.parquet", "size": 1, "columns": [{"name": "amount", "type": "string"}]}],
        fmt="parquet",
    )
    total = _profile_row(1000, [{}])

    column = _build(request=_request(format="parquet"), manifest=manifest, profile=[total])[
        "exact"
    ]["columns"][0]

    assert column["typeConsistency"] == "skipped"
    assert column["reason"] == report.SKIP_TYPE_PARQUET
    # The thing that must NOT be there: any field a reader could take as a clean result.
    assert "dominantType" not in column
    assert "nonParsingValues" not in column


def test_a_typed_column_in_a_json_source_skips_for_a_DIFFERENT_reason():
    """A user reading 'Parquet enforces types' under a JSON report would rightly stop
    believing the rest of it."""
    manifest = _manifest(
        [{"key": "a.json", "size": 1, "columns": [{"name": "id", "type": "bigint"}]}], fmt="json"
    )

    column = _build(request=_request(format="json"), manifest=manifest, profile=[_profile_row(10, [{}])])[
        "exact"
    ]["columns"][0]

    assert column["reason"] == report.SKIP_TYPE_TYPED_COLUMN


def test_figures_attach_to_the_column_the_query_aliased_them_to():
    """The c{i} aliases are POSITIONAL, so the report must rebuild the column list with the
    SAME first-seen union the query was generated from.

    If the two ever diverge — say by concatenating each file's columns instead of unioning
    them — every figure lands on the wrong column. Nothing errors, nothing looks odd, and
    the user is told their `amount` column is clean and their `note` column is full of
    non-numbers. This asserts both the ORDER and that a figure follows its name.
    """
    files = [
        _file("a.csv", ["id", "amount"]),
        _file("b.csv", ["id", "amount", "note"]),
        _file("c.csv", ["amount", "id"]),
    ]
    total = _profile_row(
        100_000,
        [
            {"not_bigint": 0},                                        # c0 = id, clean
            {"not_bigint": 412, "sample_non_numeric": '["N/A"]'},      # c1 = amount, dirty
            {"missing": 50_000},                                       # c2 = note, half null
        ],
    )

    columns = _build(manifest=_manifest(files), profile=[total])["exact"]["columns"]

    assert [c["name"] for c in columns] == ["id", "amount", "note"]
    assert columns[1]["nonParsingValues"] == 412
    assert columns[2]["nullBlankRatio"] == 0.5
    assert columns[0]["nonParsingValues"] == 0


def test_a_column_merged_from_several_spellings_is_reported_once_and_discloses_them():
    """Three files spelling one column three ways are one column to Athena, so the query projects
    it once and the report lists it once, under the first spelling, with the others disclosed.
    The disclosure is not a finding: the folder's columns agree and the verdict stays clean."""
    files = [
        _file("alice/sales/a.csv", ["CustomerID", "Region", "amount"]),
        _file("alice/sales/b.csv", ["customerid", "region", "amount"]),
        _file("alice/sales/c.csv", ["CUSTOMERID", "Region", "amount"]),
        _file("alice/sales/d.csv", ["customerid", "Region", "amount"]),
    ]
    query = sql.build_profile_query("alice", "dq_tmp_x", sql.union_columns(files), [], "csv")

    document = _build(manifest=_manifest(files), profile=[_profile_row(400, [{"not_bigint": 0}, {}, {"not_double": 0}])])

    assert [name for name, _alias in re.findall(r'"([^"]+)"(?:\), \'\'\))? AS (c\d+)\b', query)] == [
        "CustomerID",
        "Region",
        "amount",
    ]
    assert [(c["name"], c["dominantType"], c.get("otherSpellings")) for c in document["exact"]["columns"]] == [
        ("CustomerID", "BIGINT", ["customerid", "CUSTOMERID"]),
        ("Region", "text", ["region"]),
        ("amount", "DOUBLE", None),
    ]
    assert document["exact"]["crossFile"] == {"columnsAgree": True, "disagreements": []}
    assert document["verdict"] == "clean"


def test_a_column_naming_a_partition_key_gets_no_figures_and_the_rest_keep_their_own():
    """The temp table has no data column under a partition key's name, so any figure for `Year`
    here would describe the folder's `year=` value rather than the file's field. The report
    leaves it out, and reads every other column's figures from the alias the real query gave it.

    JSON, so the dropped column can sit in the middle: a report and a query that number the
    aliases over different lists then disagree about `amount`, and a missing cell reads as zero,
    so the misread column would look clean rather than fail.
    """
    files = [_file("alice/sales/year=2025/a.json", ["id", "Year", "amount"])]
    partition_keys = [{"name": "year", "values": ["2025"]}]
    query = sql.build_profile_query("alice", "dq_tmp_x", sql.union_columns(files), partition_keys, "json")
    aliased = re.findall(r'"([^"]+)"(?:\), \'\'\))? AS (c\d+)\b', query)
    total = {"source_file": "", "is_total": 1, "row_count": 100}
    total.update({f"{alias}_missing": 10 * position for position, (_name, alias) in enumerate(aliased, 1)})

    columns = _build(
        manifest=dict(_manifest(files, fmt="json"), partitionKeys=partition_keys), profile=[total]
    )["exact"]["columns"]

    assert [c["name"] for c in columns] == ["id", "amount"]
    assert [(c["name"], c["nullBlankRatio"]) for c in columns] == [
        (name, position / 10) for position, (name, _alias) in enumerate(aliased, 1)
    ]


# ── Ragged rows (FR-003) ─────────────────────────────────────────────────────


def test_the_ragged_note_carries_BOTH_caveats():
    """Quoted delimiters AND newlines inside quoted fields. Stating only the first — as an
    earlier draft did — leaves a user hunting for malformed rows that are in fact
    well-formed multi-line records."""
    note = _build(ragged=[{"ragged_rows": 37, "total_lines": 500}])["approximate"]["raggedRows"]

    assert note["count"] == 37
    assert "commas inside quotes" in note["note"]
    assert "newlines inside quoted fields" in note["note"]


def test_a_json_source_skips_ragged_rather_than_reporting_zero():
    """null means 'never applied', not 'we looked and found none' — a zero would read as a
    clean bill of health for a check that never ran."""
    figure = _build(request=_request(ragged=None), ragged=[])["approximate"]["raggedRows"]

    assert figure == {"status": "skipped", "reason": report.SKIP_RAGGED_NOT_LINE_DELIMITED}


def test_a_degraded_ragged_query_is_not_computed_with_a_friendly_reason():
    request = _request(ragged={"status": "not_computed", "reason": "HIVE_CURSOR_ERROR: xyz"})

    figure = _build(request=request, ragged=[])["approximate"]["raggedRows"]

    assert figure["status"] == "not_computed"
    assert figure["reason"] == report.NOT_COMPUTED_RAGGED
    assert "HIVE_CURSOR_ERROR" not in figure["reason"]  # no raw engine text (SPEC-106)


def test_a_line_length_failure_gets_its_specific_reason():
    request = _request(
        ragged={"status": "not_computed", "reason": "Line too long in text file s3://b/k"}
    )

    figure = _build(request=request, ragged=[])["approximate"]["raggedRows"]

    assert figure["reason"] == report.NOT_COMPUTED_RAGGED_LINE_TOO_LONG


def test_a_query_the_size_guard_refused_gets_its_own_actionable_reason():
    """SPEC-142 FR-003 — the reasonCode is a marker this codebase wrote, so it wins over the
    text match. The sentence says what the user can do, because unlike the other two
    degradations this one has an action."""
    request = _request(
        ragged={
            "queryExecutionId": None,
            "status": "not_computed",
            "reasonCode": sql.RAGGED_QUERY_TOO_LARGE,
            "reason": "ragged query is 300000 bytes over 1000 files, past DQ_MAX_QUERY_BYTES=262144",
        }
    )

    figure = _build(request=request, ragged=[])["approximate"]["raggedRows"]

    assert figure["status"] == "not_computed"
    assert figure["reason"] == report.NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE
    assert "DQ_MAX_QUERY_BYTES" not in figure["reason"]  # no internals (SPEC-106)


def test_the_rest_of_the_report_still_lands_when_ragged_could_not_be_computed():
    """FR-003 — a ragged figure that cannot be computed never fails the run (SPEC-111
    FR-003). Every exact figure is still there."""
    request = _request(
        ragged={"status": "not_computed", "reasonCode": sql.RAGGED_QUERY_TOO_LARGE, "reason": "x"}
    )

    document = _build(request=request, ragged=[])

    assert document["exact"]["rowCount"] == 100
    assert document["exact"]["duplicateRows"] == 0
    assert document["hasIncompleteFigures"] is True


def test_a_disagreeing_folder_with_no_ragged_rows_reports_the_disagreement_ONCE():
    """FR-005's report half — and ONLY the report half.

    THIS TEST CANNOT PIN THE FIX, and saying so is the point: `report.build` does not
    compute the ragged count, it reads `ragged_rows` out of the Athena result rows it is
    handed. Feeding it a zero and asserting a zero would pass against the buggy builder
    just as happily. The fix belongs where the rule is emitted —
    `test_a_folder_whose_files_disagree_reports_ZERO_ragged_rows`.

    What this test does pin is the user-visible outcome given a correct query: the
    disagreement gets its single home in `crossFile`, and no second contradictory figure
    appears beside it.
    """
    manifest = _manifest(
        [
            _file("alice/sales/jan.csv", ["id", "amount", "region"]),
            _file("alice/sales/feb.csv", ["id", "amount"]),
        ]
    )
    document = _build(
        manifest=manifest,
        profile=[_profile_row(100, [{}, {}, {}])],
        # What the per-file query now returns: nothing is ragged, though every line of
        # feb.csv (and both headers) would have been under the union comparison.
        ragged=[{"ragged_rows": 0, "total_lines": 102}],
    )

    assert document["approximate"]["raggedRows"]["count"] == 0
    assert document["exact"]["crossFile"]["columnsAgree"] is False
    assert document["exact"]["crossFile"]["disagreements"][0]["file"] == "alice/sales/feb.csv"
    # And the user is told about it exactly once.
    assert sum("region" in issue for issue in document["topIssues"]) == 1


# ── Duplicates (FR-003) ──────────────────────────────────────────────────────


def test_a_degraded_duplicates_query_still_leaves_a_complete_report():
    """The whole reason duplicates runs as its own statement."""
    request = _request(duplicates={"status": "not_computed", "reason": "EXCEEDED_RESOURCES"})
    files = [_file("a.csv", ["id"]), _file("b.csv", ["id", "extra"])]

    document = _build(
        request=request,
        manifest=_manifest(files),
        profile=[
            _profile_row(1000, [{"not_bigint": 0}, {}]),
            _profile_row(600, [{}, {}], is_total=0, source_file="s3://bkt/alice/s/a.csv"),
            _profile_row(400, [{}, {}], is_total=0, source_file="s3://bkt/alice/s/b.csv"),
        ],
        dupes=[],
    )

    assert document["exact"]["duplicateRows"] == {
        "status": "not_computed",
        "reason": report.NOT_COMPUTED_DUPLICATES,
    }
    # Everything else still landed, and the report still reaches a verdict.
    assert document["exact"]["rowCount"] == 1000
    assert document["exact"]["columns"][0]["nullBlankRatio"] == 0.0
    assert document["exact"]["crossFile"]["columnsAgree"] is False
    assert document["verdict"] == "issues_found"
    assert document["hasApproximateFigures"] is True


def test_row_counts_by_file_are_keyed_by_object_key_not_the_s3_uri():
    """S3 keys are case-sensitive and `$path` keeps the key's case, so the key recovered from the
    full path has to match the manifest's key exactly. The fixture key carries a capital in a
    folder and another in the file name because a recovery that lowercased the key, or only part
    of it, would still match wherever that part was already lowercase. Lowercasing would file the
    count under a key the manifest does not have, so looking up the manifest's key would find
    nothing and report the file with zero rows, while `rowCount`, which comes from the total row,
    would stay right."""
    document = _build(
        manifest=_manifest([_file("alice/Sales/Part-0.csv", ["id", "amount"])]),
        profile=[
            _profile_row(1000, [{}, {}]),
            _profile_row(1000, [{}, {}], is_total=0, source_file="s3://bkt/alice/Sales/Part-0.csv"),
        ],
    )

    assert document["exact"]["rowCountsByFile"] == [{"key": "alice/Sales/Part-0.csv", "rows": 1000}]


def test_two_keys_that_differ_only_in_case_each_keep_their_own_row_count():
    """S3 keys are case-sensitive, so `Data.csv` and `data.csv` in one folder are two objects, and
    each is owed the count Athena gave its own `$path`. A single capitalised key cannot catch a
    key recovery that folds case when the manifest lookup folds it too, because both sides fold
    alike and still meet. Two keys that differ only in case can, as long as their counts differ:
    folded, both recover to the same key, both files are reported with the one count that key
    kept, and the per-file counts stop summing to `rowCount`. With equal counts the collapsed
    report would read exactly like the correct one, and the test would pass with the fold in
    place."""
    files = [_file("alice/s/Data.csv", ["id"]), _file("alice/s/data.csv", ["id"])]

    document = _build(
        manifest=_manifest(files),
        profile=[
            _profile_row(30, [{}]),
            _profile_row(20, [{}], is_total=0, source_file="s3://bkt/alice/s/Data.csv"),
            _profile_row(10, [{}], is_total=0, source_file="s3://bkt/alice/s/data.csv"),
        ],
    )

    assert document["exact"]["rowCountsByFile"] == [
        {"key": "alice/s/Data.csv", "rows": 20},
        {"key": "alice/s/data.csv", "rows": 10},
    ]


def test_a_file_with_no_data_rows_is_reported_as_zero_rather_than_vanishing():
    """Athena emits no `$path` group for a file with no data rows, so a header-only CSV — a
    failed export, one of the commoner real defects — would simply be ABSENT from the array.
    The file the user most needs to hear about is the one that disappears, and the array's
    length would silently stop matching fileCount."""
    files = [_file("alice/s/a.csv", ["id"]), _file("alice/s/empty.csv", ["id"])]

    document = _build(
        manifest=_manifest(files),
        profile=[
            _profile_row(1000, [{}]),
            _profile_row(1000, [{}], is_total=0, source_file="s3://bkt/alice/s/a.csv"),
        ],
    )

    assert document["exact"]["rowCountsByFile"] == [
        {"key": "alice/s/a.csv", "rows": 1000},
        {"key": "alice/s/empty.csv", "rows": 0},
    ]


def test_row_counts_are_sorted_so_a_replay_cannot_reorder_them():
    """GROUP BY GROUPING SETS has no ORDER BY: Athena's row order is arbitrary and not
    stable across executions. FR-003 requires a replay to differ ONLY in completedAt."""
    files = [_file("alice/s/c.csv", ["id"]), _file("alice/s/a.csv", ["id"]), _file("alice/s/b.csv", ["id"])]
    per_file = [
        _profile_row(1, [{}], is_total=0, source_file=f"s3://bkt/alice/s/{name}.csv")
        for name in ("b", "c", "a")
    ]

    document = _build(manifest=_manifest(files), profile=[_profile_row(3, [{}]), *per_file])

    assert [entry["key"] for entry in document["exact"]["rowCountsByFile"]] == [
        "alice/s/a.csv",
        "alice/s/b.csv",
        "alice/s/c.csv",
    ]


# ── Encoding (FR-001 consumed here) ──────────────────────────────────────────


def test_a_sampled_scan_states_its_coverage_percentage():
    figure = _build(
        manifest=_manifest([_file("alice/sales/a.csv", ["id", "amount"], size=250_000)]),
        encoding=_encoding(bytesExamined=1000, bytesTotal=250_000, coverage="sampled"),
    )["approximate"]["encoding"]

    assert figure["coveragePercent"] == 0.4
    assert figure["note"] == "Sampled — 0.4% of bytes examined."


def test_the_coverage_percentage_counts_bytes_the_scan_could_not_read():
    """One 13-byte .csv beside ninety-nine 1 GiB .csv.gz.

    byte-scan's own bytesTotal counts only the files it could read, so using it as the
    denominator renders "Sampled — 100.0% of bytes examined. 99 compressed file(s) were not
    scanned." — a sentence that contradicts itself and understates the unexamined data by
    ~99 GB. Phase 1 fixed the "complete" label for this case and left the percentage wrong.
    """
    gib = 1024**3
    files = [_file("alice/s/a.csv", ["id"], size=13)]
    files += [_file(f"alice/s/{i}.csv.gz", ["id"], size=gib) for i in range(99)]

    figure = _build(
        manifest=_manifest(files),
        profile=[_profile_row(10, [{}])],
        encoding=_encoding(bytesExamined=13, bytesTotal=13, coverage="sampled", filesSkipped=99),
    )["approximate"]["encoding"]

    assert figure["coveragePercent"] == 0.0
    assert "100.0%" not in figure["note"]


def test_an_empty_encoding_block_is_not_computed_rather_than_a_clean_zero():
    """An absent figure must not be manufactured into a green one: zero invalid sequences
    over zero bytes examined, rendered as a real result."""
    figure = _build(encoding={})["approximate"]["encoding"]

    assert figure == {"status": "not_computed", "reason": report.NOT_COMPUTED_ENCODING}


def test_a_complete_scan_says_so():
    assert _build()["approximate"]["encoding"]["note"] == "Complete — every byte examined."


def test_skipped_files_are_named_in_the_encoding_note():
    figure = _build(encoding=_encoding(coverage="sampled", filesSkipped=99))["approximate"][
        "encoding"
    ]

    assert "99 compressed file(s) were not scanned" in figure["note"]


def test_a_skipped_encoding_block_passes_through_with_its_reason():
    figure = _build(encoding={"status": "skipped", "reason": "binary format"})["approximate"][
        "encoding"
    ]

    assert figure == {"status": "skipped", "reason": "binary format"}


# ── Verdict, top issues, and the approximate flag (FR-003) ───────────────────


def test_a_clean_source_reaches_a_clean_verdict():
    document = _build(profile=[_profile_row(1000, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["verdict"] == "clean"
    assert document["topIssues"] == []


def test_top_issues_put_structural_findings_before_statistical_ones():
    """A file missing a column changes what every other number in the report MEANS, and is
    the finding most likely to explain a broken downstream table. A duplicate-row count
    changes nothing else. Whatever is first is what gets read in a notification."""
    files = [
        _file("alice/s/part-0.csv", ["id", "amount", "note"]),
        _file("alice/s/part-1.csv", ["id", "amount", "note"]),
        _file("alice/s/part-2.csv", ["id", "amount"]),
    ]
    # 412 stragglers in 100,000 rows is a 99.6%-numeric column with a real problem. The
    # same 412 in 1,000 rows would be 59% numeric — free text, correctly NOT flagged.
    total = _profile_row(
        100_000,
        [{"not_bigint": 0}, {"not_bigint": 412, "sample_non_numeric": '["N/A"]'}, {"not_bigint": 0}],
    )

    document = _build(
        manifest=_manifest(files),
        profile=[total],
        ragged=[{"ragged_rows": 37, "total_lines": 1001}],
        dupes=[{"duplicate_rows": 812}],
        encoding=_encoding(invalidUtf8Sequences=4, coverage="sampled", bytesExamined=1, bytesTotal=250),
    )

    assert document["topIssues"] == [
        "part-2.csv is missing the column `note` that the other 2 files have",
        "37 rows have the wrong number of fields (approximate)",
        (
            "4 invalid text encodings found, in the part examined — this data may have been "
            "exported in the wrong character set"
        ),
        "`amount` has 412 values that aren't numbers in an otherwise numeric column",
        "812 duplicate rows",
    ]
    assert document["verdict"] == "issues_found"


def test_top_issues_are_capped():
    files = [_file(f"alice/s/part-{i}.csv", ["id"]) for i in range(8)]
    files += [_file(f"alice/s/odd-{i}.csv", ["id", "extra"]) for i in range(8)]
    columns = [{"not_bigint": 0}, {"not_bigint": 0}]

    document = _build(manifest=_manifest(files), profile=[_profile_row(10, columns)])

    assert len(document["topIssues"]) == config.DQ_TOP_ISSUES


def test_shifted_files_share_one_top_issue_line_however_many_there_are():
    """A folder whose export changed its header part-way through splits in two, and a line per
    shifted file would fill the capped list with one sentence and push every other finding out."""
    files = [_file(f"alice/s/{month}.csv", ["id", "amount"]) for month in ("jan", "feb", "mar")]
    files += [_file(f"alice/s/{month}.csv", ["amount", "id"]) for month in ("apr", "may", "jun")]
    columns = [{"not_bigint": 0}, {"not_bigint": 0}]

    document = _build(manifest=_manifest(files), profile=[_profile_row(10, columns)])

    assert document["topIssues"] == [
        (
            "3 files, starting with apr.csv, have columns that don't line up with this report's "
            "Columns — a CSV is read by position, so their values are counted under the wrong columns"
        )
    ]


@pytest.mark.parametrize("fmt", ["csv", "json", "parquet"])
def test_every_supported_format_reports_approximate_figures(fmt):
    """FR-003 files ragged and encoding under APPROXIMATE whenever computed and SKIPPED
    when not, so no source shape yields an all-exact report. SPEC-114's qualifier will
    therefore fire on every report and must read as the normal case, not as a warning."""
    ragged_block = None if fmt != "csv" else _request()["ragged"]
    encoding = _encoding() if fmt != "parquet" else {"status": "skipped", "reason": "binary"}

    document = _build(
        request=_request(format=fmt, ragged=ragged_block),
        manifest=_manifest([_file("a." + fmt, ["id"])], fmt=fmt),
        profile=[_profile_row(10, [{}])],
        ragged=[{"ragged_rows": 0, "total_lines": 1}] if fmt == "csv" else [],
        encoding=encoding,
    )

    assert document["hasApproximateFigures"] is True


def test_a_profile_result_with_no_total_row_is_a_FAILED_check_not_a_clean_one():
    """Every exact figure comes from that one row. Without it the report assembles happily —
    zero rows, every column clean, verdict CLEAN — and hands the user a green result over
    data nothing measured. That is worse than no report at all."""
    with pytest.raises(report.MissingProfileError):
        _build(profile=[])


def test_a_profile_result_with_only_per_file_rows_is_also_a_failed_check():
    per_file = _profile_row(10, [{}, {}], is_total=0, source_file="s3://bkt/alice/sales/a.csv")

    with pytest.raises(report.MissingProfileError):
        _build(profile=[per_file])


def test_an_enormous_offending_value_is_truncated():
    """DQ_OFFENDING_VALUE_SAMPLE bounds how MANY examples a column contributes; nothing
    bounds how long one is, and an Athena varchar has no length limit."""
    huge = "x" * 5000
    total = _profile_row(1000, [{"not_bigint": 5, "sample_non_numeric": json.dumps([huge])}])

    sample = _build(profile=[total])["exact"]["columns"][0]["sampleOffending"][0]

    assert len(sample) == report.MAX_SAMPLE_VALUE_CHARS + 1  # the cap plus the ellipsis
    assert sample.endswith("…")


def test_a_two_file_disagreement_reads_grammatically():
    """"the other 1 files have" would ship straight into a notification body."""
    files = [_file("alice/s/a.csv", ["id", "note"]), _file("alice/s/b.csv", ["id"])]

    document = _build(manifest=_manifest(files), profile=[_profile_row(10, [{}, {}])])

    assert document["topIssues"] == [
        "b.csv is missing the column `note` that the other 1 file has"
    ]


def test_an_extra_column_reads_grammatically_too():
    files = [
        _file("alice/s/a.csv", ["id"]),
        _file("alice/s/b.csv", ["id"]),
        _file("alice/s/c.csv", ["id", "surprise"]),
    ]

    document = _build(manifest=_manifest(files), profile=[_profile_row(10, [{}, {}])])

    assert document["topIssues"] == [
        "c.csv has the extra column `surprise`, which the other 2 files do not"
    ]


def test_a_healthy_csv_has_nothing_incomplete():
    """The flag that actually varies. Everything ran and every byte was scanned, so the user
    is not missing a figure — even though ragged is inherently approximate."""
    document = _build(profile=[_profile_row(1000, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["hasApproximateFigures"] is True
    assert document["hasIncompleteFigures"] is False


@pytest.mark.parametrize(
    "case",
    ["degraded_duplicates", "degraded_ragged", "skipped_ragged", "sampled_encoding",
     "skipped_encoding", "parquet_types"],
)
def test_anything_skipped_or_failed_marks_the_report_incomplete(case):
    """Each of these means a figure the user asked for is not in front of them — which is
    what SPEC-114 must warn about, as opposed to the always-on approximate qualifier."""
    request, manifest, encoding = _request(), None, _encoding()
    profile = [_profile_row(1000, [{"not_bigint": 0}, {"not_bigint": 0}])]
    ragged = dupes = None

    if case == "degraded_duplicates":
        request = _request(duplicates={"status": "not_computed", "reason": "EXCEEDED_RESOURCES"})
        dupes = []
    elif case == "degraded_ragged":
        request = _request(ragged={"status": "not_computed", "reason": "boom"})
        ragged = []
    elif case == "skipped_ragged":
        request, ragged = _request(ragged=None), []
    elif case == "sampled_encoding":
        encoding = _encoding(coverage="sampled", bytesExamined=1, bytesTotal=300)
    elif case == "skipped_encoding":
        encoding = {"status": "skipped", "reason": "binary format"}
    else:
        request = _request(format="parquet")
        manifest = _manifest(
            [{"key": "a.parquet", "size": 1, "columns": [{"name": "id", "type": "string"}]}],
            fmt="parquet",
        )
        profile = [_profile_row(1000, [{}])]

    document = _build(
        request=request, manifest=manifest, profile=profile,
        ragged=ragged, dupes=dupes, encoding=encoding,
    )

    assert document["hasIncompleteFigures"] is True


def test_the_report_carries_its_identity_and_completion_time():
    document = _build()

    assert document["requestId"] == "req-1"
    assert document["location"] == "alice/sales/"
    assert document["format"] == "csv"
    assert document["fileCount"] == 1
    assert document["completedAt"] == COMPLETED


# ── SPEC-151 FR-002: zero rows over real files is a finding, never a clean verdict ──


def test_zero_rows_over_files_that_exist_is_never_a_clean_verdict():
    """The false-clean this closes: a check whose profile ran but matched nothing returned
    verdict "clean" with rowCount 0 — no duplicates, no ragged rows, no missing values,
    all trivially true of nothing. A user reading that would conclude their data was fine
    when none of it had been examined.
    """
    document = _build(profile=[_profile_row(0, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["exact"]["rowCount"] == 0
    assert document["verdict"] == "issues_found"
    assert "no rows were found" in document["topIssues"][0]


def test_the_empty_finding_leads_because_every_other_figure_is_zero():
    """Reporting "no duplicates, nothing ragged" about nothing is not information. If this
    ever slips below another finding, the notification body leads with a statistic
    computed over an empty scan."""
    document = _build(profile=[_profile_row(0, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["topIssues"][0].startswith("no rows were found")


def test_a_delivered_report_is_still_produced_rather_than_the_check_failing():
    """A header-only CSV is a real, common export defect. Raising would hand the user
    "something went wrong" and NO report, making a data defect they need to see
    indistinguishable from an infrastructure fault (SPEC-151 FR-002, resolved as a
    finding). The report must still exist and still carry its figures."""
    document = _build(profile=[_profile_row(0, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["fileCount"] >= 1
    assert "columns" in document["exact"]
    assert document["exact"]["rowCountsByFile"] is not None


def test_a_populated_source_is_unaffected():
    document = _build(profile=[_profile_row(1000, [{"not_bigint": 0}, {"not_bigint": 0}])])

    assert document["verdict"] == "clean"
    assert document["topIssues"] == []


def test_row_count_equals_the_sum_of_the_per_file_counts_for_a_single_file_target():
    """SPEC-151 FR-001's arithmetic criterion, stated in the report's own terms.

    This is the invariant the whole FR exists to restore. Before it, the total row came
    from a scan of the parent FOLDER while rowCountsByFile was reconciled to the manifest
    (one file) — so the two halves of the same report described different populations and
    a reader summing the per-file column got a different answer to `rowCount`.

    `rowCountsByFile` is a LIST of {key, rows}, not a dict — the spec's `.values()` wording
    is loose, so the sum is taken over `rows`.
    """
    per_file = _profile_row(1000, [{}, {}], is_total=0, source_file="s3://bkt/alice/sales/a.csv")
    total = _profile_row(1000, [{"not_bigint": 0}, {"not_bigint": 0}])

    document = _build(profile=[total, per_file])

    exact = document["exact"]
    assert exact["rowCount"] == sum(entry["rows"] for entry in exact["rowCountsByFile"])


def test_the_same_invariant_holds_across_a_multi_file_folder_target():
    """The folder case must not have been broken in the course of fixing the file case."""
    files = [_file("alice/sales/a.csv", ["id", "amount"]), _file("alice/sales/b.csv", ["id", "amount"])]
    rows = [
        _profile_row(700, [{"not_bigint": 0}, {"not_bigint": 0}]),
        _profile_row(300, [{}, {}], is_total=0, source_file="s3://bkt/alice/sales/a.csv"),
        _profile_row(400, [{}, {}], is_total=0, source_file="s3://bkt/alice/sales/b.csv"),
    ]

    document = _build(manifest=_manifest(files), profile=rows)

    exact = document["exact"]
    assert exact["rowCount"] == 700
    assert sum(entry["rows"] for entry in exact["rowCountsByFile"]) == 700
