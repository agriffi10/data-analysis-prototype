"""SPEC-127 FR-004/FR-005 — the scheduled log sweep.

The weight here is on the two properties that make the sweep safe to leave running unattended:
every message is routable (so nothing poison-loops on the queue), and `service` is untrusted
input on an S3 key path (so nothing escapes the logs/ prefix).
"""

import json
import os
import sys
from pathlib import Path

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


class RaisingSink:
    def emit(self, batch):
        raise RuntimeError("sink exploded")

    def close(self):
        pass


def _install_sink(sink):
    """Swap the process sink AND retire the worker built from the previous one.

    The worker is created lazily from whatever sink was configured at the first flush and then
    cached for the process, so reconfiguring alone would leave every later event going to the
    sink this test replaced.
    """
    from log_foundry import decorator as lf_decorator

    worker = getattr(lf_decorator, "_worker", None)
    if worker is not None:
        worker.shutdown()
        lf_decorator._worker = None
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


def _levels(sink):
    """Every event that is not a span boundary — the narrative proper."""
    return [e for e in sink.events if e["message"] not in ("span.start", "span.end")]


def _by_message(sink, message):
    return [e for e in sink.events if e["message"] == message]


def _spans(sink, function):
    return [e for e in sink.events if e["message"] == "span.start" and e["function"] == function]


# -- FR-001: intake ---------------------------------------------------------------------


def test_intake_reports_the_message_count_and_the_day_groups(wired, captured):
    wired(
        [
            [
                _message(_event(service="data-quality"), "a"),
                _message(_event(service="observability"), "b"),
            ]
        ]
    )

    log_sweep.handler({}, None)

    received = _by_message(captured, "received")
    assert len(received) == 1
    assert received[0]["fields"]["messages"] == 2
    assert received[0]["fields"]["groups"] == 2


def test_the_receive_loop_gets_its_own_child_span(wired, captured):
    """The poll loop and the writes fail in completely different ways, and this is the half
    that is billed per round — a single duration covering both tells you neither.
    """
    wired([[_message(_event(), "a")]])

    log_sweep.handler({}, None)

    receive = _spans(captured, "receive")
    assert receive, "no receive span"
    sweep = _spans(captured, "sweep")
    assert receive[0]["trace_id"] == sweep[0]["trace_id"]
    assert receive[0]["parent_span_id"] == sweep[0]["span_id"]


def test_a_truncated_round_says_so_with_the_cap_and_the_count(wired, captured, monkeypatch):
    monkeypatch.setattr(log_sweep, "MAX_MESSAGES", 20)
    wired([[_message(_event(), f"r{i}-{n}") for n in range(10)] for i in range(5)])

    log_sweep.handler({}, None)

    capped = _by_message(captured, "hit the message cap")
    assert capped and capped[0]["fields"] == {
        **capped[0]["fields"],
        "limit": 20,
        "taken": 20,
    }
    assert capped[0]["level"] == "WARNING"


def test_an_empty_sweep_narrates_nothing(wired, captured):
    """Boundary spans only. The sweep fires every 10 minutes and is usually empty, so an
    intake event on an empty round would be 144 events a day saying nothing happened — into
    the queue this function drains.
    """
    wired([])

    log_sweep.handler({}, None)

    assert _levels(captured) == []


# -- FR-002: every destination is named, with its outcome -------------------------------


def test_each_destination_gets_a_child_span_and_an_entry_and_success_event(wired, captured):
    key = "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])

    log_sweep.handler({}, None)

    assert _spans(captured, "append-day"), "no append-day span"
    appending = _by_message(captured, "appending")
    appended = _by_message(captured, "appended")
    assert appending and appending[0]["fields"]["key"] == key
    assert appending[0]["fields"]["events"] == 1
    assert appended and appended[0]["fields"]["key"] == key
    assert appended[0]["fields"]["events"] == 1
    assert appended[0]["fields"]["bytes"] > 0


def test_a_write_failure_is_an_error_event_with_a_stable_reason(wired, captured):
    """The case that matters is the one where the data did not land, so this asserts on the
    path where the messages stay queued.
    """
    sqs, _ = wired([[_message(_event(), "a")]], s3_fails=True)

    log_sweep.handler({}, None)

    failed = _by_message(captured, "append failed")
    assert failed and failed[0]["level"] == "ERROR"
    assert failed[0]["fields"]["reason"] == "write-failed"
    assert failed[0]["fields"]["events"] == 1
    assert sqs.deleted == [], "the premise of the test: the events are still queued"


