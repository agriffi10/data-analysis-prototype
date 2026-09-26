"""Unit tests for the data-quality assemble-report Lambda (SPEC-112 FR-003/FR-004).

Pure logic, AWS stubbed. The report content itself is covered by test_report_dqcommon.py;
what is tested here is the READ side (finding Athena's result objects), the WRITE side (a
key that is a pure function of requestId), the replay guarantee that follows from it, and the
location the report, the notification and the runs row name.
"""

import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-drop-temp-tables"))

import dq_assemble_report as v
import pytest
from cpcommon.columns import MAX_COLUMN_NAME_LENGTH
from cpcommon.errors import TerminalError
from dqcommon import report

BUCKET = "dq-user-bkt"
PREFIX = "alice/_data-quality-reports/req-1"
RESULTS = "s3://dq-user-bkt/alice/athenaresults/data-quality/req-1"


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


def _csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def _profile():
    row = {"source_file": "", "is_total": 1, "row_count": 1000}
    for alias in ("c0", "c1"):
        row[f"{alias}_missing"] = 0
        for cast in ("bigint", "double", "timestamp", "date"):
            row[f"{alias}_not_{cast}"] = 0
        row[f"{alias}_sample_non_numeric"] = ""
        row[f"{alias}_sample_non_temporal"] = ""
    return _csv([row])


MANIFEST = {
    "format": "csv",
    "fileCount": 1,
    "files": [
        {
            "key": "alice/sales/a.csv",
            "size": 300,
            "columns": [{"name": "id", "type": "string"}, {"name": "amount", "type": "string"}],
        }
    ],
}


class _FakeS3:
    """Serves the manifest + the three result objects; records puts and lists."""

    def __init__(self, objects=None, missing=()):
        self.objects = objects or {}
        self.missing = set(missing)
        self.puts = []
        self.gets = []
        self.lists = []

    def get_object(self, Bucket, Key):  # boto3's kwarg casing
        self.gets.append(Key)
        if Key in self.missing or Key not in self.objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.objects[Key] = Body
        return {}

    def list_objects_v2(self, Bucket, Prefix):
        self.lists.append(Prefix)
        return {
            "Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]
        }


def _objects(extra=None):
    objects = {
        f"{PREFIX}/manifest.json": json.dumps(MANIFEST).encode(),
        "alice/athenaresults/data-quality/req-1/profile/q1.csv": _profile(),
        "alice/athenaresults/data-quality/req-1/ragged/q2.csv": _csv(
            [{"ragged_rows": 0, "total_lines": 1001}]
        ),
        "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _csv([{"duplicate_rows": 0}]),
    }
    objects.update(extra or {})
    return objects


def _event():
    return {
        "requestId": "req-1",
        "actor": "alice",
        "location": "alice/sales",
        "pathFilter": None,
        "format": "csv",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "manifestKey": f"{PREFIX}/manifest.json",
        "reportPrefix": PREFIX,
        "profile": {"queryExecutionId": "q1", "status": "SUCCEEDED", "resultLocation": f"{RESULTS}/profile/"},
        "ragged": {"queryExecutionId": "q2", "status": "SUCCEEDED", "resultLocation": f"{RESULTS}/ragged/"},
        "duplicates": {"queryExecutionId": "q3", "status": "SUCCEEDED", "resultLocation": f"{RESULTS}/duplicates/"},
        "encoding": {
            "invalidUtf8Sequences": 0,
            "sampleOffsets": [],
            "bytesExamined": 300,
            "bytesTotal": 300,
            "coverage": "complete",
            "filesScanned": 1,
            "filesSkipped": 0,
        },
    }


def _setup(monkeypatch, objects=None, missing=()):
    fake = _FakeS3(objects=objects if objects is not None else _objects(), missing=missing)
    monkeypatch.setattr(v.clients, "s3", lambda: fake)
    return fake


def _index(fake):
    """The runs-index document (SPEC-123), or None if this run never wrote one."""
    indexes = [p for p in fake.puts if p["Key"].endswith("index.json")]
    return json.loads(indexes[-1]["Body"]) if indexes else None


# ── The write ────────────────────────────────────────────────────────────────


def test_the_report_lands_at_a_key_that_is_a_pure_function_of_the_request(monkeypatch):
    fake = _setup(monkeypatch)

    out = v.handler(_event(), None)

    assert fake.puts[0]["Key"] == f"{PREFIX}/report.json"
    assert out["reportKey"] == f"{PREFIX}/report.json"


