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

import pytest  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402

import dq_assemble_report as v  # noqa: E402
import dq_drop_temp_tables as cleanup  # noqa: E402

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

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3's kwarg casing
        self.gets.append(Key)
        if Key in self.missing or Key not in self.objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.objects[Key] = Body
        return {}

    def list_objects_v2(self, Bucket, Prefix):  # noqa: N803
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
    return json.loads(fake.puts[-1]["Body"])


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


def test_a_replay_overwrites_the_same_object_and_changes_only_completedAt(monkeypatch):
    """THE replay guarantee. No verb in this codebase does request-id idempotency checking,
    so a Step Functions Retry or an SQS redelivery re-runs this verb — and the ONLY thing
    that stops it leaving a second, divergent report is that the key is derived from the
    requestId and nothing in the body depends on when it ran."""
    fake = _setup(monkeypatch)

    first = v.handler(_event(), None)
    second = v.handler(_event(), None)

    assert first["reportKey"] == second["reportKey"]
    reports = [json.loads(put["Body"]) for put in fake.puts]
    assert len(fake.puts) == 2
    # One object, not two: same bucket AND same key on both writes.
    assert {(p["Bucket"], p["Key"]) for p in fake.puts} == {(BUCKET, f"{PREFIX}/report.json")}
    for document in reports:
        document.pop("completedAt")
    assert reports[0] == reports[1]


def test_the_written_report_is_the_assembled_document(monkeypatch):
    fake = _setup(monkeypatch)

    v.handler(_event(), None)

    document = _written(fake)
    assert document["requestId"] == "req-1"
    assert document["verdict"] == "clean"
    assert document["exact"]["rowCount"] == 1000
    assert document["exact"]["crossFile"]["columnsAgree"] is True


# ── Finding Athena's result objects ──────────────────────────────────────────


def test_results_are_read_at_the_execution_id_key(monkeypatch):
    fake = _setup(monkeypatch)

    v.handler(_event(), None)

    assert "alice/athenaresults/data-quality/req-1/profile/q1.csv" in fake.gets
    assert fake.lists == []  # the constructed key hit, so no LIST was needed


def test_a_result_not_at_the_expected_key_falls_back_to_listing(monkeypatch):
    """The ONE assumption in this verb no unit test can prove: Athena names a result object
    after its execution id. Nothing else in this repo has ever read a result file, so a
    miss must degrade to a LIST rather than lose a check that has already run three queries
    and a byte scan."""
    objects = _objects(
        {"alice/athenaresults/data-quality/req-1/profile/somewhere-else.csv": _profile()}
    )
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    fake = _setup(monkeypatch, objects=objects)

    v.handler(_event(), None)

    assert "alice/athenaresults/data-quality/req-1/profile/" in fake.lists
    assert _written(fake)["exact"]["rowCount"] == 1000  # the fallback found the REAL result


def test_the_metadata_sidecar_is_never_mistaken_for_the_result(monkeypatch):
    """Athena writes a .csv.metadata beside the result. It sorts adjacent, and parsing it
    as the result would yield a report full of zeros rather than an error."""
    objects = _objects(
        {
            "alice/athenaresults/data-quality/req-1/profile/aaa.csv.metadata": b"not-a-result",
            "alice/athenaresults/data-quality/req-1/profile/zzz.csv": _profile(),
        }
    )
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    fake = _setup(monkeypatch, objects=objects)

    v.handler(_event(), None)

    # Assert the REAL result was read, not merely that nothing raised. Parsing the sidecar
    # yields a header and no rows, so the report still assembles and still says "clean" —
    # over a row count of zero. Checking the verdict alone would pass on a report that had
    # silently lost every figure in it.
    assert _written(fake)["exact"]["rowCount"] == 1000


def test_a_result_that_is_nowhere_raises_a_terminal_with_a_friendly_reason(monkeypatch):
    objects = _objects()
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    _setup(monkeypatch, objects=objects)

    with pytest.raises(TerminalError) as excinfo:
        v.handler(_event(), None)

    assert excinfo.value.reason == "query_failed"


