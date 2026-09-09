"""SPEC-157 FR-002 — the refresh lock's release verb.

It runs on paths the CREATE branch shares, so the no-op case is not an edge case here: it is the
majority of invocations. The assertions weighted accordingly.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import release_refresh_lock as verb
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
