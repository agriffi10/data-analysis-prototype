"""SPEC-127 FR-004/FR-005 — the scheduled log sweep.

The weight here is on the two properties that make the sweep safe to leave running unattended:
every message is routable (so nothing poison-loops on the queue), and `service` is untrusted
input on an S3 key path (so nothing escapes the logs/ prefix).
"""

import ast
import importlib.util
import inspect
import json
import os
import sys
import textwrap
import types
from collections import Counter

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


def _message(body, receipt="r1", sent=None):
    message = {"Body": body if isinstance(body, str) else json.dumps(body), "ReceiptHandle": receipt}
    if sent is not None:
        message["Attributes"] = {"SentTimestamp": str(sent)}
    return message


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

    A message's ``Attributes`` come back only when the receive asks for ``SentTimestamp``, as on
    the real queue, so a sweep that stopped asking would find every message undated. ``arrive``
    models an active session: it is called with the clock's time on every delete, the write half
    of a wave, and each message it returns queues in a group of its own, as producers send them.
    """

    def __init__(self, per_group, reject_deletes=False, arrive=None, clock=None):
        self.pending = {g: list(ms) for g, ms in per_group.items()}
        self.inflight = {}
        self.deleted = []
        self.receives = 0
        self.reject_deletes = reject_deletes
        self.arrive = arrive
        self.clock = clock

    def receive_message(self, **kwargs):
        assert kwargs["WaitTimeSeconds"] == 0, (
            "the sweep must SHORT poll, never long poll"
        )
        self.receives += 1
        limit = kwargs["MaxNumberOfMessages"]
        dated = bool({"SentTimestamp", "All"} & set(kwargs.get("MessageSystemAttributeNames", ())))
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
        if not dated:
            taken = [{k: v for k, v in m.items() if k != "Attributes"} for m in taken]
        return {"Messages": taken} if taken else {}

    def delete_message_batch(self, QueueUrl, Entries):
        if self.arrive:
            self.clock.ms += 1000
            for message in self.arrive(self.clock.ms):
                self.pending[message["ReceiptHandle"]] = [message]
        if self.reject_deletes:
            # SQS reports a rejected delete as HTTP 200 with a Failed array, and the message
            # stays in flight — so the group it belongs to keeps yielding nothing.
            return {"Failed": [{"Id": entry["Id"]} for entry in Entries]}
        for entry in Entries:
            handle = entry["ReceiptHandle"]
            self.inflight.pop(handle, None)
            self.deleted.append(handle)
        return {}


START_MS = 1_800_000_000_000
BACKLOG_SENT_MS = START_MS - 3_600_000


class Clock:
    """The sweep's wall clock, moved by the fake queue rather than by time passing.

    A real clock cannot tell "sent since the sweep started" from "sent since this wave started":
    the fake sweep runs inside a millisecond, so every stamp lands on the start and both readings
    agree. A second per delete call is what separates them.
    """

    def __init__(self, ms):
        self.ms = ms

    def time_ns(self):
        return self.ms * 1_000_000

    def monotonic(self):
        return self.ms / 1000


@pytest.fixture
def fifo(monkeypatch):
    """Wire a FIFO queue, S3 and a stopped clock into the sweep, and hand the queue back."""

    def _wire(per_group, **kwargs):
        clock = Clock(START_MS)
        sqs, s3 = FifoSQS(per_group, clock=clock, **kwargs), FakeS3()
        monkeypatch.setattr(log_sweep, "time", clock)
        monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
        monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)
        return sqs

    return _wire


def _arrival(now):
    """One message a session sends while a wave is being written, stamped when it arrived."""
    return [_message(_event(service="api"), f"new-{now}", sent=now)]


def _per_event_backlog(count):
    return {
        f"old-{n}": [_message(_event(), f"old-{n}", sent=BACKLOG_SENT_MS)] for n in range(count)
    }


def _per_service_backlog(count):
    return {
        service: [
            _message(_event(service=service), f"{service}-{n}", sent=BACKLOG_SENT_MS)
            for n in range(count)
        ]
        for service in ("data-quality", "table-share", "archive")
    }


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


@pytest.mark.parametrize(
    ("backlog", "message_cap", "reject_deletes"),
    [
        ({"data-quality": [_message(_event(), f"m-{n}") for n in range(50)]}, None, False),
        (_per_event_backlog(30), 10, True),
    ],
    ids=["deleted", "delete-rejected"],
)
def test_the_wave_cap_bounds_a_sweep_and_says_so(
    fifo, captured, monkeypatch, backlog, message_cap, reject_deletes
):
    """A backlog deeper than the cap is left for the next tick rather than taken in one
    invocation, and it is reported — a bounded sweep that read as a drained queue is the exact
    shape of the defect this replaced.

    The cap also outranks a blocked group. The rejected-delete row leaves its first wave in
    flight, and the reason must still be the cap that stopped the sweep.
    """
    monkeypatch.setattr(log_sweep, "MAX_WAVES", 2)
    if message_cap:
        monkeypatch.setattr(log_sweep, "MAX_MESSAGES", message_cap)
    fifo(backlog, reject_deletes=reject_deletes)

    result = log_sweep.handler({}, None)

    assert result["swept"] == 20
    assert result["waves"] == 2
    stopped = _by_message(captured, "stopped with the queue possibly still yielding")
    assert stopped and stopped[0]["level"] == "WARNING"
    assert stopped[0]["fields"]["limit"] == 2
    assert stopped[0]["fields"]["reason"] == log_sweep.STOP_WAVE_CAP




def test_a_backlog_across_groups_drains_in_one_sweep(monkeypatch, captured):
    """A backlog spread over several message groups leaves in ONE invocation, not one wave.

    The shape the wave loop exists for. A wave takes at most ten messages per unblocked group
    and then holds them, so on a FIFO queue every group it touched stops yielding until the
    delete lands — three groups give a wave thirty messages and an empty round, which the
    single-wave sweep read as a drained queue.

    Twenty-five per group over three groups is deliberately not a multiple of that wave: the
    final wave is partial, so a sweep that stopped on a short wave rather than an empty queue
    is visible here too. Against the single-wave shape this takes 30 of 75.
    """
    per_group = {
        service: [_message(_event(service=service), f"{service}-{n}") for n in range(25)]
        for service in ("data-quality", "table-share", "archive")
    }
    sqs, s3 = FifoSQS(per_group), FakeS3()
    monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
    monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)

    result = log_sweep.handler({}, None)

    assert result["swept"] == 75, "the sweep left part of the backlog on the queue"
    assert result["written"] == 75 and len(sqs.deleted) == 75
    assert result["waves"] == 3, "thirty messages a wave, so 75 needs three of them"
    assert not any(queued for queued in sqs.pending.values()) and not sqs.inflight
    assert not _by_message(captured, "stopped with the queue possibly still yielding")


@pytest.mark.parametrize(
    ("backlog", "message_cap", "waves"),
    [
        (_per_event_backlog(30), None, 2),
        (_per_service_backlog(25), None, 4),
        (_per_event_backlog(30), 10, 4),
    ],
    ids=["grouped-per-event", "grouped-per-service", "after-full-waves"],
)
def test_a_caught_up_sweep_finishes_on_a_wave_of_arrivals_alone(
    fifo, captured, monkeypatch, backlog, message_cap, waves
):
    """A session's arrivals end the sweep once the backlog is gone, not the wave cap.

    Every delete lets a message arrive, so each wave finds what arrived during the one before,
    and a sweep that waited for an empty receive ran to ``MAX_WAVES`` on every tick. It must take
    the backlog, then one wave holding only arrivals, and finish as a normal sweep. The
    per-service row is a legacy backlog: its waves still hold ten old messages per group, so it
    drains in full before the stop can fire. The last row's backlog fills its first waves, and a
    wave that filled the cap earlier must not keep a later wave of arrivals from finishing it.

    The wave cap is set to the wave the sweep should finish on, so a finish that let the cap
    speak first would report ``wave-cap`` over a drained queue.
    """
    monkeypatch.setattr(log_sweep, "MAX_WAVES", waves)
    if message_cap:
        monkeypatch.setattr(log_sweep, "MAX_MESSAGES", message_cap)
    sqs = fifo(backlog, arrive=_arrival)

    result = log_sweep.handler({}, None)

    assert result["waves"] == waves
    backlog_receipts = {m["ReceiptHandle"] for queued in backlog.values() for m in queued}
    assert backlog_receipts <= set(sqs.deleted), "the stop cut the backlog short"
    assert not sqs.inflight, "the last wave must be written and deleted before the sweep ends"
    assert not _by_message(captured, "stopped with the queue possibly still yielding")
    assert _by_message(captured, "swept")[0]["level"] == "INFO"


@pytest.mark.parametrize(
    ("arrive", "message_cap"),
    [
        (lambda now: [_message(_event(service="api"), f"new-{now}")], None),
        (lambda now: [_message(_event(service="api"), f"new-{now}", sent="soon")], None),
        (
            lambda now: [
                _message(_event(service="api"), f"new-{now}-{n}", sent=now) for n in range(10)
            ],
            5,
        ),
    ],
    ids=["undated", "unparseable", "a-full-wave-of-arrivals"],
)
def test_a_wave_the_sweep_cannot_vouch_for_keeps_it_going(
    fifo, captured, monkeypatch, arrive, message_cap
):
    """Stopping early is the costly direction, so every doubt reads as more backlog.

    A message the sweep cannot date might be old. A wave that filled the message cap might have
    older messages behind it, because SQS does not order messages across groups. Either way the
    sweep runs on — here to a wave cap of four — rather than finishing on the arrivals.
    """
    monkeypatch.setattr(log_sweep, "MAX_WAVES", 4)
    if message_cap:
        monkeypatch.setattr(log_sweep, "MAX_MESSAGES", message_cap)
    fifo(_per_event_backlog(3), arrive=arrive)

    result = log_sweep.handler({}, None)

    assert result["waves"] == 4
    stopped = _by_message(captured, "stopped with the queue possibly still yielding")
    assert stopped and stopped[0]["fields"]["reason"] == log_sweep.STOP_WAVE_CAP


@pytest.mark.parametrize(
    ("backlog", "arrive", "swept", "waves"),
    [
        ({"data-quality": [_message(_event(), f"m-{n}") for n in range(30)]}, None, 10, 1),
        (_per_event_backlog(30), _arrival, 33, 2),
    ],
    ids=["finished-on-an-empty-receive", "finished-on-a-wave-of-arrivals"],
)
def test_a_rejected_delete_stops_the_sweep_on_its_own_reason(
    fifo, captured, backlog, arrive, swept, waves
):
    """``group-blocked`` is reported, and it is not the wave cap or the time reserve.

    A rejected delete leaves the message in flight, so its group keeps yielding nothing and the
    very next receive comes back empty with the queue nowhere near drained. That empty round is
    indistinguishable from a drained queue at the receive, which is why the sweep has to reach
    for what it knows about its own deletes to name it. A wave of arrivals alone is the same
    inference by another route, and a blocked group can hide older messages from it too.

    The reason is asserted rather than the warning alone: all three stop reasons travel on the
    same event, and the operator response to each is a different one.
    """
    fifo(backlog, reject_deletes=True, arrive=arrive)

    result = log_sweep.handler({}, None)

    assert result["swept"] == swept and result["waves"] == waves
    stopped = _by_message(captured, "stopped with the queue possibly still yielding")
    assert stopped and stopped[0]["fields"]["reason"] == log_sweep.STOP_GROUP_BLOCKED


@pytest.mark.parametrize("reject_deletes", [False, True], ids=["deleted", "delete-rejected"])
def test_a_sweep_running_out_of_time_stops_on_the_reserve(fifo, captured, reject_deletes):
    """The reserve is checked BETWEEN waves and never before the first one.

    A wave's cost tracks the day object, which grows all day, so the wave cap bounds the count
    and not the duration. Forcing the reserve to bite after one wave separates the two: the
    sweep must still take that wave, then stop and say the reserve is why — a sweep that
    reported the wave cap here would send an operator to raise a limit that was not reached.
    The clock also outranks a blocked group, which is why the rejected-delete row still reads
    ``time-reserve``: the reserve is the harder constraint, and it is the one that stopped it.
    """
    fifo(
        {"data-quality": [_message(_event(), f"m-{n}") for n in range(30)]},
        reject_deletes=reject_deletes,
    )

    class _Context:
        def get_remaining_time_in_millis(self):
            return log_sweep.SWEEP_RESERVE_MS - 1

    result = log_sweep.handler({}, _Context())

    assert result["swept"] == 10 and result["waves"] == 1, "the first wave runs unconditionally"
    stopped = _by_message(captured, "stopped with the queue possibly still yielding")
    assert stopped and stopped[0]["fields"]["reason"] == log_sweep.STOP_TIME_RESERVE


# -- The sweep's own volume: set by destinations, never by waves -------------------------

DAY = "year=2026/month=07/day=22/data.jsonl"


class DegradedS3(FakeS3):
    """An S3 whose day objects each go wrong in their own way, chosen by service.

    ``contended`` loses the first race of every append, and ``twice`` loses the first two on
    its first append, as a concurrent writer commits between the read and the write.
    ``exhausted`` loses every race and ``broken`` faults on every write. Every other service
    gets the plain conditional fake.
    """

    def __init__(self, contended, twice, exhausted, broken):
        super().__init__()
        self.contended, self.twice = contended, twice
        self.exhausted, self.broken = exhausted, broken
        self.landed, self.retried = set(), set()

    def _loses(self, service, key, if_match):
        if service in self.exhausted:
            return True
        if service not in self.contended:
            return False
        if not str(if_match).startswith('"race-'):
            return True
        if service in self.twice and key not in self.landed and key not in self.retried:
            self.retried.add(key)
            return True
        return False

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        service = Key.split("/")[1].removeprefix("service=")
        if service in self.broken:
            raise RuntimeError("s3 is down for this key")
        if self._loses(service, Key, IfMatch):
            if Key in self.objects:
                self._n += 1
                self.objects[Key] = (self.objects[Key][0], f'"race-{self._n}"')
            raise _ClientError("PreconditionFailed")
        self.landed.add(Key)
        return super().put_object(Bucket, Key, Body, ContentType, IfMatch, IfNoneMatch)


class PickySQS(FifoSQS):
    """Rejects the deletes of some services' messages and raises on others', by receipt, and
    records at every receive how many events had reached the sink and how many emitter calls
    the sweep had made."""

    def __init__(self, per_group, rejected, raising, delivered, emitted):
        super().__init__(per_group)
        self.rejected, self.raising = rejected, raising
        self.delivered, self.emitted = delivered, emitted
        self.seen, self.calls = [], []

    def receive_message(self, **kwargs):
        self.seen.append(len(self.delivered))
        self.calls.append(len(self.emitted))
        return super().receive_message(**kwargs)

    def delete_message_batch(self, QueueUrl, Entries):
        owner = Entries[0]["ReceiptHandle"].rsplit("-", 1)[0]
        if owner in self.raising:
            raise _ClientError("InternalError")
        if owner in self.rejected:
            return {"Failed": [{"Id": entry["Id"]} for entry in Entries]}
        return super().delete_message_batch(QueueUrl, Entries)


def _continues(node):
    """Reports whether a statement can continue the loop it sits in.

    A ``continue`` inside an inner loop's body binds that loop and does not count; one in an
    inner loop's ``else`` binds the enclosing loop and does.

    Args:
      node: The statement.

    Returns:
      True when a ``continue`` in it would restart the enclosing loop.
    """
    if isinstance(node, ast.Continue):
        return True
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
        return False
    if isinstance(node, ast.For | ast.AsyncFor | ast.While):
        return any(_continues(child) for child in node.orelse)
    return any(_continues(child) for child in ast.iter_child_nodes(node))


def _undriven(module, drive):
    """Runs ``drive`` and returns the source of every line of the module's code it missed.

    Every function the module's source defines counts — nested ones, methods, properties and
    classmethods included, because the code is read from the compiled source rather than from
    whatever the module exposes — so a branch added anywhere in it has to be reached by
    ``drive`` or it is reported, whatever the branch does and however it is spelled.

    Exempt: each code object's first line, which the interpreter does not report as run on
    every version, so a lambda or generator expression that is never called is silent — and
    harmless, since it never runs. And a block in ``handler``'s own scope that ends in a
    ``return``, or in a ``break`` out of its outermost loop, and never continues that loop: such
    a block runs at most once per sweep. A ``break`` out of an inner loop, a block that
    continues the loop, and a ``return`` in a function nested in the handler all run per wave,
    and are held like any other line. A function that runs only at import time is reported,
    since no drive can reach it.

    Args:
      module: The imported module whose code is held to it.
      drive: Runs the module's code.

    Returns:
      ``(line number, source)`` for each line never reached, in line order.
    """
    path = module.__file__
    with open(path, encoding="utf-8") as f:
        source = f.read()

    expected = set()

    def collect(code):
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                if const.co_flags & inspect.CO_OPTIMIZED:
                    expected.update(
                        line
                        for _, _, line in const.co_lines()
                        if line is not None and line != const.co_firstlineno
                    )
                collect(const)

    collect(compile(source, path, "exec"))

    once = set()

    class _OncePerSweep(ast.NodeVisitor):
        """Marks the handler's blocks that end its outermost loop or the sweep itself."""

        depth = 0

        def visit_FunctionDef(self, node):
            pass

        visit_AsyncFunctionDef = visit_ClassDef = visit_Lambda = visit_FunctionDef

        def visit_While(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_For = visit_AsyncFor = visit_While

        def visit_If(self, node):
            last = node.body[-1]
            ends = isinstance(last, ast.Return) or (isinstance(last, ast.Break) and self.depth == 1)
            if ends and not any(_continues(statement) for statement in node.body):
                once.update(range(node.body[0].lineno, last.end_lineno + 1))
            self.generic_visit(node)

    for node in ast.parse(source).body:
        if getattr(node, "name", "") == "handler":
            for statement in node.body:
                _OncePerSweep().visit(statement)

    ran = set()
    monitoring = sys.monitoring
    tool = next(i for i in (3, 4) if monitoring.get_tool(i) is None)
    monitoring.use_tool_id(tool, "log-sweep-guard")
    try:
        monitoring.register_callback(
            tool,
            monitoring.events.LINE,
            lambda code, line: ran.add(line) if code.co_filename == path else None,
        )
        monitoring.set_events(tool, monitoring.events.LINE)
        drive()
    finally:
        monitoring.set_events(tool, 0)
        monitoring.register_callback(tool, monitoring.events.LINE, None)
        monitoring.free_tool_id(tool)

    lines = source.splitlines()
    return [(line, lines[line - 1].strip()) for line in sorted(expected - ran - once)]


class _Plenty:
    """A Lambda context with all the time in the world, so the reserve check runs and passes."""

    def get_remaining_time_in_millis(self):
        return 10**9


def test_a_sweep_emits_the_same_events_however_many_waves_it_takes(monkeypatch, captured):
    """The guard on the sweep's own volume, which it emits into the queue it drains.

    An emitter that fires per wave or per message puts work back in proportion to the work the
    sweep takes, so a busy queue keeps it busy with its own telemetry. So no emitter may be
    called between the sweep's first receive and its last, however rarely it would fire; two
    waves and six over the same destinations must emit the same events, message for message,
    which also holds the child spans a call count cannot see; and nothing may reach the sink
    before the sweep returns, or a later wave could receive it.

    Those hold only on the paths the sweeps drive, so they drive all of them, and the test
    proves it: every line of the sweep must run, bar the handler's blocks that end the loop or
    the sweep without continuing it. Each sweep's waves take a clean append and delete, a lost
    race (two on one destination's first append), an exhausted one, a write fault, large
    objects, rejected and raising deletes, and bodies that are not JSON, not an object, badly
    named or undated; every sweep ends on a wave that its receive finished on an empty round,
    holding a message stamped after the sweep began and one it cannot date; and each pair is
    run with the receive stopping on its message cap and on its round cap. A branch added to
    the sweep fails here until it is driven too. Only compared pairs may be driven: a sweep run
    just to reach a line would satisfy the completeness check while nothing held that line. One
    group per event, as the producers send them.
    """
    monkeypatch.setattr(log_sweep, "LARGE_OBJECT_WARN_BYTES", 32 * 1024)
    emitted = []

    def counting(real):
        def emit(*args, **kwargs):
            emitted.append(args[0] if args else "")
            return real(*args, **kwargs)

        return emit

    for level in ("info", "warning", "error"):
        monkeypatch.setattr(lf, level, counting(getattr(lf, level)))

    kinds = {
        "data-quality": lambda: _event(service="data-quality"),
        "archive": lambda: _event(service="archive"),
        "file-ops": lambda: _event(service="file-ops"),
        "table-share": lambda: _event(service="table-share"),
        "file-send": lambda: _event(service="file-send"),
        "shared-space": lambda: _event(service="shared-space"),
        "unrouted": lambda: "this is not json",
        "listbody": lambda: "[1, 2, 3]",
        "badservice": lambda: _event(service="Data-Quality"),
        "undated": lambda: _event(service="table-builder", ts="not a timestamp"),
    }
    dated = {"data-quality": 10**13}
    caps = {"message cap": (110, 100), "round cap": (1000, 11)}

    def sweep(per_kind):
        captured.events.clear()
        per_group = {
            f"{kind}-{n}": [_message(body(), f"{kind}-{n}", sent=dated.get(kind))]
            for n in range(per_kind)
            for kind, body in kinds.items()
        }
        sqs = PickySQS(
            per_group,
            rejected={"data-quality", "archive"},
            raising={"file-send"},
            delivered=captured.events,
            emitted=emitted,
        )
        s3 = DegradedS3(
            contended={"data-quality", "archive"},
            twice={"data-quality"},
            exhausted={"table-share"},
            broken={"file-ops"},
        )
        s3.objects[f"logs/service=data-quality/{DAY}"] = (b"x" * 64 * 1024 + b"\n", '"seed"')
        s3.objects[f"logs/service=archive/{DAY}"] = (b"x" * 64 * 1024, '"seed"')
        monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
        monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)
        result = log_sweep.handler({}, _Plenty())
        return result, list(captured.events), sqs.seen, sqs.calls, len(emitted)

    runs = {}

    def drive():
        for cap, (messages, rounds) in caps.items():
            monkeypatch.setattr(log_sweep, "MAX_MESSAGES", messages)
            monkeypatch.setattr(log_sweep, "MAX_ROUNDS", rounds)
            runs[cap] = (sweep(15), sweep(59))

    undriven = _undriven(log_sweep, drive)

    project = {
        "appended": lambda f: (f["events"], f["writes"]),
        "append failed": lambda f: (f["events"], f["reason"]),
        "day object changed under us": lambda f: (f["conflicts"], f["worst_attempt"]),
        "day object is large": lambda f: f["bytes"] > log_sweep.LARGE_OBJECT_WARN_BYTES,
    }
    for cap, (two, six) in runs.items():
        (two_result, two_events, two_seen, two_calls, two_after) = two
        (six_result, six_events, six_seen, six_calls, six_after) = six
        assert (two_result["waves"], six_result["waves"]) == (2, 6), f"{cap}: the waves differ"
        for calls, after in ((two_calls, two_after), (six_calls, six_after)):
            assert len(set(calls)) == 1 and after > calls[0], f"{cap}: an emitter ran in the loop"
        assert len(six_seen) > 6 and set(two_seen + six_seen) == {0}, f"{cap}: an event left mid-sweep"
        assert Counter(e["message"] for e in two_events) == Counter(
            e["message"] for e in six_events
        ), cap
        accounts = sorted(
            (
                e["message"],
                e["fields"]["key"].split("/")[1].removeprefix("service="),
                project[e["message"]](e["fields"]),
            )
            for e in six_events
            if e["message"] in project
        )
        assert accounts == [
            ("append failed", "file-ops", (59, "write-failed")),
            ("append failed", "table-share", (59, "precondition-exhausted")),
            ("appended", "_unrouted", (177, 6)),
            ("appended", "archive", (59, 6)),
            ("appended", "data-quality", (59, 6)),
            ("appended", "file-send", (59, 6)),
            ("appended", "shared-space", (59, 6)),
            ("appended", "table-builder", (59, 6)),
            ("day object changed under us", "archive", (6, 1)),
            ("day object changed under us", "data-quality", (7, 2)),
            ("day object changed under us", "table-share", (36, 6)),
            ("day object is large", "archive", True),
            ("day object is large", "data-quality", True),
        ], cap
        undeleted = [
            e["fields"]["events"]
            for e in six_events
            if e["message"] == "delete failed; events will be appended again next sweep"
        ]
        assert undeleted == [177], cap
    assert undriven == [], "the sweeps never reached these lines, so they hold nothing there"


