"""SPEC-127 FR-004/FR-005 — the scheduled log sweep.

The weight here is on the two properties that make the sweep safe to leave running unattended:
every message is routable (so nothing poison-loops on the queue), and `service` is untrusted
input on an S3 key path (so nothing escapes the logs/ prefix).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

os.environ.setdefault("LOGS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/dat-prod-logs")
os.environ.setdefault("ADMIN_BUCKET", "dat-prod-athena-admin")

import log_sweep  # noqa: E402


class FakeSQS:
    """Serves receive_message in rounds, then empties — like a real short-poll drain."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.deleted = []

    def receive_message(self, **kwargs):
        assert kwargs["WaitTimeSeconds"] == 0, "the sweep must SHORT poll, never long poll"
        if not self.rounds:
            return {}
        return {"Messages": self.rounds.pop(0)}

    def delete_message_batch(self, QueueUrl, Entries):
        self.deleted.extend(e["ReceiptHandle"] for e in Entries)
        return {}


class FakeS3:
    def __init__(self, fail=False):
        self.puts = []
        self.fail = fail

    def put_object(self, Bucket, Key, Body, **kwargs):
        if self.fail:
            raise RuntimeError("s3 is down")
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _message(body, receipt="r1"):
    return {"Body": body if isinstance(body, str) else json.dumps(body), "ReceiptHandle": receipt}


def _event(service="data-quality", ts="2026-07-22T14:03:11.482Z", **extra):
    return {"timestamp": ts, "service": service, "log_id": "abc", **extra}


@pytest.fixture
def wired(monkeypatch):
    """Wire fake SQS + S3 into the sweep and hand both back."""

    def _wire(rounds, s3_fails=False):
        sqs, s3 = FakeSQS(rounds), FakeS3(fail=s3_fails)
        monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
        monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)
        return sqs, s3

    return _wire


# -- FR-005: routing, and the key-injection surface -------------------------------------


def test_well_formed_event_lands_under_its_service_and_the_events_own_hour(wired):
    sqs, s3 = wired([[_message(_event())]])

    log_sweep.handler({}, None)

    assert len(s3.puts) == 1
    assert s3.puts[0]["Key"].startswith("logs/data-quality/dt=2026-07-22/hh=14/")
    assert s3.puts[0]["Key"].endswith(".ndjson")


def test_partition_comes_from_the_event_not_the_sweep_clock(wired):
    """A replayed event stamped with sweep time is invisible in the window it belongs to."""
    sqs, s3 = wired([[_message(_event(ts="2026-07-01T03:00:00.000Z"))]])

    log_sweep.handler({}, None)

    assert "dt=2026-07-01/hh=03/" in s3.puts[0]["Key"]


def test_service_path_traversal_cannot_escape_the_logs_prefix(wired):
    """`service` arrives in an untrusted body and becomes part of an S3 key."""
    sqs, s3 = wired([[_message(_event(service="../../fallback-results"))]])

    log_sweep.handler({}, None)

    assert len(s3.puts) == 1
    key = s3.puts[0]["Key"]
    assert key.startswith("logs/_unrouted/"), key
    assert ".." not in key
    # The hard guarantee: nothing is written outside logs/.
    assert all(p["Key"].startswith("logs/") for p in s3.puts)


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ("this is not json", "unparseable body"),
        ("[1, 2, 3]", "valid JSON but not an object"),
        (json.dumps({"timestamp": "2026-07-22T14:00:00Z"}), "missing service"),
        (json.dumps(_event(service="Data-Quality")), "uppercase fails the pattern"),
        (json.dumps(_event(service="ab")), "too short"),
        (json.dumps(_event(service="9lives")), "must start with a letter"),
    ],
)
def test_unroutable_bodies_go_to_unrouted_and_are_deleted(wired, body, why):
    sqs, s3 = wired([[_message(body)]])

    log_sweep.handler({}, None)

    assert s3.puts[0]["Key"].startswith("logs/_unrouted/"), why
    assert sqs.deleted == ["r1"], f"{why}: must be deleted, or it poison-loops every 5 minutes"