@pytest.mark.parametrize(("coverage", "incomplete"), [("complete", False), ("sampled", True)])
def test_the_runs_row_carries_the_reports_incomplete_flag(monkeypatch, coverage, incomplete):
    """The list row's Partly checked tag reads this entry field. Dropped from the threaded
    summary, the entry would store null, the page would read that as incomplete, and every row
    would be tagged again with nothing failing."""
    fake = _setup(monkeypatch)
    event = _event()
    event["encoding"] = {**event["encoding"], "coverage": coverage}

    out = v.handler(event, None)

    assert out["hasIncompleteFigures"] is incomplete
    assert [entry["hasIncompleteFigures"] for entry in _index(fake)["entries"]] == [incomplete]


def test_the_actor_is_notified_before_the_index_is_touched(monkeypatch):
    """The notification is the user's only completion signal (SPEC-114), and the index
    append can cost several round trips under contention. Notifying second would mean a
    verb that times out mid-CAS leaves a written report nobody is ever told about."""
    fake = _setup(monkeypatch)
    order = []
    monkeypatch.setattr(v.notify, "emit_completed", lambda event: order.append("notify"))
    real_put = fake.put_object

    def put(**kwargs):
        if kwargs["Key"].endswith("index.json"):
            order.append("index")
        return real_put(**kwargs)

    monkeypatch.setattr(fake, "put_object", put)

    v.handler(_event(), None)
    assert order == ["notify", "index"]


def test_a_manifest_naming_a_file_outside_the_checked_folder_writes_no_report(monkeypatch):
    """Inside the space is not enough: a report describes the location the user checked.

    Driven through the real loader, with a sibling folder the actor owns, so a verb that contained
    the manifest to the space root instead of the location would pass it and write the report.
    """
    forged = dict(MANIFEST, files=[*MANIFEST["files"], {"key": "alice/other/b.csv", "size": 1, "columns": []}])
    fake = _setup(monkeypatch, objects=_objects({f"{PREFIX}/manifest.json": json.dumps(forged).encode()}))

    with pytest.raises(TerminalError) as excinfo:
        v.handler(_event(), None)

    assert excinfo.value.reason == "invalid_request"
    assert "outside the checked location" in excinfo.value.detail
    assert fake.puts == []


_REORDERED_ISSUE = (
    "b.csv's columns don't line up with this report's Columns — a CSV is read by position, so its "
    "values are counted under the wrong columns"
)


@pytest.mark.parametrize(
    ("fmt", "cross_file", "top_issues"),
    [
        pytest.param(
            "csv",
            {
                "columnsAgree": False,
                "disagreements": [
                    {"file": "alice/sales/year=2025/b.csv", "missing": [], "extra": [], "shifted": True}
                ],
            },
            [_REORDERED_ISSUE],
            id="csv-is-read-by-position",
        ),
        pytest.param(
            "parquet",
            {"columnsAgree": True, "disagreements": []},
            [],
            id="parquet-is-matched-by-name",
        ),
    ],
)
def test_a_file_with_its_columns_in_another_order_is_reported_only_where_fields_match_by_position(
    monkeypatch, fmt, cross_file, top_issues
):
    """The temp table declares one column order for the folder and OpenCSVSerde reads fields by
    position, so ``b.csv``'s ``Year`` is profiled as ``amount``. A comparison of column SETS cannot
    see it, so the report has to. The same two headers in Parquet are read by name and are not a
    finding."""
    manifest = {
        "format": fmt,
        "fileCount": 2,
        "partitionKeys": [{"name": "year", "values": ["2025"]}],
        "files": [
            {
                "key": f"alice/sales/year=2025/{name}.{fmt}",
                "size": 150,
                "columns": [{"name": column, "type": "string"} for column in header],
            }
            for name, header in (("a", ["id", "amount", "Year"]), ("b", ["id", "Year", "amount"]))
        ],
    }
    fake = _setup(monkeypatch, objects=_objects({f"{PREFIX}/manifest.json": json.dumps(manifest).encode()}))

    v.handler({**_event(), "format": fmt}, None)

    document = json.loads(fake.puts[0]["Body"])
    assert document["exact"]["crossFile"] == cross_file
    assert document["topIssues"] == top_issues