def test_cas_exhaustion_reports_its_own_reason(wired, captured, monkeypatch):
    """A different token from a write failure, because they need different responses: one is
    contention, the other is a broken bucket.
    """
    _, s3 = wired([[_message(_event(), "a")]])
    monkeypatch.setattr(
        s3, "put_object", lambda **k: (_ for _ in ()).throw(_ClientError("PreconditionFailed"))
    )

    log_sweep.handler({}, None)

    failed = _by_message(captured, "append failed")
    assert failed and failed[0]["fields"]["reason"] == "precondition-exhausted"


# -- FR-003: degraded paths are warnings, not silence -----------------------------------


def test_every_cas_retry_is_reported_because_the_count_is_the_signal(wired, captured, monkeypatch):
    _, s3 = wired([[_message(_event(), "a")]])
    monkeypatch.setattr(
        s3, "put_object", lambda **k: (_ for _ in ()).throw(_ClientError("PreconditionFailed"))
    )

    log_sweep.handler({}, None)

    retries = _by_message(captured, "day object changed under us")
    assert len(retries) == log_sweep.MAX_CAS_ATTEMPTS
    assert [e["fields"]["attempt"] for e in retries] == list(
        range(1, log_sweep.MAX_CAS_ATTEMPTS + 1)
    )


def test_a_large_day_object_warns_with_its_size(wired, captured, monkeypatch):
    key = "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    _, s3 = wired([[_message(_event(service="data-quality", ts="2026-07-22T10:00:00Z"), "a")]])
    monkeypatch.setattr(log_sweep, "LARGE_OBJECT_WARN_BYTES", 10)
    s3.objects[key] = (b"x" * 64 + b"\n", '"etag-0"')

    log_sweep.handler({}, None)

    large = _by_message(captured, "day object is large")
    assert large and large[0]["fields"]["key"] == key
    assert large[0]["fields"]["bytes"] == 65


def test_undated_events_are_counted_not_hidden_in_the_partitions(wired, captured):
    wired([[_message(_event(ts="not-a-timestamp"), "a"), _message(_event(), "b")]])

    log_sweep.handler({}, None)

    undated = _by_message(captured, "events had no usable timestamp")
    assert undated and undated[0]["fields"]["undated"] == 1


def test_a_failed_delete_says_the_events_will_repeat_not_that_they_were_lost(
    wired, captured, monkeypatch
):
    """25 messages is three SQS delete chunks on purpose: the event must be per GROUP, not per
    chunk. A per-chunk emitter is O(messages) on exactly the path where the queue is already
    unhappy — which is the feedback loop FR-005 exists to prevent.
    """
    sqs, _ = wired([[_message(_event(), f"r{n}") for n in range(25)]])
    monkeypatch.setattr(
        sqs, "delete_message_batch", lambda **k: (_ for _ in ()).throw(RuntimeError("sqs down"))
    )

    log_sweep.handler({}, None)

    failed = _by_message(captured, "delete failed; events will be appended again next sweep")
    assert len(failed) == 1, f"one event per group, not per chunk — got {len(failed)}"
    assert failed[0]["fields"]["events"] == 25
    assert failed[0]["fields"]["lost"] is False


def test_unroutable_bodies_are_counted_and_the_body_is_never_logged(wired, captured):
    """Not on sensitivity grounds — the body is already preserved verbatim under
    service=_unrouted/. It is unbounded input from a queue, and echoing it into a day object
    is the growth the read-modify-write design exists to avoid.
    """
    poison = '{"service": "../../etc/passwd", "secret": "do-not-echo-me"}'
    wired([[_message(poison, "a")]])

    log_sweep.handler({}, None)

    unrouted = _by_message(captured, "bodies could not be routed")
    assert unrouted and unrouted[0]["fields"]["unrouted"] == 1
    assert "do-not-echo-me" not in json.dumps(captured.events)
    assert "etc/passwd" not in json.dumps(captured.events)


# -- FR-004: the outcome event is total -------------------------------------------------


def test_the_outcome_event_reports_written_and_failed(wired, captured, monkeypatch):
    """The old summary reported swept/groups/written and no failure count, so a sweep that
    wrote two destinations of three read as a success in every field it had.
    """
    _, s3 = wired(
        [
            [
                _message(_event(service="data-quality"), "a"),
                _message(_event(service="observability"), "b"),
            ]
        ]
    )
    real_put = s3.put_object
    monkeypatch.setattr(
        s3,
        "put_object",
        lambda **k: (_ for _ in ()).throw(RuntimeError("down"))
        if "data-quality" in k["Key"]
        else real_put(**k),
    )

    log_sweep.handler({}, None)

    swept = _by_message(captured, "swept")
    assert len(swept) == 1
    assert swept[0]["fields"]["written"] == 1
    assert swept[0]["fields"]["failed"] == 1
    assert swept[0]["level"] == "ERROR", "a partly-failed sweep must be reachable by level"