def test_a_degraded_query_is_never_read_at_all(monkeypatch):
    """A not_computed block has no result object; asking for one would turn a degraded
    figure into a failed request — the exact inversion SPEC-111 FR-003 exists to prevent."""
    fake = _setup(monkeypatch)
    event = _event()
    event["duplicates"] = {"status": "not_computed", "reason": "EXCEEDED_RESOURCES"}

    out = v.handler(event, None)

    assert not any("duplicates/" in key for key in fake.gets)
    assert _written(fake)["exact"]["duplicateRows"]["status"] == "not_computed"
    # The verdict stays "clean" — nothing was FOUND — and hasApproximateFigures is what
    # stops that reading as an all-clear. This pairing is the spec's remedy for exactly the
    # "unqualified clean over a check that did not run" problem, so SPEC-114 MUST render the
    # qualifier: "clean" alone here would be a lie by omission.
    assert out["verdict"] == "clean"
    assert out["hasApproximateFigures"] is True


def test_a_json_source_reads_no_ragged_result(monkeypatch):
    fake = _setup(monkeypatch)
    event = _event()
    event["ragged"] = None

    v.handler(event, None)

    assert not any("ragged/" in key for key in fake.gets)


# ── The summary payload (FR-003) and the SPEC-123 seam (FR-004) ──────────────


def test_the_summary_carries_everything_a_notification_and_an_index_entry_need(monkeypatch):
    """FR-004's seam: SPEC-123's index entry is built from these fields, so the index write
    it adds needs nothing this verb does not already have."""
    _setup(monkeypatch)

    out = v.handler(_event(), None)

    for field in (
        "requestId",
        "location",
        "format",
        "fileCount",
        "verdict",
        "hasApproximateFigures",
        "completedAt",
        "reportKey",
        "topIssues",
    ):
        assert field in out, field


def test_the_summary_never_carries_the_full_report(monkeypatch):
    _setup(monkeypatch)

    out = v.handler(_event(), None)

    assert "exact" not in out
    assert "approximate" not in out


def test_the_request_object_is_threaded_through(monkeypatch):
    """RecordSuccess/RecordFailure hard-fail on an ABSENT JSONPath key (States.Runtime),
    which a Pass state cannot Catch — dropping requestId/actor here costs the user their
    notification entirely."""
    _setup(monkeypatch)

    out = v.handler(_event(), None)

    assert out["requestId"] == "req-1"
    assert out["actor"] == "alice"
    assert out["location"] == "alice/sales/"


# ── Faults ───────────────────────────────────────────────────────────────────


def test_a_throttled_write_raises_transient_so_the_state_machine_retries(monkeypatch):
    """The report is the artefact and every query has already been paid for; a SlowDown
    must cost a retry, not the check."""
    fake = _setup(monkeypatch)

    def _throttle(**kw):
        raise _FakeClientError("SlowDown")

    monkeypatch.setattr(fake, "put_object", _throttle)

    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_record_success_can_read_every_field_it_names(monkeypatch):
    """The state machine's contract, asserted against the state that ACTUALLY feeds it.

    RecordSuccess is a Pass state, and a Pass state's JSONPath HARD-FAILS on an ABSENT key
    with States.Runtime — which a Pass state cannot Catch. So a field named there but not
    present does not degrade anything: the execution dies before NotifyFailure and the user
    is told NOTHING about a check that SUCCEEDED. That failure mode has already been hit
    once in this arc (the SPEC-108 live smoke test).

    THE STATE FEEDING RecordSuccess IS DROP-TEMP-TABLES', NOT THIS VERB'S. DropTempTables
    carries OutputPath "$.Payload", so it REPLACES the state wholesale — asserting against
    assemble-report's output alone would pass while drop-temp-tables quietly dropped every
    field, which is exactly what an earlier version of this test did.
    """
    asl = _state_machine()
    reads = [
        path for key, path in asl["States"]["RecordSuccess"]["Parameters"].items()
        if key.endswith(".$")
    ]
    assert reads, "RecordSuccess reads nothing — this test would pass vacuously"
    _setup(monkeypatch)

    # The real success path: AssembleReport -> DropTempTables -> RecordSuccess.
    state = cleanup.handler(v.handler(_event(), None), None)

    missing = [path for path in reads if not _has_path(state, path)]
    assert not missing, f"RecordSuccess reads fields the success path never sets: {missing}"