# ── The location the report names ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("threaded", "path_filter", "named"),
    [
        pytest.param("alice/sales", None, "alice/sales/", id="a-folder-ends-in-a-slash"),
        pytest.param(
            "alice/sales/a.csv",
            f"s3://{BUCKET}/alice/sales/a.csv",
            "alice/sales/a.csv",
            id="a-file-is-named-exactly",
        ),
    ],
)
def test_the_report_the_notification_and_the_runs_row_all_name_a_folder_as_a_folder(
    monkeypatch, threaded, path_filter, named
):
    """validate-authorize threads the location normalised, and normalising drops a folder's slash,
    so the report said ``alice/sales`` and its Open folder opened ``alice/``. Whether the target is
    a folder is inspect-source's decision, carried as ``pathFilter``, and the three places a user
    reads the location all take it from there."""
    fake = _setup(monkeypatch)
    sent = []
    monkeypatch.setattr(v.notify, "emit_notification", lambda actor, message, **kw: sent.append(message))

    out = v.handler({**_event(), "location": threaded, "pathFilter": path_filter}, None)

    report = json.loads(fake.puts[0]["Body"])
    assert report["location"] == named
    assert out["location"] == named
    assert [entry["location"] for entry in _index(fake)["entries"]] == [named]
    assert len(sent) == 1
    assert f'"{named}"' in sent[0]


def test_a_state_without_the_carried_decision_writes_no_report(monkeypatch):
    """Absent is refused rather than read as a folder, which would name a file's report a folder."""
    fake = _setup(monkeypatch)
    event = _event()
    del event["pathFilter"]

    with pytest.raises(TerminalError) as exc:
        v.handler(event, None)

    assert exc.value.reason == "invalid_request"
    assert "pathFilter" in exc.value.detail
    assert fake.puts == []


# ── Finding Athena's result objects ──────────────────────────────────────────


def test_a_result_that_is_nowhere_raises_a_terminal_with_a_friendly_reason(monkeypatch):
    objects = _objects()
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    _setup(monkeypatch, objects=objects)

    with pytest.raises(TerminalError) as excinfo:
        v.handler(_event(), None)

    assert excinfo.value.reason == "query_failed"


# ── The samples, and the cap the report is read through ──────────────────────


def _samples_cell(rows, count=None):
    """One duplicates result whose samples cell is rendered as ``json_format`` renders it.

    Args:
      rows: The sampled rows, each a list whose first element is the repeat count as text.
      count: The duplicate-row figure, defaulting to the repeats past the first of each row.

    Returns:
      The result object's bytes.

    Raises:
      None.
    """
    total = count if count is not None else sum(int(row[0]) - 1 for row in rows)
    return _csv([{"duplicate_rows": total, "duplicate_samples": json.dumps(rows)}])


def _wide_profile(columns: int, offending: list[str] | None = None) -> bytes:
    """A profile result over ``columns`` string columns, for the wide-source fixture.

    ``report.build`` zips the manifest's columns against the profile's positional aliases with
    ``strict=True``, so a wide manifest needs a profile of the same width or the report raises
    before the read under test can matter.

    Args:
      columns: How many columns the source declares.
      offending: The non-numeric values every column samples, making each a numeric column with a
        few stragglers — the only shape whose report carries them. None for clean columns.

    Returns:
      The profile result object's bytes.

    Raises:
      None.
    """
    row = {"source_file": "", "is_total": 1, "row_count": 1000}
    for index in range(columns):
        alias = f"c{index}"
        row[f"{alias}_missing"] = 0
        for cast in ("bigint", "double", "timestamp", "date"):
            numeric = cast in ("bigint", "double")
            row[f"{alias}_not_{cast}"] = 0 if offending is None else 5 if numeric else 1000
        row[f"{alias}_sample_non_numeric"] = "" if offending is None else json.dumps(offending)
        row[f"{alias}_sample_non_temporal"] = ""
    return _csv([row])


def _report(fake):
    """The report document this run wrote.

    Args:
      fake: The stubbed S3.

    Returns:
      The parsed report.

    Raises:
      None.
    """
    written = [p for p in fake.puts if p["Key"].endswith("report.json")]
    return json.loads(written[-1]["Body"])


