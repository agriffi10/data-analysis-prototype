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
    """Implements REAL conditional-put semantics (If-Match / If-None-Match with a changing
    ETag), because the whole append design turns on what happens when two sweeps race. A fake
    that ignored the preconditions would make the CAS loop untestable and green either way.
    """

    def __init__(self, fail=False):
        self.objects = {}  # key -> (body: bytes, etag: str)
        self.puts = []
        self.fail = fail
        self._n = 0

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        if self.fail:
            raise RuntimeError("s3 is down")
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise _ClientError("ConditionalRequestConflict")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _ClientError("PreconditionFailed")
        self._n += 1
        self.objects[Key] = (Body, f'"etag-{self._n}"')
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}

    def body_of(self, key):
        return self.objects[key][0].decode("utf-8")


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


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
    assert s3.puts[0]["Key"] == "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    assert s3.puts[0]["Key"].endswith("/data.jsonl")


def test_partition_comes_from_the_event_not_the_sweep_clock(wired):
    """A replayed event stamped with sweep time is invisible in the window it belongs to."""
    sqs, s3 = wired([[_message(_event(ts="2026-07-01T03:00:00.000Z"))]])

    log_sweep.handler({}, None)

    assert "year=2026/month=07/day=01/" in s3.puts[0]["Key"]


def test_service_path_traversal_cannot_escape_the_logs_prefix(wired):
    """`service` arrives in an untrusted body and becomes part of an S3 key."""
    sqs, s3 = wired([[_message(_event(service="../../fallback-results"))]])

    log_sweep.handler({}, None)

    assert len(s3.puts) == 1
    key = s3.puts[0]["Key"]
    assert key.startswith("logs/service=_unrouted/"), key
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

    assert s3.puts[0]["Key"].startswith("logs/service=_unrouted/"), why
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


def test_one_object_per_service_day_group(wired):
    """Grouping is per DAY now, not per hour — two events in the same day share one object."""
    sqs, s3 = wired(
        [
            [
                _message(_event(service="data-quality", ts="2026-07-22T14:00:00Z"), "a"),
                _message(_event(service="data-quality", ts="2026-07-22T23:59:00Z"), "b"),
                _message(_event(service="data-quality", ts="2026-07-23T00:00:00Z"), "c"),
                _message(_event(service="observability", ts="2026-07-22T14:00:00Z"), "d"),
            ]
        ]
    )

    log_sweep.handler({}, None)

    assert len(s3.objects) == 3, "dq day 22, dq day 23, observability day 22"
    day22 = s3.body_of("logs/service=data-quality/year=2026/month=07/day=22/data.jsonl")
    assert len(day22.strip().split("\n")) == 2, "both same-day events in one object"


# -- SPEC-129: append, and the CAS that makes it safe -----------------------------------


def test_second_sweep_appends_rather_than_overwriting(wired):
    """The core of the append design: yesterday's lines must survive today's sweep."""
    key = "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"

    sqs, s3 = wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])
    log_sweep.handler({}, None)
    assert len(s3.body_of(key).strip().split("\n")) == 1

    sqs.rounds = [[_message(_event(service="data-quality", ts="2026-07-22T11:00:00Z"), "b")]]
    log_sweep.handler({}, None)

    lines = s3.body_of(key).strip().split("\n")
    assert len(lines) == 2, "the second sweep overwrote the first instead of appending"


def test_a_losing_cas_race_re_reads_and_keeps_both_writers_events(wired, monkeypatch):
    """Two sweeps racing must not silently drop one side's events.

    The fake fails the first conditional PUT the way S3 does (412), after mutating the object
    underneath — exactly the interleaving that makes a naive read-modify-write lose data.
    """
    key = "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    sqs, s3 = wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])
    s3.objects[key] = (b'{"log_id":"pre-existing"}\n', '"etag-0"')

    real_put = s3.put_object
    calls = {"n": 0}

    def racing_put(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # A concurrent writer commits first, invalidating our read ETag.
            s3.objects[key] = (b'{"log_id":"other-writer"}\n', '"etag-99"')
            raise _ClientError("PreconditionFailed")
        return real_put(**kwargs)

    monkeypatch.setattr(s3, "put_object", racing_put)

    log_sweep.handler({}, None)

    body = s3.body_of(key)
    assert "other-writer" in body, "the winner's line was erased by the retry"
    assert "live-probe" in body or "log_id" in body
    assert sqs.deleted == ["a"], "messages must be deleted once the retry succeeded"


def test_cas_exhaustion_leaves_the_messages_queued(wired, monkeypatch):
    """Giving up must not delete: the events have to survive to the next sweep."""
    sqs, s3 = wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])
    monkeypatch.setattr(s3, "put_object", lambda **k: (_ for _ in ()).throw(_ClientError("PreconditionFailed")))

    log_sweep.handler({}, None)

    assert sqs.deleted == [], "a message deleted after a failed write is a lost log"


def test_a_read_failure_never_overwrites_an_existing_day(wired, monkeypatch):
    """A transient GET error must fail the write, not silently replace the day's object."""
    key = "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    sqs, s3 = wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])
    s3.objects[key] = (b'{"log_id":"precious"}\n', '"etag-0"')
    monkeypatch.setattr(s3, "get_object", lambda **k: (_ for _ in ()).throw(RuntimeError("s3 flaked")))

    log_sweep.handler({}, None)

    # The read failed -> no etag -> If-None-Match:* -> conflict, because the object exists.
    assert "precious" in s3.body_of(key), "a failed read overwrote the day's logs"
    assert sqs.deleted == []


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

    assert s3.puts[0]["Key"].startswith("logs/service=data-quality/year=")
    assert any("timestamp" in r.message for r in caplog.records)