def test_a_clean_sweep_reports_its_outcome_at_info(wired, captured):
    wired([[_message(_event(), "a")]])

    log_sweep.handler({}, None)

    swept = _by_message(captured, "swept")
    assert swept and swept[0]["level"] == "INFO"
    assert swept[0]["fields"]["failed"] == 0


def test_missing_configuration_warns_before_returning(wired, captured, monkeypatch):
    """Configuration missing on the function that collects everyone's logs is the failure most
    likely to be discovered late — nothing else reports it.
    """
    monkeypatch.setattr(log_sweep, "ADMIN_BUCKET", "")
    wired([[_message(_event(), "a")]])

    assert log_sweep.handler({}, None) == {"swept": 0, "written": 0}

    misconfigured = _by_message(captured, "not configured")
    assert misconfigured and misconfigured[0]["level"] == "WARNING"
    assert misconfigured[0]["fields"]["has_bucket"] is False


def test_the_handler_is_total_when_every_emit_raises(wired, _quiet_sink):
    """No emitter and no step may introduce a path on which the sweep raises — a throw means
    the messages redeliver, and a sweep that always throws poison-loops the queue it exists to
    drain.
    """
    sqs, _s3 = wired([[_message(_event(), "a"), _message('{"bad": true}', "b")]])
    _install_sink(RaisingSink())

    result = log_sweep.handler({}, None)

    assert result == {"swept": 2, "written": 2, "groups": 2}
    assert sorted(sqs.deleted) == ["a", "b"]


# -- FR-005: one sweep's events are O(1) in the messages it consumes --------------------


def _sweep_event_count(wired_factory, message_count, captured):
    receipts = [
        _message(_event(service="data-quality" if n % 2 else "observability"), f"r{n}")
        for n in range(message_count)
    ]
    wired_factory([receipts[i : i + 10] for i in range(0, len(receipts), 10)])
    captured.events.clear()
    log_sweep.handler({}, None)
    return len(captured.events)


def test_the_event_count_depends_on_day_groups_not_on_messages(wired, captured):
    """The guard, not the comment. The sweep emits into the queue it drains, so one event per
    message consumed would mean draining M messages produced ~M more — a floor the queue could
    never get below, permanently busy carrying its own telemetry.

    Two sweeps over the SAME two day-groups, one with ten times the messages. Any per-message
    emitter added later makes these two numbers differ.
    """
    small = _sweep_event_count(wired, 20, captured)
    large = _sweep_event_count(wired, 200, captured)

    assert small == large, (
        f"{small} events for 20 messages but {large} for 200 — an emitter is per-message"
    )


def test_the_event_count_grows_with_day_groups(wired, captured):
    """The other half of the bound: it must be O(G), which also proves the test above is not
    green merely because the count is constant in everything.
    """
    two_groups = _sweep_event_count(wired, 20, captured)

    receipts = [_message(_event(service=f"svc-{n}"), f"r{n}") for n in range(5)]
    wired([receipts])
    captured.events.clear()
    log_sweep.handler({}, None)

    assert len(captured.events) > two_groups


# -- FR-006: CloudWatch keeps everything it has ----------------------------------------


def test_every_existing_cloudwatch_message_is_still_in_the_source():
    """The sink is SQS-only, so a sweep that cannot write to S3 cannot report through the
    structured store that it could not write to S3 — the mechanism that would carry the report
    is the thing that failed. Its CloudWatch line is the only account that exists.

    Matched on the message literals rather than on formatted call sites, so reformatting the
    file cannot fail this while deleting a call still does.
    """
    source = Path(log_sweep.__file__).read_text(encoding="utf-8")
    for message in (
        "log-sweep: LOGS_QUEUE_URL or ADMIN_BUCKET unset",
        "log-sweep: no existing object at %s",
        "log-sweep: %s is %.1f MB",
        "log-sweep: %s changed under us",
        "log-sweep: failed to write %s",
        "log-sweep: gave up on %s",
        "log-sweep: failed to delete %d messages",
        "log-sweep: hit the %d-message cap",
        "log-sweep: %d event(s) had no usable timestamp",
        "log-sweep %s: %d message(s)",
    ):
        assert message in source, f"a CloudWatch account was removed: {message!r}"
    assert source.count("logger.") >= 11, "a logger call was removed without its message"


def test_a_failure_is_written_to_BOTH_accounts(wired, captured, caplog):
    """Presence in the source is not reachability. This drives the write-failure path and
    asserts the CloudWatch line and the structured event both land — which is the deliberate
    duplication FR-006 requires, and the thing a future "de-duplicate the logging" cleanup
    would break.
    """
    wired([[_message(_event(), "a")]], s3_fails=True)

    with caplog.at_level("ERROR"):
        log_sweep.handler({}, None)

    assert any("failed to write" in r.message for r in caplog.records), "no CloudWatch account"
    assert _by_message(captured, "append failed"), "no structured account"