def test_the_samples_reach_the_report_through_a_reader_sized_for_them(monkeypatch):
    """Reads a duplicates cell wider than the CSV reader's default and writes what it held.

    The route end to end, and the only test that covers it: ``report.parse_result`` is handed the
    computed limit by THIS verb, and the unit tests that prove the limit itself works call it
    directly rather than through a handler.

    So the cell has to be one the DEFAULT refuses, and that takes a WIDE source. At the two columns
    every other fixture here uses, five rows of ``sql.SAMPLE_VALUE_CHARS`` values cannot approach
    131,072 characters however badly they escape — the limit only binds past about twenty grouped
    columns, which is the whole reason it is computed from the column count rather than set once.
    Hence the thirty-column manifest, and the two measurements before the run: without them a
    comfortable cell would read fine with the limit removed and this test would assert nothing.
    """
    names = [f"col{index}" for index in range(30)]
    manifest = {
        "format": "csv",
        "fileCount": 1,
        "files": [
            {
                "key": "alice/sales/a.csv",
                "size": 300,
                "columns": [{"name": name, "type": "string"} for name in names],
            }
        ],
    }
    first = ["z" * 200] * len(names)
    # Every character one JSON escapes to six, which is what the computed limit is sized against.
    filler = [chr(1) * 200] * len(names)
    samples = [["3", *first], *[[str(n), *filler] for n in range(2, 6)]]
    encoded = json.dumps(samples)
    assert len(encoded) > csv.field_size_limit()
    assert report.duplicates_field_size_limit(len(names)) > len(encoded)

    fake = _setup(
        monkeypatch,
        objects=_objects(
            {
                f"{PREFIX}/manifest.json": json.dumps(manifest).encode(),
                "alice/athenaresults/data-quality/req-1/profile/q1.csv": _wide_profile(len(names)),
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _csv(
                    [{"duplicate_rows": 4, "duplicate_samples": encoded}]
                ),
            }
        ),
    )

    v.handler(_event(), None)

    written = _report(fake)["exact"]["duplicateSamples"]
    assert written["columns"] == names
    assert written["rows"][0] == {"repeats": 3, "values": first}


def test_a_report_the_samples_push_past_the_cap_is_written_without_them(
    monkeypatch, captured_events
):
    """Drops the samples — and nothing else — from a report too large for the browser to open.

    The browser reads a report through the document route's size cap, so a report above it is not
    a large report but an unreadable one, and every finding in it is lost with the part that made
    it big.

    This lowers the cap AND enlarges the samples, on a two-column report, so the drop's own
    behaviour — the sentence, the one logged size — is checked apart from what makes a report heavy.
    The samples are bounded by the statement that produces them — ``DQ_DUPLICATE_SAMPLE`` rows of
    ``DQ_MAX_COLUMNS`` + 2 values of ``sql.SAMPLE_VALUE_CHARS`` each — so measured as the write
    measures them, SERIALIZED, the block runs 206 KB of plain ASCII to 2.4 MB of astral text
    against a 3 MiB cap. No samples fixture crosses that on its own: in production the branch needs
    a report whose OTHER figures already sit within about 700 KB of the cap, and the test of the
    largest report the statements can return builds one at the real cap.

    The three figures are the same block counted three ways, and the spread is the point: a
    character count is not a byte count, and JSON escapes a control character to six and an astral
    code point to twelve. An earlier draft of this paragraph quoted the raw character count, 204 KB,
    as if it were the serialized size, and understated the production window by a factor of ten. What the lowered cap cannot hide is a wrong constant, which
    ``test_data_quality_report_contract.py`` pins against the API's independently — and the samples
    are still what crosses the cap here, which is what the assertions below check.
    """
    huge = [[str(n), "z" * 200, "y" * 200] for n in range(2, 7)]
    fake = _setup(
        monkeypatch,
        objects=_objects(
            {
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _samples_cell(
                    huge, count=5
                )
            }
        ),
    )
    monkeypatch.setattr(v.config, "DQ_REPORT_MAX_BYTES", 1500)

    v.handler(_event(), None)

    document = _report(fake)
    assert document["exact"]["duplicateSamples"] == {
        "omitted": v.report.SAMPLES_OMITTED_TOO_LARGE
    }
    assert document["exact"]["duplicateRows"] == 5
    assert document["exact"]["rowCount"] == 1000
    assert document["verdict"] == "issues_found"
    assert len(fake.puts[0]["Body"]) <= 1500
    # The size is reported once, and it is the size of the document that did NOT fit — the
    # written one is under the cap by construction and saying so would tell an operator nothing.
    over = [e for e in captured_events.events if e.get("message") == v.OVER_CAP_EVENT]
    assert [e["fields"]["report_bytes"] for e in over] == [
        _samples_body(document, huge)
    ]


