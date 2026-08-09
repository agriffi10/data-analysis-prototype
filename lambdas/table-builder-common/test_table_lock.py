"""SPEC-157 FR-001/FR-004 — the per-table refresh lock.

The fake implements REAL conditional-put semantics, because every property this module has rests
on what happens when two writers race. A fake that ignored ``IfMatch``/``IfNoneMatch`` would make
the whole suite green regardless of the code — the trap SPEC-153 was written to close, and the
reason ``log-sweep``'s fake is built the same way.
"""

import json
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from cpcommon import clients, config
from tbcommon import table_lock

HOLDER = "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"
OTHER = "arn:aws:states:us-east-1:1:execution:orchestrator:run-b"
KEY = "locks/table-builder/alice/sales.json"


class _ClientError(Exception):
    """Carries an error code where ``cpcommon.errors.error_code`` looks for one."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeS3:
    """Implements real If-Match / If-None-Match semantics over a changing ETag."""

    def __init__(self, read_error=None):
        self.objects = {}
        self.puts = []
        self.deletes = []
        self.read_error = read_error
        self._n = 0

    def get_object(self, Bucket, Key):
        if self.read_error is not None:
            raise self.read_error
        if Key not in self.objects:
            raise _ClientError("NoSuchKey")
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise _ClientError("ConditionalRequestConflict")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _ClientError("PreconditionFailed")
        self._n += 1
        etag = f'"etag-{self._n}"'
        self.objects[Key] = (Body, etag)
        self.puts.append({"Key": Key, "Body": Body, "IfMatch": IfMatch, "IfNoneMatch": IfNoneMatch})
        return {"ETag": etag}

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)
        return {}

    def state_of(self, key):
        return json.loads(self.objects[key][0])


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(clients, "_s3", fake)
    monkeypatch.setattr(config, "ADMIN_BUCKET", "dat-prod-athena-admin", raising=False)
    return fake


def _seed(fake, *, holder, acquired_at, etag='"etag-0"'):
    """Places a lock object directly, bypassing the module under test."""
    body = json.dumps({"version": 1, "holder": holder, "acquiredAt": acquired_at}).encode("utf-8")
    fake.objects[KEY] = (body, etag)


def _iso(seconds_ago):
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── FR-001: the key ──────────────────────────────────────────────────────────


def test_the_key_is_scoped_per_database_and_table():
    assert table_lock.lock_key("alice", "sales") == KEY


@pytest.mark.parametrize(
    "database,table",
    [
        ("../../etc", "sales"),
        ("alice", "../../../secrets"),
        ("alice", "sales/../../other"),
        ("Alice", "sales"),
        ("alice", "Sales"),
        ("al", "sales"),
        ("alice", ""),
        ("alice", None),
        (None, "sales"),
        ("alice", "sales.json"),
    ],
)
def test_a_name_that_is_not_catalog_safe_is_refused_not_sanitised(database, table):
    """A sanitised name would silently address a DIFFERENT table's lock."""
    with pytest.raises(ValueError, match="not catalog-safe"):
        table_lock.lock_key(database, table)


# ── FR-001: the acquire protocol ─────────────────────────────────────────────


def test_an_absent_lock_is_created_with_if_none_match(s3):
    acquired, etag = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is True
    assert etag == '"etag-1"'
    assert s3.puts[0]["IfNoneMatch"] == "*"
    assert s3.puts[0]["IfMatch"] is None


def test_the_body_records_the_version_holder_and_claim_time(s3):
    table_lock.acquire("alice", "sales", HOLDER)

    state = s3.state_of(KEY)
    assert state["version"] == 1
    assert state["holder"] == HOLDER
    assert state["acquiredAt"].endswith("Z")
    assert set(state) == {"version", "holder", "acquiredAt"}


def test_a_free_lock_is_claimed_under_if_match(s3):
    _seed(s3, holder=None, acquired_at=None)

    acquired, etag = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is True
    assert s3.puts[0]["IfMatch"] == '"etag-0"'
    assert s3.state_of(KEY)["holder"] == HOLDER
    assert etag == '"etag-1"'


def test_a_live_holder_refuses_without_writing(s3):
    _seed(s3, holder=OTHER, acquired_at=_iso(30))

    acquired, etag = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is False
    assert etag is None
    assert s3.puts == []
    assert s3.state_of(KEY)["holder"] == OTHER


@pytest.mark.parametrize("code", ["PreconditionFailed", "412", "ConditionalRequestConflict", "409"])
def test_a_precondition_failure_reads_as_someone_else_holds_it(s3, monkeypatch, code):
    """A lock's lost CAS is the ANSWER, not a transient fault — so it must never retry."""

    def _conflict(**kwargs):
        raise _ClientError(code)

    monkeypatch.setattr(s3, "put_object", _conflict)

    assert table_lock.acquire("alice", "sales", HOLDER) == (False, None)


def test_a_write_fault_that_is_not_a_precondition_propagates(s3, monkeypatch):
    def _boom(**kwargs):
        raise _ClientError("InternalError")

    monkeypatch.setattr(s3, "put_object", _boom)

    with pytest.raises(_ClientError):
        table_lock.acquire("alice", "sales", HOLDER)


def test_an_unreadable_lock_refuses_rather_than_overwriting_a_live_holder(s3):
    """A transient READ error must not become a silent steal — the log-sweep discipline."""
    _seed(s3, holder=OTHER, acquired_at=_iso(30))
    s3.read_error = _ClientError("InternalError")

    acquired, _ = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is False
    assert s3.state_of(KEY)["holder"] == OTHER


