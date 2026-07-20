"""Unit tests for dqcommon.report (SPEC-112 FR-002/FR-003).

Pure: no AWS anywhere. The point of these is that a subtly wrong report does not crash —
it tells a user something false about their data and they act on it — so the assertions are
on exact wording and exact numbers, not on shape.
"""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
from dqcommon import config, report  # noqa: E402

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
        encoding or _encoding(),
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
    result = report.cross_file([_file("a.csv", ["id"])])

    assert result == {"columnsAgree": True, "disagreements": []}


def test_files_presenting_the_same_columns_agree():
    files = [_file("a.csv", ["id", "amount"]), _file("b.csv", ["amount", "id"])]

    assert report.cross_file(files)["columnsAgree"] is True


def test_a_drifting_file_is_named_with_its_missing_columns():
    files = [
        _file("alice/s/part-0.csv", ["id", "amount", "note"]),
        _file("alice/s/part-1.csv", ["id", "amount", "note"]),
        _file("alice/s/part-2.csv", ["id", "amount"]),
    ]

    result = report.cross_file(files)

    assert result["columnsAgree"] is False
    assert result["disagreements"] == [
        {"file": "alice/s/part-2.csv", "missing": ["note"], "extra": []}
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

    assert report.cross_file(files)["disagreements"] == [
        {"file": "alice/s/part-0.csv", "missing": ["note"], "extra": []}
    ]


def test_a_source_with_no_files_agrees_rather_than_raising():
    assert report.cross_file([]) == {"columnsAgree": True, "disagreements": []}


def test_an_extra_column_is_reported_as_extra_not_as_everyone_else_missing_one():
    """The baseline is the MODAL column set. Using the union would render every
    disagreement as a missing column and never an extra one; using the FIRST file's would
    blame all 999 others whenever file 0 is the odd one out."""
    files = [
        _file("a.csv", ["id"]),
        _file("b.csv", ["id"]),
        _file("c.csv", ["id", "surprise"]),
    ]

    assert report.cross_file(files)["disagreements"] == [
        {"file": "c.csv", "missing": [], "extra": ["surprise"]}
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
    document = _build(
        profile=[
            _profile_row(1000, [{}, {}]),
            _profile_row(1000, [{}, {}], is_total=0, source_file="s3://bkt/alice/sales/part-0.csv"),
        ]
    )

    assert document["exact"]["rowCountsByFile"] == [{"key": "alice/sales/part-0.csv", "rows": 1000}]


# ── Encoding (FR-001 consumed here) ──────────────────────────────────────────


def test_a_sampled_scan_states_its_coverage_percentage():
    figure = _build(encoding=_encoding(bytesExamined=1000, bytesTotal=250_000, coverage="sampled"))[
        "approximate"
    ]["encoding"]

    assert figure["coveragePercent"] == 0.4
    assert figure["note"] == "Sampled — 0.4% of bytes examined."


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
        "4 invalid text encodings found, in the part examined — this data may have been "
        "exported in the wrong character set",
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


def test_the_report_carries_its_identity_and_completion_time():
    document = _build()

    assert document["requestId"] == "req-1"
    assert document["location"] == "alice/sales/"
    assert document["format"] == "csv"
    assert document["fileCount"] == 1
    assert document["completedAt"] == COMPLETED