def _samples_body(document, rows):
    """How large the same report would have been with its samples still attached.

    Derived from the document that WAS written rather than re-measured from a second assembly, so
    the figure the log claims is checked against the only other thing it can be.

    Args:
      document: The report as written, carrying the omission sentence.
      rows: The sampled rows the statement returned.

    Returns:
      The byte length of that report with its samples.

    Raises:
      None.
    """
    restored = json.loads(json.dumps(document))
    restored["exact"]["duplicateSamples"] = {
        "columns": ["id", "amount"],
        "rows": [{"repeats": int(row[0]), "values": list(row[1:])} for row in rows],
    }
    return len(v._serialize(restored))


def test_a_report_that_fits_says_nothing_about_its_size(monkeypatch, captured_events):
    """Logs the report's size only on the run that had to act on it.

    A number emitted on every run is one nobody reads, and the run where it mattered would look
    like all the others.
    """
    _setup(
        monkeypatch,
        objects=_objects(
            {
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _samples_cell(
                    [["3", "a", "x"]], count=2
                )
            }
        ),
    )

    v.handler(_event(), None)

    assert [
        e for e in captured_events.events if e.get("message") == v.OVER_CAP_EVENT
    ] == []


def test_a_report_already_over_the_cap_without_samples_keeps_the_sentence_it_had(
    monkeypatch,
):
    """Leaves a true explanation in place rather than replacing it with a false one.

    A nested source's samples were never written, so dropping them frees nothing and the report is
    over the cap for some other reason. Overwriting its sentence would tell the user the samples
    were left out for size, which is not what happened — and the document would still not fit.
    """
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["files"][0]["columns"][1] = {"name": "amount", "type": "array<string>"}
    fake = _setup(
        monkeypatch,
        objects=_objects(
            {
                f"{PREFIX}/manifest.json": json.dumps(manifest).encode(),
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _csv(
                    [{"duplicate_rows": 4}]
                ),
            }
        ),
    )
    monkeypatch.setattr(v.config, "DQ_REPORT_MAX_BYTES", 10)

    v.handler(_event(), None)

    assert _report(fake)["exact"]["duplicateSamples"] == {
        "omitted": v.report.SAMPLES_OMITTED_NESTED
    }


def _split_manifest(count: int, columns, key) -> dict:
    """A folder whose files alternate between two schemas, so every other file disagrees.

    Args:
      count: How many files.
      columns: Each file's column names, from its index.
      key: Each file's key, from its index.

    Returns:
      The manifest.

    Raises:
      None.
    """
    return {
        "format": "csv",
        "fileCount": count,
        "files": [
            {
                "key": key(index),
                "size": 300,
                "columns": [{"name": name, "type": "string"} for name in columns(index)],
            }
            for index in range(count)
        ],
    }


