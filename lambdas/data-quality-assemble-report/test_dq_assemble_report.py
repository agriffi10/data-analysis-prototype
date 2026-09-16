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
from cpcommon.errors import TerminalError

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