def test_a_destination_that_failed_on_some_waves_and_landed_on_another_reports_both(
    monkeypatch, captured
):
    """A destination's account keeps both outcomes, however the waves split them.

    Two waves fail and the third lands, so a rollup that kept only the last outcome, or one
    failure event per wave, would each read differently from the one success and one failure
    carrying the events left queued.
    """
    monkeypatch.setattr(log_sweep, "MAX_MESSAGES", 10)
    per_group = {f"m-{n}": [_message(_event(), f"m-{n}")] for n in range(30)}
    sqs, s3 = FifoSQS(per_group), FakeS3()
    real_put, puts = s3.put_object, {"n": 0}

    def flaky_put(**kwargs):
        puts["n"] += 1
        if puts["n"] <= 2:
            raise RuntimeError("s3 is down")
        return real_put(**kwargs)

    monkeypatch.setattr(s3, "put_object", flaky_put)
    monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
    monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)

    result = log_sweep.handler({}, None)

    key = f"logs/service=data-quality/{DAY}"
    assert result["waves"] == 3
    assert [
        (e["fields"]["key"], e["fields"]["events"], e["fields"]["writes"])
        for e in _by_message(captured, "appended")
    ] == [(key, 10, 1)]
    assert [
        (e["fields"]["key"], e["fields"]["events"], e["fields"]["reason"])
        for e in _by_message(captured, "append failed")
    ] == [(key, 20, "write-failed")]
    swept = _by_message(captured, "swept")
    assert swept[0]["level"] == "ERROR" and swept[0]["fields"]["failed"] == 20