def test_a_report_the_files_that_disagree_push_past_the_cap_lists_the_ones_that_fit(
    monkeypatch,
):
    """Lists the disagreeing files that fit, counts the rest, and leaves the shorter list whole.

    The cap is set a kilobyte under the report the same run writes uncapped, so the files that
    disagree are what crosses it. The row counts are a list the cap may shorten too, but a shorter
    one, and a list is shortened only once every longer one has come down to its length — so they
    arrive whole, and only the long list pays.

    The last assertion is what makes "the ones that fit" true rather than "some of them": one more
    file restored, with its count taken back, is over the cap.
    """
    first = [f"first_{index}".ljust(40, "x") for index in range(3)]
    second = [f"second_{index}".ljust(40, "x") for index in range(3)]
    manifest = _split_manifest(
        40,
        lambda index: second if index % 2 else first,
        lambda index: f"alice/sales/part-{index:05d}.csv",
    )
    objects = _objects(
        {
            f"{PREFIX}/manifest.json": json.dumps(manifest).encode(),
            "alice/athenaresults/data-quality/req-1/profile/q1.csv": _wide_profile(6),
        }
    )
    whole = _report(_run(monkeypatch, objects))
    cap = len(v._serialize(whole)) - 1000
    monkeypatch.setattr(v.config, "DQ_REPORT_MAX_BYTES", cap)

    fake = _run(monkeypatch, objects)

    body = [p for p in fake.puts if p["Key"].endswith("report.json")][-1]["Body"]
    document = json.loads(body)
    cross = document["exact"]["crossFile"]
    every = whole["exact"]["crossFile"]["disagreements"]
    kept = cross["disagreements"]
    assert 0 < len(kept) < len(every)
    assert kept == every[: len(kept)]
    assert cross["disagreementsUnlisted"] == len(every) - len(kept)
    assert cross["columnsAgree"] is False
    assert document["exact"]["rowCountsByFile"] == whole["exact"]["rowCountsByFile"]
    assert "rowCountsByFileUnlisted" not in document["exact"]
    assert len(body) <= cap
    cross["disagreements"] = every[: len(kept) + 1]
    cross["disagreementsUnlisted"] -= 1
    if not cross["disagreementsUnlisted"]:
        del cross["disagreementsUnlisted"]
    assert len(v._serialize(document)) > cap


def _run(monkeypatch, objects, event=None):
    """Runs the handler once over a fresh stubbed S3 holding ``objects``.

    Args:
      monkeypatch: The test's monkeypatch.
      objects: The stubbed objects, by key.
      event: The task input, defaulting to ``_event()``.

    Returns:
      The stubbed S3, holding what the run wrote.

    Raises:
      None.
    """
    fake = _setup(monkeypatch, objects=dict(objects))
    v.handler(event or _event(), None)
    return fake


def test_every_drop_is_priced_exactly_and_taken_from_the_longest_list(monkeypatch):
    """Holds the trim's arithmetic to the serializer, and its choice to the longest list, at every cap.

    The trim prices each entry it drops rather than serializing the report again, so its figure is
    only as good as that pricing: a byte low writes a report the page refuses, and a byte high drops
    an entry that fit. The sweep compares the size it computed with the length of the report it left,
    at every cap from the whole report down to nothing, which passes each edge on the way — a count
    reaching two digits, a list emptying, a spelling shorter than the count that replaces it.

    Longest first means a list loses an entry only while it is at least as long as every other, so
    whatever a list keeps, one more of its entries would have made it the longest. A fixed order
    breaks that at the first cap where the list it starts with runs short.

    The spellings are one list spent from its end, so across the columns, in order, they read as
    whole columns, then at most one partly kept, then empty ones. That is read from the report, not
    from the grouping the trim was handed, and the last column has the fewest spellings: were each
    column its own list, the longest would be spent first and a later column left whole behind it.
    """
    document = {
        "exact": {
            "rowCountsByFile": [{"key": f"alice/sales/{n}.csv", "rows": n} for n in range(12)],
            "crossFile": {
                "columnsAgree": False,
                "disagreements": [
                    {"file": f"alice/sales/{n}.csv", "missing": ["m" * n], "extra": [], "shifted": False}
                    for n in range(12)
                ],
            },
            "columns": [
                {"name": "id", "otherSpellings": ["ID", "Id"]},
                {"name": "amount", "otherSpellings": ["A" * 40, *[f"Amount{n}" for n in range(11)]]},
                {"name": "note"},
                {"name": "region", "otherSpellings": ["REGION"]},
            ],
        }
    }
    whole = len(v._serialize(document))
    for cap in range(whole, 0, -1):
        monkeypatch.setattr(v.config, "DQ_REPORT_MAX_BYTES", cap)
        trimmed = json.loads(json.dumps(document))
        lists = v._per_file_lists(trimmed)

        size = v._shed_longest_first(lists, whole)

        assert size == len(v._serialize(trimmed)), cap
        totals = [sum(tail.listed for tail in tails) for tails in lists]
        for index, tails in enumerate(lists):
            if all(tail.kept == len(tail.lengths) for tail in tails):
                continue
            largest = max(length for tail in tails for length in tail.lengths)
            assert all(totals[index] + largest + 1 >= total for total in totals), cap
        spent = [
            0 if len(column["otherSpellings"]) == len(whole_column["otherSpellings"])
            else 2 if not column["otherSpellings"] else 1
            for column, whole_column in zip(
                trimmed["exact"]["columns"], document["exact"]["columns"], strict=True
            )
            if whole_column.get("otherSpellings")
        ]
        assert spent == sorted(spent) and spent.count(1) <= 1, cap


