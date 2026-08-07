"""Unit tests for dqcommon.index_store — the per-space runs index (SPEC-123 FR-001).

The fake S3 below implements REAL conditional-put semantics (If-Match / If-None-Match with
a changing ETag), because the whole FR is about what happens when two writers race. A fake
that ignored the preconditions would make every CAS test pass without exercising the CAS.

Runnable under pytest or directly: python3 test_index_store_dqcommon.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients
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

    def __init__(self, objects=None):
        self.objects = dict(objects or {})  # key -> (bytes, etag)
        self.puts = 0
        self.version = 0
        #: Fires once before a put commits, to simulate a writer landing mid-CAS.
        self.on_put = None

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
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


def _install(objects=None):
    fake = _FakeS3(objects)
    clients._s3 = fake
    return fake


def _summary(request_id="r-1", **over):
    summary = {
        "requestId": request_id,
        "location": "alice/sales",
        "format": "csv",
        "verdict": "issues_found",
        "fileCount": 3,
        "hasApproximateFigures": True,
        "completedAt": "2026-07-21T14:32:11Z",
    }
    summary.update(over)
    return summary


# ── The key + the entry shape ────────────────────────────────────────────────


def test_the_index_is_per_space_one_level_above_the_request_prefix():
    assert index_store.index_key(PREFIX) == KEY
    assert index_store.index_key("finance/_data-quality-reports/abc/") == "finance/_data-quality-reports/index.json"


def test_the_entry_carries_the_row_fields_and_nothing_else():
    """The dashboard fetches this whole file on every load; anything extra is paid for on
    every page view and rendered on none of them."""
    entry = index_store.entry_from(_summary())
    assert set(entry) == set(index_store.ENTRY_FIELDS)
    assert entry["timestamp"] == "2026-07-21T14:32:11Z"


def test_the_entry_is_built_by_whitelist_not_by_stripping_the_event():
    """A blacklist would leak whatever field a later spec threads onto the state."""
    entry = index_store.entry_from(
        _summary(idToken="secret", manifestKey="alice/…/manifest.json", topIssues=["…"])
    )
    assert "idToken" not in entry
    assert "manifestKey" not in entry
    assert "topIssues" not in entry


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


def test_a_lost_race_is_retried_not_dropped():
    fake = _install()
    fake.on_put = lambda: fake.put_object(
        Bucket=BUCKET, Key=KEY, Body=json.dumps({"entries": []}).encode(), IfNoneMatch="*"
    )
    assert index_store.append(BUCKET, PREFIX, _summary()) is True
    assert [e["requestId"] for e in fake.entries()] == ["r-1"]


def test_an_exhausted_cas_does_not_fail_the_check():
    """The report is written and the notification has fired by now. A lost ROW must never
    become a lost CHECK."""

    class _AlwaysConflicts(_FakeS3):
        def put_object(self, **kwargs):
            raise _ClientError("PreconditionFailed")

    fake = _AlwaysConflicts()
    clients._s3 = fake
    assert index_store.append(BUCKET, PREFIX, _summary()) is False  # reported, not raised


def test_a_non_precondition_write_error_is_swallowed_too():
    class _Denied(_FakeS3):
        def put_object(self, **kwargs):
            raise _ClientError("AccessDenied")

    clients._s3 = _Denied()
    assert index_store.append(BUCKET, PREFIX, _summary()) is False


def test_append_never_raises_on_a_junk_summary():
    _install()
    for junk in ({}, {"requestId": None}, {"completedAt": 7}):
        index_store.append(BUCKET, PREFIX, junk)


# ── Absent / corrupt / capped ────────────────────────────────────────────────


def test_a_missing_index_is_created():
    fake = _install()
    assert index_store.append(BUCKET, PREFIX, _summary()) is True
    assert [e["requestId"] for e in fake.entries()] == ["r-1"]


def test_a_corrupt_index_is_rebuilt_rather_than_failing_the_space_forever():
    """One bad object must not permanently stop a space recording runs — the entries it
    would preserve are a convenience whose source of truth (the reports) is intact."""
    fake = _install({KEY: (b"{ this is not json", '"etag-0"')})
    assert index_store.append(BUCKET, PREFIX, _summary()) is True
    assert [e["requestId"] for e in fake.entries()] == ["r-1"]


def test_an_index_whose_entries_are_the_wrong_type_is_rebuilt():
    fake = _install({KEY: (json.dumps({"entries": {"not": "a list"}}).encode(), '"etag-0"')})
    assert index_store.append(BUCKET, PREFIX, _summary()) is True
    assert [e["requestId"] for e in fake.entries()] == ["r-1"]


def test_a_rebuild_still_goes_through_the_cas():
    """It must not clobber a writer who repaired the object in the meantime."""
    fake = _install({KEY: (b"corrupt", '"etag-0"')})
    index_store.append(BUCKET, PREFIX, _summary())
    # The rebuild carried the corrupt object's ETag, so a stale writer would have lost.
    assert fake.puts == 1


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


def test_a_replayed_request_replaces_its_row_instead_of_duplicating_it():
    """The report key is a pure function of requestId and gets overwritten on a Step
    Functions Retry or an SQS redelivery, so its row must behave the same way."""
    fake = _install()
    index_store.append(BUCKET, PREFIX, _summary(verdict="clean"))
    index_store.append(BUCKET, PREFIX, _summary(verdict="issues_found"))

    entries = fake.entries()
    assert len(entries) == 1
    assert entries[0]["verdict"] == "issues_found"


# ── SPEC-153 FR-010: CAS parity with the log-sweep twin ──────────────────────


def test_a_read_failure_never_overwrites_an_existing_day():
    """The twin's ``test_a_read_failure_never_overwrites_an_existing_day``, which this
    module was missing.

    ``_read`` swallows ANY exception and returns ``([], None)`` — deliberately, so an absent
    index is the ordinary case rather than an error. The cost is that a transient GET fault
    is indistinguishable from "no index yet", and the empty list it returns is what the CAS
    would then write. What saves the existing rows is the ``None`` etag: it selects
    ``If-None-Match: *``, which an existing object rejects. That is load-bearing and was
    asserted nowhere here, so "a transient read failure cannot truncate a space's index"
    rested on a line of reasoning rather than a test.
    """
    existing = [{"requestId": "precious", "timestamp": "2026-01-01T00:00:00Z"}]
    fake = _install({KEY: (json.dumps({"entries": existing}).encode(), '"etag-0"')})

    def _throttled(**kwargs):
        raise _ClientError("SlowDown")

    fake.get_object = _throttled

    assert index_store.append(BUCKET, PREFIX, _summary()) is False
    assert fake.entries() == existing, "a failed read truncated the space's index"
    assert fake.puts == 0


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all index-store tests passed")