def test_a_receive_fault_after_a_wave_still_reports_what_that_wave_wrote(monkeypatch, captured):
    """The accounts are emitted on the way out of a fault, not only at a clean finish.

    A receive fault raises out of the sweep. The first wave's writes are already durable by
    then, so an account emitted only after the loop would leave them in S3 with no structured
    record that this sweep put them there — and its rejected deletes, which will duplicate them
    next sweep, with no record either.
    """

    class _FaultingSQS(FifoSQS):
        attempted = False

        def delete_message_batch(self, QueueUrl, Entries):
            self.attempted = True
            return super().delete_message_batch(QueueUrl, Entries)

        def receive_message(self, **kwargs):
            if self.attempted:
                raise _ClientError("InternalError")
            return super().receive_message(**kwargs)

    per_group = {
        service: [_message(_event(service=service), f"{service}-{n}") for n in range(5)]
        for service in ("data-quality", "archive")
    }
    sqs, s3 = _FaultingSQS(per_group, reject_deletes=True), FakeS3()
    monkeypatch.setattr(log_sweep.clients, "sqs", lambda: sqs)
    monkeypatch.setattr(log_sweep.clients, "s3", lambda: s3)

    with pytest.raises(_ClientError):
        log_sweep.handler({}, None)

    assert sorted(
        (e["fields"]["key"], e["fields"]["events"]) for e in _by_message(captured, "appended")
    ) == [(f"logs/service=archive/{DAY}", 5), (f"logs/service=data-quality/{DAY}", 5)]
    undeleted = _by_message(captured, "delete failed; events will be appended again next sweep")
    assert [e["fields"]["events"] for e in undeleted] == [10]