_S3_MAX_KEY_BYTES = 1024


def test_the_largest_report_the_statements_can_return_is_written_where_the_page_can_read_it(
    monkeypatch,
):
    """Writes a report at every bound at once under the cap, its offending values intact.

    Every per-column figure is at its bound: ``DQ_MAX_COLUMNS`` columns, each numeric with
    ``DQ_OFFENDING_VALUE_SAMPLE`` stragglers of ``sql.SAMPLE_VALUE_CHARS`` astral code points — the
    character JSON escapes furthest, twelve, as a surrogate pair — each named as long as the
    column-name rule allows, with every sampled duplicate row full. So is every per-file list:
    ``DQ_MAX_OBJECTS`` files keyed to S3's 1,024-byte limit in astral characters, half carrying every
    column and half only the first, and each spelling its columns in a case no other file uses. So
    are the two figures nothing shortens: every top issue names the 199 columns a file can lack, the
    most one line can, and the encoding examples are ``DQ_OFFSET_SAMPLE`` of those keys. Uncapped,
    that report runs to tens of megabytes. The widths and counts are read from the constants, so
    raising any of them runs this against the new worst case, and the cap is the real one.

    The samples are dropped and every list is shortened, which is what they are for, and each list
    still counts every entry it had. The offending values are not touched, because nothing drops
    them: they have to fit on their own, and that is what sizes ``DQ_OFFENDING_VALUE_SAMPLE``. The
    assertions that each list was shortened, and that the fixed figures are at their bounds, are
    what give the last one meaning — a report whose lists never needed shortening fits trivially.
    """
    width = v.config.DQ_MAX_COLUMNS
    files = v.config.DQ_MAX_OBJECTS
    names = [f"{index:03d}".ljust(MAX_COLUMN_NAME_LENGTH, "x") for index in range(width)]
    schemas = (names, names[:1])

    def spelled(index):
        """One file's header: its schema, every name spelled in a case no other file uses.

        Args:
          index: The file's position in the folder.

        Returns:
          The file's column names.

        Raises:
          None.
        """
        bits = [index >> bit & 1 for bit in range(files.bit_length())]
        return [
            name[:3] + "".join("X" if bit else "x" for bit in bits) + name[3 + len(bits) :]
            for name in schemas[index % 2]
        ]

    stem = "alice/sales/"
    tail = "0000.csv"
    fill = "\U0001f600" * ((_S3_MAX_KEY_BYTES - len(stem) - len(tail)) // 4)
    manifest = _split_manifest(files, spelled, lambda index: f"{stem}{fill}{index:04d}.csv")
    value = "\U0001f600" * v.sql.SAMPLE_VALUE_CHARS
    offending = [value] * v.config.DQ_OFFENDING_VALUE_SAMPLE
    rows = [[str(n), *[value] * width] for n in range(2, 2 + v.config.DQ_DUPLICATE_SAMPLE)]
    event = _event()
    event["encoding"] = {
        **event["encoding"],
        "invalidUtf8Sequences": 10**12,
        "sampleOffsets": [
            {"key": entry["key"], "offset": 10**15}
            for entry in manifest["files"][: v.config.DQ_OFFSET_SAMPLE]
        ],
    }
    fake = _run(
        monkeypatch,
        _objects(
            {
                f"{PREFIX}/manifest.json": json.dumps(manifest).encode(),
                "alice/athenaresults/data-quality/req-1/profile/q1.csv": _wide_profile(
                    width, offending
                ),
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _samples_cell(rows),
            }
        ),
        event,
    )

    body = [p for p in fake.puts if p["Key"].endswith("report.json")][-1]["Body"]
    document = json.loads(body)
    exact = document["exact"]
    assert len(manifest["files"][0]["key"].encode()) == _S3_MAX_KEY_BYTES
    assert exact["duplicateSamples"] == {"omitted": v.report.SAMPLES_OMITTED_TOO_LARGE}
    shown = value[: v.report.MAX_SAMPLE_VALUE_CHARS] + "…"
    assert [column["sampleOffending"] for column in exact["columns"]] == [
        [shown] * v.config.DQ_OFFENDING_VALUE_SAMPLE
    ] * width
    assert len(document["topIssues"]) == v.config.DQ_TOP_ISSUES
    assert [issue.count("`") for issue in document["topIssues"]] == [2 * (width - 1)] * len(
        document["topIssues"]
    )
    assert len(document["approximate"]["encoding"]["sampleOffsets"]) == v.config.DQ_OFFSET_SAMPLE
    cross = exact["crossFile"]
    assert len(cross["disagreements"]) + cross["disagreementsUnlisted"] == files // 2
    assert len(exact["rowCountsByFile"]) + exact["rowCountsByFileUnlisted"] == files
    assert [
        len(column["otherSpellings"]) + column.get("otherSpellingsUnlisted", 0)
        for column in exact["columns"]
    ] == [files - 1] + [files // 2 - 1] * (width - 1)
    assert exact["columns"][-1]["otherSpellingsUnlisted"] > 0
    assert len(body) <= v.config.DQ_REPORT_MAX_BYTES


def _caller_fields(events) -> list[tuple]:
    """Every event's message and the fields this verb CHOSE to put on it, in order.

    Spans included, which is the point: the test using this says no sampled value reaches a span
    field, and a comparison that skipped spans could not say that. What is dropped is only what two
    runs can never match on — the timestamps, the trace, span and log ids, and the duration — none
    of which a verb supplies. Everything left is a value this code passed in, which is where a leak
    would appear.

    Args:
      events: Captured log-foundry events.

    Returns:
      One ``(message, fields)`` pair per event.

    Raises:
      None.
    """
    return [(e.get("message"), e.get("fields")) for e in events]


def _summary_fields(events) -> dict:
    """The fields of the one event this verb emits about the report it assembled.

    Args:
      events: Captured log-foundry events.

    Returns:
      That event's ``fields`` dict.

    Raises:
      StopIteration: When no such event was emitted, which is itself the finding.
    """
    return next(e for e in events if e.get("message") == "assembled report")["fields"]


def test_no_sampled_value_reaches_the_notification_the_index_or_a_span(
    monkeypatch, captured_events
):
    """Holds everything OUTSIDE the report byte-identical whether or not the samples were written.

    The report is read by the one person who asked for the check, through a signed request. A
    notification, a runs-index row and a log line are not: they fan out, they are retained, and
    they are read by whoever can see the plane. So the samples go in the document and nowhere
    else. Asserted as an equality between two runs rather than as a substring search for the
    fixture's values, since a search only ever covers the strings somebody thought to look for.
    """
    sent = []
    monkeypatch.setattr(
        v.notify, "emit_notification", lambda actor, message, **kw: sent.append(message)
    )

    # The SAME report both times, differing only in whether the statement returned a samples
    # cell. A baseline with a different duplicate count would compare two different reports and
    # the equality below would be measuring the count, not the samples.
    plain = _setup(
        monkeypatch,
        objects=_objects(
            {
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _csv(
                    [{"duplicate_rows": 2}]
                )
            }
        ),
    )
    v.handler(_event(), None)
    without = (list(sent), _index(plain), [dict(e) for e in captured_events.events])

    sent.clear()
    sampled = _setup(
        monkeypatch,
        objects=_objects(
            {
                "alice/athenaresults/data-quality/req-1/duplicates/q3.csv": _samples_cell(
                    [["3", "secret-value", "another-secret"]], count=2
                )
            }
        ),
    )
    v.handler(_event(), None)
    with_samples = (
        list(sent),
        _index(sampled),
        [dict(e) for e in captured_events.events][len(without[2]) :],
    )

    # The samples really did land, so the comparison below is between two different reports.
    assert _report(sampled)["exact"]["duplicateSamples"]["rows"][0]["values"] == [
        "secret-value",
        "another-secret",
    ]
    assert with_samples[0] == without[0]
    assert with_samples[1] == without[1]
    # `fields`, not the top level: log-foundry nests every caller-supplied field under it, so a
    # top-level read yields [] on both sides — an equality that holds whatever the verb logs.
    # EVERY event, spans included, since this test's claim is about spans too; only the values no
    # verb supplies are dropped, which is what lets two runs be compared at all.
    assert _caller_fields(with_samples[2]) == _caller_fields(without[2])
    assert _summary_fields(without[2])["row_count"] == 1000