def test_unrouted_body_is_preserved_verbatim(wired):
    sqs, s3 = wired([[_message("this is not json")]])

    log_sweep.handler({}, None)

    assert "this is not json" in s3.puts[0]["Body"].decode("utf-8")


# -- FR-005: put-then-delete ordering ---------------------------------------------------


def test_messages_are_deleted_only_after_a_successful_put(wired):
    sqs, s3 = wired([[_message(_event())]], s3_fails=True)

    log_sweep.handler({}, None)

    assert s3.puts == []
    assert sqs.deleted == [], "a failed put must leave the messages on the queue to redeliver"


def test_a_failed_put_does_not_abort_the_whole_sweep(wired, monkeypatch):
    """One service's S3 failure must not cost the other services their writes."""
    sqs, s3 = wired(
        [[_message(_event(service="data-quality"), "r1"), _message(_event(service="observability"), "r2")]]
    )
    real_put = s3.put_object

    def flaky(Bucket, Key, Body, **kwargs):
        if "data-quality" in Key:
            raise RuntimeError("s3 is down for this key")
        return real_put(Bucket=Bucket, Key=Key, Body=Body, **kwargs)

    monkeypatch.setattr(s3, "put_object", flaky)

    result = log_sweep.handler({}, None)

    assert any("observability" in p["Key"] for p in s3.puts)
    assert sqs.deleted == ["r2"]
    assert result["swept"] == 2


def test_one_object_per_service_dt_hh_group(wired):
    sqs, s3 = wired(
        [
            [
                _message(_event(service="data-quality", ts="2026-07-22T14:00:00Z"), "a"),
                _message(_event(service="data-quality", ts="2026-07-22T14:59:00Z"), "b"),
                _message(_event(service="data-quality", ts="2026-07-22T15:00:00Z"), "c"),
                _message(_event(service="observability", ts="2026-07-22T14:00:00Z"), "d"),
            ]
        ]
    )

    log_sweep.handler({}, None)

    assert len(s3.puts) == 3, "hh=14 dq, hh=15 dq, hh=14 observability"
    dq14 = next(p for p in s3.puts if "data-quality/dt=2026-07-22/hh=14" in p["Key"])
    assert len(dq14["Body"].decode("utf-8").strip().split("\n")) == 2


# -- FR-004: the poll model -------------------------------------------------------------


def test_sweep_short_polls_and_loops_until_a_round_is_empty(wired):
    """FakeSQS asserts WaitTimeSeconds==0; this covers the multi-round drain."""
    sqs, s3 = wired([[_message(_event(), "a")], [_message(_event(), "b")]])

    result = log_sweep.handler({}, None)

    assert result["swept"] == 2
    assert sorted(sqs.deleted) == ["a", "b"]


def test_empty_queue_completes_without_writing(wired):
    sqs, s3 = wired([])

    assert log_sweep.handler({}, None) == {"swept": 0, "written": 0}
    assert s3.puts == []


def test_round_cap_truncates_and_says_so(wired, monkeypatch, caplog):
    """A silent cap reads as 'swept everything' when it didn't."""
    monkeypatch.setattr(log_sweep, "MAX_MESSAGES", 20)
    rounds = [[_message(_event(), f"r{i}-{n}") for n in range(10)] for i in range(5)]
    sqs, s3 = wired(rounds)

    with caplog.at_level("WARNING"):
        result = log_sweep.handler({}, None)

    assert result["swept"] == 20
    assert any("cap" in r.message for r in caplog.records)


# -- FR-005: the handler is total -------------------------------------------------------


def test_a_completely_malformed_message_does_not_raise(wired):
    """The sweep must return normally — a throw means redelivery forever."""
    sqs, s3 = wired([[{"NoBodyKey": True}, _message(_event(), "ok")]])

    result = log_sweep.handler({}, None)

    assert result["swept"] == 2


def test_unparseable_timestamp_falls_back_and_is_counted(wired, caplog):
    sqs, s3 = wired([[_message(_event(ts="not-a-timestamp"))]])

    with caplog.at_level("WARNING"):
        log_sweep.handler({}, None)

    assert s3.puts[0]["Key"].startswith("logs/data-quality/dt=")
    assert any("timestamp" in r.message for r in caplog.records)