def _run_elsewhere(beside, source):
    """Runs source as a module in a file beside another, so the lines it runs are another file's.

    Args:
      beside: A path in the directory to write the module to.
      source: The module's source.

    Returns:
      None.

    Raises:
      None.
    """
    path = os.path.join(os.path.dirname(beside), "elsewhere.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location("elsewhere", path)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


_CORPUS = {
    "a helper's untaken branch is reported": (
        """
        def helper(flag):
            if flag:
                return "taken"
            return "not taken"
        """,
        lambda m: m.helper(False),
        ['return "taken"'],
    ),
    "a helper whose every branch runs is silent, and another file's code is not counted": (
        """
        from textwrap import dedent
        def helper(flag):
            if flag:
                return dedent("taken")
            return "not taken"
        """,
        lambda m: (m.helper(True), m.helper(False)),
        [],
    ),
    "a handler block that ends its loop or the sweep is exempt": (
        """
        def handler(n):
            while True:
                if n > 99:
                    n = 0
                    break
                if n < -99:
                    n = 1
                    return n
                n += 1
                if n > 3:
                    break
        """,
        lambda m: m.handler(0),
        [],
    ),
    "a handler block that continues its loop before ending it is reported": (
        """
        def handler(n):
            while n < 3:
                if n > 99:
                    if n > 999:
                        continue
                    n = 0
                    break
                n += 1
        """,
        lambda m: m.handler(0),
        ["if n > 999:", "continue", "n = 0", "break"],
    ),
    "a continue that binds an inner loop leaves the block exempt": (
        """
        def handler(n):
            while True:
                if n > 99:
                    for k in range(2):
                        if k:
                            continue
                    break
                n += 1
                if n > 3:
                    break
        """,
        lambda m: m.handler(0),
        [],
    ),
    "a continue in an inner loop's else continues the outer loop, so the block is reported": (
        """
        def handler(n):
            while n < 3:
                if n > 99:
                    for k in range(2):
                        pass
                    else:
                        continue
                    break
                n += 1
        """,
        lambda m: m.handler(0),
        ["for k in range(2):", "pass", "continue"],
    ),
    "a line run in another file does not stand in for the same line here": (
        """
        def helper(flag):
            if flag:
                return "taken"
            return "not taken"
        """,
        lambda m: (m.helper(False), _run_elsewhere(m.__file__, "a = 1\nb = 2\nc = 3\n")),
        ['return "taken"'],
    ),
    "a property never read and a classmethod never called are reported": (
        """
        class Tally:
            @property
            def degraded(self):
                return True

            @classmethod
            def fresh(cls):
                return cls()
        """,
        lambda m: m.Tally(),
        ["return True", "return cls()"],
    ),
    "a handler block that does not end its loop is reported": (
        """
        def handler(n):
            while n < 3:
                if n > 99:
                    n = 0
                n += 1
        """,
        lambda m: m.handler(0),
        ["n = 0"],
    ),
    "a helper's block that returns is not exempt, since it returns per call": (
        """
        def helper(flag):
            if flag:
                x = 1
                return x
            return 0
        """,
        lambda m: m.helper(False),
        ["x = 1", "return x"],
    ),
    "a decorated function is read through its wrapper": (
        """
        import functools
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*args):
                return fn(*args)
            return wrapper
        @deco
        def helper(flag):
            if flag:
                return "taken"
            return "not taken"
        """,
        lambda m: (m.deco(len), m.helper(False)),
        ['return "taken"'],
    ),
    "a method's untaken branch is reported": (
        """
        class Filter:
            def filter(self, flag):
                if flag:
                    return "taken"
                return "not taken"
        """,
        lambda m: m.Filter().filter(False),
        ['return "taken"'],
    ),
    "a handler block that breaks a loop inside its loop is reported, since it runs per wave": (
        """
        def handler(n):
            while n < 3:
                for item in range(2):
                    if item > 99:
                        n = 0
                        break
                n += 1
        """,
        lambda m: m.handler(0),
        ["n = 0", "break"],
    ),
    "a returning block in a function nested in the handler is reported": (
        """
        def handler(n):
            def inner(k):
                if k > 99:
                    k = 0
                    return k
                return 1
            while n < 3:
                n += inner(n)
        """,
        lambda m: m.handler(0),
        ["k = 0", "return k"],
    ),
    "a nested function never called is reported": (
        """
        def helper():
            def inner():
                return 1
            return 0
        """,
        lambda m: m.helper(),
        ["return 1"],
    ),
}


@pytest.mark.parametrize("case", sorted(_CORPUS), ids=sorted(_CORPUS))
def test_the_completeness_check_reports_exactly_the_lines_a_drive_missed(tmp_path, case):
    """The completeness check is a gate, so each thing it reports is proved, and so is its
    silence on a module whose every line was driven."""
    source, drive, missed = _CORPUS[case]
    path = tmp_path / "corpus_module.py"
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("corpus_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert [text for _, text in _undriven(module, lambda: drive(module))] == missed
