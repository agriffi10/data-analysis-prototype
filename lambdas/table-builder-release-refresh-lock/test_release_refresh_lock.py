"""SPEC-157 FR-002 — the refresh lock's release verb.

It runs on paths the CREATE branch shares, so the no-op case is not an edge case here: it is the
majority of invocations. The assertions weighted accordingly.

Runnable under pytest or directly: python3 test_release_refresh_lock.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import release_refresh_lock as verb
from cpcommon import clients, config
from tbcommon import table_lock

REQUEST = {
    "requestId": "req-1",
    "actor": "alice",
    "mode": "refresh",
    "tableName": "sales",
    "space": {"database": "alice"},
    "lock": {"etag": '"etag-1"'},
}


@pytest.fixture
def released(monkeypatch):
    calls = []

    def _release(database, table, etag):
        calls.append((database, table, etag))

    monkeypatch.setattr(table_lock, "release", _release)
    return calls


def test_a_held_lock_is_released_under_its_own_tag(released):
    assert verb.handler(dict(REQUEST), None) == {"released": True}
    assert released == [("alice", "sales", '"etag-1"')]


def test_a_create_passes_straight_through(released):
    """Every create reaches this verb — the state sits on a shared path deliberately, because
    the alternative is a Choice on a possibly-absent key, which raises the uncatchable
    States.Runtime."""
    event = {k: v for k, v in REQUEST.items() if k != "lock"}

    assert verb.handler(event, None) == {"released": False}
    assert released == []


def test_a_validate_failure_seed_does_not_raise(released):
    """The failure path reaches here carrying null identity. A raise would replace a RECORDED
    failure with an unrecorded one — the execution would die before NotifyFailure ran."""
    seed = {
        "requestId": None,
        "actor": None,
        "space": {"database": None},
        "tableName": None,
        "mode": "create",
        "error": {"Error": "States.TaskFailed", "Cause": "boom"},
    }

    assert verb.handler(seed, None) == {"released": False}
    assert released == []


def test_a_lock_with_no_usable_table_identity_is_not_released(released):
    """A held tag but a null table means the state is not one this verb can act on. Guessing a
    key from a null name is how a lock belonging to something else gets freed."""
    event = {**REQUEST, "tableName": None}

    assert verb.handler(event, None) == {"released": False}
    assert released == []


def test_a_dead_s3_does_not_fail_the_request(monkeypatch):
    """FR-002 AC3, exercised through the REAL primitive rather than a stub of it.

    Release must never fail the request: the lock is recoverable by the staleness steal, and a
    request that did its work and then reported failure over its own bookkeeping is strictly
    worse. There are two layers — the primitive swallows, and the ASL Catch continues — and this
    asserts the first one holds at the verb boundary, where a future refactor would break it.
    """

    class _Dead:
        def get_object(self, **kwargs):
            raise RuntimeError("s3 is down")

        def put_object(self, **kwargs):
            raise RuntimeError("s3 is down")

    monkeypatch.setattr(clients, "_s3", _Dead())
    monkeypatch.setattr(config, "ADMIN_BUCKET", "dat-prod-athena-admin", raising=False)

    assert verb.handler(dict(REQUEST), None) == {"released": True}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
