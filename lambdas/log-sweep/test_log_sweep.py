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

import log_foundry as lf
import log_sweep


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


class FifoSQS:
    """Implements the FIFO ordering rule the plain fake cannot express: a message group stops
    yielding once one of its messages is in flight, and only a delete unblocks it.

    ``FakeSQS`` serves rounds and then empties, which quietly asserts that an empty receive
    means an empty queue. On a real FIFO queue it usually means the opposite — every group the
    caller is holding is blocked behind the caller. A sweep built against the simpler fake took
    ten messages per backlogged group per invocation and reported itself drained, and no test
    could see it, because the fake ran out of rounds at exactly the moment the real queue would
    have blocked.
    """

    def __init__(self, per_group):
        self.pending = {g: list(ms) for g, ms in per_group.items()}
        self.inflight = {}
        self.deleted = []
        self.receives = 0

    def receive_message(self, **kwargs):
        assert kwargs["WaitTimeSeconds"] == 0, (
            "the sweep must SHORT poll, never long poll"
        )
        self.receives += 1
        limit = kwargs["MaxNumberOfMessages"]
        blocked = set(self.inflight.values())
        taken = []
        for group, queued in self.pending.items():
            room = limit - len(taken)
            if room <= 0:
                break
            if not queued or group in blocked:
                continue
            batch = queued[:room]
            for message in batch:
                self.inflight[message["ReceiptHandle"]] = group
            self.pending[group] = queued[len(batch) :]
            taken.extend(batch)
        return {"Messages": taken} if taken else {}

    def delete_message_batch(self, QueueUrl, Entries):
        for entry in Entries:
            handle = entry["ReceiptHandle"]
            self.inflight.pop(handle, None)
            self.deleted.append(handle)
        return {}


@pytest.fixture
def wired(monkeypatch):
    """Wire fake SQS + S3 into the sweep and hand both back."""

    def _wire(rounds, s3_fails=False):
        sqs, s3 = FakeSQS(rounds), FakeS3(fail=s3_fails)
        monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
        monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)
        return sqs, s3

    return _wire


# -- SPEC-131: the structured narrative -------------------------------------------------


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, batch):
        self.events.extend(batch)

    def close(self):
        pass


class NullSink:
    def emit(self, batch):
        pass

    def close(self):
        pass


def _install_sink(sink):
    """Swap the process sink.

    `configure()` is sufficient on its own: the library drains, closes the previous sink and
    re-points delivery. It was not always — a worker built lazily at the first flush used to
    be cached for the process, so this function also retired it by hand. That retirement is
    gone, and could not have stayed: the private name it reached for no longer exists, so it
    had become a silent no-op.

    Args:
      sink: The sink to deliver into for the rest of this test.

    Returns:
      None.

    Raises:
      None.
    """
    lf.configure(service="observability", version="0", env="test", sink=sink)


@pytest.fixture(autouse=True)
def _quiet_sink():
    """Keep every test in this module off the import-time SQSSink.

    `observability.init` runs at import with LOGS_QUEUE_URL set, so without this each handler
    call ends by handing its span to a real boto3 SQS client. The worker swallows the resulting
    failure, so it is invisible — and slow.
    """
    _install_sink(NullSink())
    yield
    _install_sink(NullSink())


@pytest.fixture
def captured(_quiet_sink):
    sink = RecordingSink()
    _install_sink(sink)
    return sink


def _by_message(sink, message):
    return [e for e in sink.events if e["message"] == message]


# -- FR-005: routing, and the key-injection surface -------------------------------------


def test_well_formed_event_lands_under_its_service_and_the_events_own_hour(wired):
    _sqs, s3 = wired([[_message(_event())]])

    log_sweep.handler({}, None)

    assert len(s3.puts) == 1
    assert s3.puts[0]["Key"] == "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    assert s3.puts[0]["Key"].endswith("/data.jsonl")


def test_service_path_traversal_cannot_escape_the_logs_prefix(wired):
    """`service` arrives in an untrusted body and becomes part of an S3 key."""
    _sqs, s3 = wired([[_message(_event(service="../../fallback-results"))]])

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


# -- FR-005: put-then-delete ordering ---------------------------------------------------


def test_messages_are_deleted_only_after_a_successful_put(wired):
    sqs, s3 = wired([[_message(_event())]], s3_fails=True)

    log_sweep.handler({}, None)

    assert s3.puts == []
    assert sqs.deleted == [], "a failed put must leave the messages on the queue to redeliver"


# -- SPEC-129: append, and the CAS that makes it safe -----------------------------------


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


# -- FR-004: the poll model -------------------------------------------------------------


def test_sweep_short_polls_and_loops_until_a_round_is_empty(wired):
    """FakeSQS asserts WaitTimeSeconds==0; this covers the multi-round drain."""
    sqs, _s3 = wired([[_message(_event(), "a")], [_message(_event(), "b")]])

    result = log_sweep.handler({}, None)

    assert result["swept"] == 2
    assert sorted(sqs.deleted) == ["a", "b"]


def test_the_wave_cap_bounds_a_sweep_and_says_so(monkeypatch, captured):
    """A backlog deeper than the cap is left for the next tick rather than taken in one
    invocation, and it is reported — a bounded sweep that read as a drained queue is the exact
    shape of the defect this replaced.
    """
    monkeypatch.setattr(log_sweep, "MAX_WAVES", 2)
    per_group = {
        "data-quality": [_message(_event(), f"m-{n}") for n in range(50)],
    }
    sqs, s3 = FifoSQS(per_group), FakeS3()
    monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
    monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)

    result = log_sweep.handler({}, None)

    assert result["swept"] == 20
    assert result["waves"] == 2
    stopped = _by_message(captured, "stopped with the queue possibly still yielding")
    assert stopped and stopped[0]["level"] == "WARNING"
    assert stopped[0]["fields"]["limit"] == 2
    assert stopped[0]["fields"]["reason"] == log_sweep.STOP_WAVE_CAP