def test_the_console_echo_is_not_used_here():
    assert ("echo" + "=True") not in Path(log_sweep.__file__).read_text(encoding="utf-8")


# -- FR-007: sweep_id joins the two accounts -------------------------------------------


def test_sweep_id_is_on_every_structured_event_including_the_boundaries(wired, captured):
    wired([[_message(_event(), "a")]])

    log_sweep.handler({}, None)

    assert captured.events, "no events emitted"
    ids = {e["fields"].get("sweep_id") for e in captured.events}
    assert len(ids) == 1 and None not in ids, (
        "sweep_id must ride as baggage, so it reaches the boundary spans too"
    )


def test_sweep_id_is_on_every_cloudwatch_line(wired, caplog):
    """A join key present on one side of the join is not a join key."""
    wired([[_message(_event(), "a")]])

    with caplog.at_level("INFO"):
        log_sweep.handler({}, None)

    assert caplog.records, "the sweep logged nothing at all"
    assert all(r.message.startswith("[sweep ") for r in caplog.records), [
        r.message for r in caplog.records
    ]


def test_two_successive_sweeps_carry_different_sweep_ids(wired, captured):
    """A warm container reuses the contextvar; a leaked sweep_id would merge two sweeps."""
    sqs, _ = wired([[_message(_event(), "a")]])

    log_sweep.handler({}, None)
    first = {e["fields"]["sweep_id"] for e in captured.events}

    captured.events.clear()
    sqs.rounds = [[_message(_event(), "b")]]
    log_sweep.handler({}, None)
    second = {e["fields"]["sweep_id"] for e in captured.events}

    assert len(first) == len(second) == 1
    assert first != second


# -- FR-005: routing, and the key-injection surface -------------------------------------


def test_well_formed_event_lands_under_its_service_and_the_events_own_hour(wired):
    _sqs, s3 = wired([[_message(_event())]])

    log_sweep.handler({}, None)

    assert len(s3.puts) == 1
    assert s3.puts[0]["Key"] == "logs/service=data-quality/year=2026/month=07/day=22/data.jsonl"
    assert s3.puts[0]["Key"].endswith("/data.jsonl")


def test_partition_comes_from_the_event_not_the_sweep_clock(wired):
    """A replayed event stamped with sweep time is invisible in the window it belongs to."""
    _sqs, s3 = wired([[_message(_event(ts="2026-07-01T03:00:00.000Z"))]])

    log_sweep.handler({}, None)

    assert "year=2026/month=07/day=01/" in s3.puts[0]["Key"]


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


def test_unrouted_body_is_preserved_verbatim(wired):
    _sqs, s3 = wired([[_message("this is not json")]])

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
    _sqs, s3 = wired(
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
    sqs, _s3 = wired([[_message(_event(), "a")], [_message(_event(), "b")]])

    result = log_sweep.handler({}, None)

    assert result["swept"] == 2
    assert sorted(sqs.deleted) == ["a", "b"]


def test_empty_queue_completes_without_writing(wired):
    _sqs, s3 = wired([])

    assert log_sweep.handler({}, None) == {"swept": 0, "written": 0}
    assert s3.puts == []


def test_round_cap_truncates_and_says_so(wired, monkeypatch, caplog):
    """A silent cap reads as 'swept everything' when it didn't."""
    monkeypatch.setattr(log_sweep, "MAX_MESSAGES", 20)
    rounds = [[_message(_event(), f"r{i}-{n}") for n in range(10)] for i in range(5)]
    _sqs, _s3 = wired(rounds)

    with caplog.at_level("WARNING"):
        result = log_sweep.handler({}, None)

    assert result["swept"] == 20
    assert any("cap" in r.message for r in caplog.records)


# -- FR-005: the handler is total -------------------------------------------------------


def test_a_completely_malformed_message_does_not_raise(wired):
    """The sweep must return normally — a throw means redelivery forever."""
    _sqs, _s3 = wired([[{"NoBodyKey": True}, _message(_event(), "ok")]])

    result = log_sweep.handler({}, None)

    assert result["swept"] == 2


def test_unparseable_timestamp_falls_back_and_is_counted(wired, caplog):
    _sqs, s3 = wired([[_message(_event(ts="not-a-timestamp"))]])

    with caplog.at_level("WARNING"):
        log_sweep.handler({}, None)

    assert s3.puts[0]["Key"].startswith("logs/service=data-quality/year=")
    assert any("timestamp" in r.message for r in caplog.records)
