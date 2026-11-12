"""Unit tests for dqcommon.index_store — the per-space runs index (SPEC-123 FR-001).

The fake S3 below implements REAL conditional-put semantics (If-Match / If-None-Match with
a changing ETag), because the whole FR is about what happens when two writers race. A fake
that ignored the preconditions would make every CAS test pass without exercising the CAS.
"""

import json
import os
import pathlib
import re
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import budget, clients
from dqcommon import config, index_store

BUCKET = "dat-prod-user-space"
PREFIX = "alice/_data-quality-reports/r-1/"
KEY = "alice/_data-quality-reports/index.json"


class _ClientError(Exception):
    """Shaped like botocore's, which is all `cpcommon.cas.is_precondition` reads."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """An S3 that actually enforces the conditional-put contract."""

    def __init__(self, objects=None, put_error=None):
        self.objects = dict(objects or {})  # key -> (bytes, etag)
        self.puts = 0
        self.get_attempts = 0
        self.put_attempts = 0
        self.put_error = put_error
        self.version = 0
        #: Fires once before a put commits, to simulate a writer landing mid-CAS.
        self.on_put = None

    def get_object(self, Bucket, Key):
        self.get_attempts += 1
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        self.put_attempts += 1
        if self.put_error:
            raise self.put_error
        if self.on_put:
            hook, self.on_put = self.on_put, None
            hook()
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise _ClientError("ConditionalRequestConflict")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _ClientError("PreconditionFailed")
        self.version += 1
        self.objects[Key] = (Body, f'"etag-{self.version}"')
        self.puts += 1

    def entries(self, key=KEY):
        return json.loads(self.objects[key][0])["entries"]


class _Unbounded:
    """The default client, which must never be reached: it records the call and refuses it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"the runs index called {name} on the unbounded client")


def _install(objects=None, put_error=None):
    fake = _FakeS3(objects, put_error)
    clients._s3 = fake
    clients._s3_bounded = fake
    return fake


def _verb_timeout(name):
    """One data-quality verb's Lambda timeout, read from the plane's verb map rather than restated."""
    plane_tf = (pathlib.Path(__file__).resolve().parents[2] / "infra" / "plane-data-quality.tf").read_text()
    found = re.search(rf'"{name}"\s*=\s*\{{([^}}]*)\}}', plane_tf)
    assert found, f"the data-quality verb map no longer configures a {name!r} verb"
    return int(re.search(r"timeout\s*=\s*(\d+)", found.group(1)).group(1))


def _summary(request_id="r-1", **over):
    summary = {
        "requestId": request_id,
        "location": "alice/sales",
        "format": "csv",
        "verdict": "issues_found",
        "fileCount": 3,
        "hasApproximateFigures": True,
        "hasIncompleteFigures": True,
        "completedAt": "2026-07-21T14:32:11Z",
    }
    summary.update(over)
    return summary


# ── The CAS (FR-001's named tests) ───────────────────────────────────────────


def test_two_concurrent_appends_both_survive():
    """THE RACE THE CAS EXISTS FOR. Checks of different locations run in parallel, so two
    assemble-report invocations can append at once; a plain read-modify-write loses one."""
    fake = _install()

    # r-2 commits after r-1 has read, before r-1 writes — the classic interleaving.
    def interleave():
        index_store.append(BUCKET, "alice/_data-quality-reports/r-2/", _summary("r-2"))

    fake.on_put = interleave
    assert index_store.append(BUCKET, PREFIX, _summary("r-1")) is True

    ids = sorted(e["requestId"] for e in fake.entries())
    assert ids == ["r-1", "r-2"], "a concurrent append was silently lost"


def test_an_entry_carries_the_incomplete_flag_and_not_the_approximate_one():
    """The row's qualifier. The approximate flag is true on every report, so a list tag keyed to
    it sat on every row and said nothing; the incomplete flag is the one that varies."""
    fake = _install()

    index_store.append(BUCKET, PREFIX, _summary(hasIncompleteFigures=False))

    [entry] = fake.entries()
    assert entry["hasIncompleteFigures"] is False
    assert set(entry) == {
        "requestId",
        "location",
        "format",
        "verdict",
        "fileCount",
        "hasIncompleteFigures",
        "timestamp",
    }


# ── Absent / corrupt / capped ────────────────────────────────────────────────