def test_the_pre_identity_failure_path_actually_routes_through_the_seed():
    """Pinning the WIRING, not just the seed's contents.

    A subset check between two blobs in this file is satisfied whether or not the seed is on
    the path at all. Repoint ValidateAuthorize's Catch straight at ParseError and a
    malformed request reaches RecordFailure with no requestId/actor/location keys — dying
    uncatchably, on the one failure that happens before the request identity exists. The
    table-builder suite pins its equivalent edge the same way.
    """
    validate = _state_machine()["States"]["ValidateAuthorize"]

    assert validate["Catch"][0]["Next"] == "ValidateFailureSeed"


def test_the_seed_supplies_every_identity_field_record_failure_names():
    """The pre-identity path's contract.

    A validate-authorize failure never has a location — its input was the raw SQS array —
    so ValidateFailureSeed must seed every identity field RecordFailure names. Miss one and
    a malformed or unauthorized request produces no notification at all.

    This covers the PRE-IDENTITY path only. The other entries to RecordFailure (a Catch on
    any of the seven Task states) carry the threaded request object instead, and are covered
    by each verb's own "request object is threaded through" test.
    """
    asl = _state_machine()
    reads = {
        path for key, path in asl["States"]["RecordFailure"]["Parameters"].items()
        if key.endswith(".$")
    }
    assert reads, "RecordFailure reads nothing — this test would pass vacuously"
    # Nothing is added between the seed and RecordFailure any more — the ParseError state
    # that used to sit there was removed (it decoded the Cause with an intrinsic that
    # raises an uncatchable States.Runtime), so EVERY field read must come from the seed.
    identity = set(reads)
    seed = {
        key.removesuffix(".$"): value
        for key, value in asl["States"]["ValidateFailureSeed"]["Parameters"].items()
    }

    missing = [path for path in identity if not _has_path(seed, path)]
    assert not missing, f"RecordFailure reads fields the seed never supplies: {missing}"


def test_a_throttled_fallback_listing_also_raises_transient(monkeypatch):
    """The fallback path needs the same mapping as every other S3 call in this verb — a
    SlowDown arriving as a bare ClientError is not in the Retry list."""
    objects = _objects()
    del objects["alice/athenaresults/data-quality/req-1/profile/q1.csv"]
    fake = _setup(monkeypatch, objects=objects)

    def _throttle(**kw):
        raise _FakeClientError("SlowDown")

    monkeypatch.setattr(fake, "list_objects_v2", _throttle)

    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_profile_result_with_no_total_row_fails_the_check(monkeypatch):
    """A green verdict over data nothing measured is worse than no report at all, so this
    must surface as a terminal — not as a clean report full of zeros."""
    objects = _objects(
        {
            "alice/athenaresults/data-quality/req-1/profile/q1.csv": _csv(
                [{"source_file": "s3://b/alice/sales/a.csv", "is_total": 0, "row_count": 5}]
            )
        }
    )
    fake = _setup(monkeypatch, objects=objects)

    with pytest.raises(TerminalError) as excinfo:
        v.handler(_event(), None)

    assert excinfo.value.reason == "query_failed"
    assert fake.puts == []  # and NOTHING was written


def test_a_malformed_state_raises_a_terminal_rather_than_a_key_error(monkeypatch):
    _setup(monkeypatch)
    event = _event()
    del event["reportPrefix"]

    with pytest.raises(TerminalError) as excinfo:
        v.handler(event, None)

    assert excinfo.value.reason == "invalid_request"