# ── FR-001: release ──────────────────────────────────────────────────────────


def test_release_frees_the_lock_under_if_match(s3):
    _, etag = table_lock.acquire("alice", "sales", HOLDER)

    table_lock.release("alice", "sales", etag)

    assert s3.puts[-1]["IfMatch"] == etag
    assert s3.state_of(KEY) == {"version": 1, "holder": None, "acquiredAt": None}


def test_a_release_that_lost_its_cas_is_not_retried_and_never_raises(s3):
    """Losing it means the lock was STOLEN — re-writing would clobber the new holder."""
    _, etag = table_lock.acquire("alice", "sales", HOLDER)
    _seed(s3, holder=OTHER, acquired_at=_iso(1), etag='"etag-99"')
    before = len(s3.puts)

    table_lock.release("alice", "sales", etag)

    assert len(s3.puts) == before
    assert s3.state_of(KEY)["holder"] == OTHER


def test_release_without_an_etag_writes_nothing(s3):
    _seed(s3, holder=OTHER, acquired_at=_iso(1))

    table_lock.release("alice", "sales", None)

    assert s3.puts == []


def test_a_release_fault_is_swallowed(s3, monkeypatch):
    """A request that did its work must not report failure because of its own bookkeeping."""
    _, etag = table_lock.acquire("alice", "sales", HOLDER)

    def _down(**kwargs):
        raise RuntimeError("s3 is down")

    monkeypatch.setattr(s3, "put_object", _down)

    table_lock.release("alice", "sales", etag)


def test_the_lock_is_never_deleted(s3):
    """The execution role carries an explicit Deny on s3:DeleteObject for this bucket."""
    _, etag = table_lock.acquire("alice", "sales", HOLDER)
    table_lock.release("alice", "sales", etag)

    assert s3.deletes == []

    source = (pathlib.Path(__file__).parent / "tbcommon" / "table_lock.py").read_text()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("*"))
    assert "delete_object" not in code


# ── FR-004: stealing, and the bound that makes it legitimate ─────────────────


def test_the_steal_threshold_exceeds_the_machine_timeout():
    """A threshold BELOW the timeout would let a running execution's lock be stolen."""
    assert table_lock.STALE_LOCK_SECONDS > table_lock.MACHINE_TIMEOUT_SECONDS


def test_a_fresh_lock_is_not_stolen(s3):
    _seed(s3, holder=OTHER, acquired_at=_iso(table_lock.STALE_LOCK_SECONDS - 60))

    assert table_lock.acquire("alice", "sales", HOLDER) == (False, None)
    assert s3.state_of(KEY)["holder"] == OTHER


def test_an_expired_lock_is_stolen(s3):
    _seed(s3, holder=OTHER, acquired_at=_iso(table_lock.STALE_LOCK_SECONDS + 60))

    acquired, etag = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is True
    assert etag is not None
    assert s3.puts[0]["IfMatch"] == '"etag-0"'
    assert s3.state_of(KEY)["holder"] == HOLDER


@pytest.mark.parametrize(
    "raw",
    [b"not json at all", b"[]", b'{"version": 1', b"", b'"a string"'],
)
def test_a_malformed_body_is_stolen_not_treated_as_held(s3, raw):
    """A body nobody can read is not evidence that a refresh is running."""
    s3.objects[KEY] = (raw, '"etag-0"')

    acquired, _ = table_lock.acquire("alice", "sales", HOLDER)

    assert acquired is True
    assert s3.state_of(KEY)["holder"] == HOLDER


def test_a_lock_with_an_unparseable_claim_time_is_stolen(s3):
    _seed(s3, holder=OTHER, acquired_at="not-a-timestamp")

    assert table_lock.acquire("alice", "sales", HOLDER)[0] is True


def test_a_naive_claim_time_is_read_as_utc_not_as_unparseable(s3):
    """A body without the Z must not read as stale — that would steal a LIVE lock."""
    naive = (datetime.now(UTC) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")
    _seed(s3, holder=OTHER, acquired_at=naive)

    assert table_lock.acquire("alice", "sales", HOLDER) == (False, None)


def test_a_lock_with_no_claim_time_is_stolen(s3):
    _seed(s3, holder=OTHER, acquired_at=None)

    assert table_lock.acquire("alice", "sales", HOLDER)[0] is True


def test_two_simultaneous_steals_and_only_one_wins(s3, monkeypatch):
    """Both readers see the SAME stale tag, so the CAS decides — not the age check.

    Pinning the read is what makes this the concurrent case rather than two sequential ones: a
    second caller that re-read would be refused by the live-holder branch and would never reach
    the conditional write this test exists to exercise.
    """
    _seed(s3, holder=OTHER, acquired_at=_iso(table_lock.STALE_LOCK_SECONDS + 60))
    stale = s3.objects[KEY]
    monkeypatch.setattr(table_lock, "_read", lambda key: (stale[0], stale[1]))

    first, first_etag = table_lock.acquire("alice", "sales", HOLDER)
    second, second_etag = table_lock.acquire("alice", "sales", OTHER)

    assert first is True
    assert first_etag is not None
    assert second is False
    assert second_etag is None
    assert s3.state_of(KEY)["holder"] == HOLDER