def test_the_index_is_capped_oldest_dropped_first():
    existing = [
        {"requestId": f"old-{i}", "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
        for i in range(config.DQ_INDEX_MAX_ENTRIES)
    ]
    fake = _install({KEY: (json.dumps({"entries": existing}).encode(), '"etag-0"')})
    index_store.append(BUCKET, PREFIX, _summary("newest"))

    entries = fake.entries()
    assert len(entries) == config.DQ_INDEX_MAX_ENTRIES
    assert entries[-1]["requestId"] == "newest"
    assert "old-0" not in [e["requestId"] for e in entries], "the OLDEST must be the one dropped"


# ── SPEC-153 FR-010: CAS parity with the log-sweep twin ──────────────────────


def test_ACCEPTED_the_cap_evicts_by_position_so_a_replay_can_outlive_a_newer_run():
    """Position-based eviction, pinned as the documented choice it is.

    The cap keeps the LAST ``DQ_INDEX_MAX_ENTRIES`` rows of a list ordered by ARRIVAL, and
    the same-requestId replacement moves a replayed run to the end while keeping its
    original ``completedAt``. So once a replay has happened, position order and timestamp
    order disagree, and the next new run evicts the oldest row *by position* — here ``r-1``,
    which is NEWER in time than the replayed ``r-0`` that survives.

    ACCEPTED: ``index_store.py`` records at the cap that the dashboard sorts by timestamp
    itself and never relies on disk order, and every evicted run's report object — the
    source of truth — is untouched. A replay is also not itself an eviction: the row is
    removed before it is re-appended, so the length is unchanged.

    If this starts failing, eviction became timestamp-aware: revisit the decision, do not
    delete the test.
    """
    existing = [
        {"requestId": f"r-{i}", "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
        for i in range(config.DQ_INDEX_MAX_ENTRIES)
    ]
    fake = _install({KEY: (json.dumps({"entries": existing}).encode(), '"etag-0"')})

    index_store.append(BUCKET, PREFIX, _summary("r-0", completedAt="2026-01-01T00:00:00Z"))
    ids = [e["requestId"] for e in fake.entries()]
    assert len(ids) == config.DQ_INDEX_MAX_ENTRIES, "a replay must not evict anything"
    assert ids[-1] == "r-0" and ids[0] == "r-1"

    index_store.append(BUCKET, PREFIX, _summary("fresh", completedAt="2026-06-01T00:00:00Z"))

    ids = [e["requestId"] for e in fake.entries()]
    assert len(ids) == config.DQ_INDEX_MAX_ENTRIES
    assert "r-1" not in ids, "the oldest BY POSITION is the row dropped"
    assert "r-0" in ids, "and the replayed, older-by-timestamp row outlived it"


# ── Bounded in time ──────────────────────────────────────────────────────────


def test_every_index_call_goes_through_the_bounded_client():
    """The budget caps how long the verb waits for a call, not how long the call runs: one left on
    the default client, which waits a minute for a response and makes five attempts, would hold
    its socket and thread that long after being abandoned."""
    _install()
    unbounded = _Unbounded()
    clients._s3 = unbounded

    assert index_store.append(BUCKET, PREFIX, _summary()) is True

    assert unbounded.calls == []


@pytest.mark.parametrize(
    ("step", "gets", "puts"),
    [
        pytest.param(1, 3, 2, id="refused-before-a-write"),
        pytest.param(2, 1, 1, id="refused-before-a-read"),
    ],
)
def test_the_index_stops_starting_calls_once_its_deadline_has_passed(
    monkeypatch, caplog, step, gets, puts
):
    """A stall is not a fault, so nothing would catch it: the loop must give up on the clock.

    Every write loses its precondition, so without the deadline the loop would run all its
    attempts and end in exhaustion. The clock advances ``step`` seconds per reading, which puts
    the first call past the deadline on a write in one case and on a read in the other — the
    exact counts are what tell the two checks apart, since dropping either still ends early.
    """
    clock = iter(range(0, 1000, step))
    monkeypatch.setattr(budget.time, "monotonic", lambda: next(clock))
    fake = _install(put_error=_ClientError("PreconditionFailed"))

    assert index_store.append(BUCKET, PREFIX, _summary()) is False

    assert (fake.get_attempts, fake.put_attempts) == (gets, puts)
    assert isinstance(caplog.records[-1].exc_info[1], TimeoutError)


def test_a_read_that_never_answers_costs_the_row_and_not_the_verb(monkeypatch, caplog):
    """The stall the budget exists for, end to end: nothing raises, so only the cap ends it."""
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    fake = _install()
    released = threading.Event()
    fake.get_object = lambda **_: released.wait(2)
    started = time.monotonic()

    try:
        recorded = index_store.append(BUCKET, PREFIX, _summary())
        held = time.monotonic() - started
        reason = caplog.records[-1].exc_info[1]
    finally:
        released.set()

    assert recorded is False
    assert held < 1
    assert isinstance(reason, TimeoutError) and "ran past" in str(reason)
    assert fake.put_attempts == 0


def test_the_notice_and_the_index_cannot_outlast_assemble_report():
    """A stall after the report is written is swallowed only if it ends before the verb's timeout.

    The completion notice goes first, on a budget of its own, so it holds the verb for one cap; a
    send that delivered and lost its reply would otherwise have held it to the timeout after the
    user was told. The index follows, for its deadline plus one capped call started just before
    it. Together they must leave at least half of the verb's timeout to the work the verb exists
    for — reading the query results and writing the report — which runs on the unbounded default
    client before either.
    """
    worst = budget.CALL_CAP_SECONDS + index_store.INDEX_DEADLINE_SECONDS + budget.CALL_CAP_SECONDS
    timeout = _verb_timeout("assemble-report")

    assert worst <= timeout / 2, (
        f"the notice and the index can take {worst}s inside assemble-report, whose timeout is {timeout}s"
    )
