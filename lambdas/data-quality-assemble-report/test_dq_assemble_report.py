"""Unit tests for the data-quality assemble-report Lambda (SPEC-112 FR-003/FR-004).

Pure logic, AWS stubbed. The report content itself is covered by test_report_dqcommon.py;
what is tested here is the READ side (finding Athena's result objects), the WRITE side (a
key that is a pure function of requestId), and the replay guarantee that follows from it.
"""

import csv
import io
import json
import os
import re
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
        "location": "alice/sales/",
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


def _written(fake):
    """The REPORT document, selected by key rather than by being the last write.

    It used to be `puts[-1]`. SPEC-123 made this verb write twice — the report, then the
    per-space runs index — so "the last thing put" silently became the index, and every
    assertion below started reading the wrong object.
    """
    reports = [p for p in fake.puts if p["Key"].endswith(v.REPORT_BASENAME)]
    assert reports, "the report object was never written"
    return json.loads(reports[-1]["Body"])


def _index(fake):
    """The runs-index document (SPEC-123), or None if this run never wrote one."""
    indexes = [p for p in fake.puts if p["Key"].endswith("index.json")]
    return json.loads(indexes[-1]["Body"]) if indexes else None


def _state_machine():
    """Parse the DEPLOYED ASL template, with its Terraform placeholders stubbed out.

    Read from infra/ rather than duplicated here on purpose: a copy would drift, and the
    whole value of the contract tests below is that they fail when one side moves.
    """
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "infra", "modules", "data-quality", "state-machine.asl.json.tftpl",
    )
    with open(path) as handle:
        return json.loads(re.sub(r"\$\{[^}]+\}", "stub-arn", handle.read()))


def _has_path(state, path):
    """Whether a JSONPath like ``$.a.b`` resolves to an existing KEY in ``state``.

    Walks nested segments rather than slicing off "$." and comparing to top-level keys: the
    sibling table-builder machine already reads `$.space.database`, so a naive check would
    false-fail the first time this machine grows a nested read. Only the key's PRESENCE
    matters — a null value is fine in a Pass state, a missing key is fatal.
    """
    cursor = state
    for segment in path.removeprefix("$.").split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            return False
        cursor = cursor[segment]
    return True


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


# ── Finding Athena's result objects ──────────────────────────────────────────


def test_a_result_that_is_nowhere_raises_a_terminal_with_a_friendly_reason(monkeypatch):
    objects = _objects()
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    _setup(monkeypatch, objects=objects)

    with pytest.raises(TerminalError) as excinfo:
        v.handler(_event(), None)

    assert excinfo.value.reason == "query_failed"


# ── The summary payload (FR-003) and the SPEC-123 seam (FR-004) ──────────────


# ── Faults ───────────────────────────────────────────────────────────────────


# -- SPEC-132: counts and the key, never a result row -----------------------------------
