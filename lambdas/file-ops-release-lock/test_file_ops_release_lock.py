"""The release verb: it frees what was held, and it never fails the request.

Reached on every terminal path the machine's graph can walk — including one that holds nothing by
construction — so "release nothing" has to be an ordinary outcome rather than an error.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_release_lock as v


@pytest.fixture(autouse=True)
def released(monkeypatch):
    log = []
    monkeypatch.setattr(v.lock, "release", lambda b, r, e: log.append((b, r, e)))
    return log


def _held(*spaces):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "lock": {"acquired": True, "spaces": list(spaces)},
    }


def test_every_held_space_is_freed_against_its_own_tag(released):
    event = _held(
        {"bucket": "user-bkt", "root": "alice/", "etag": '"e1"'},
        {"bucket": "shared-bkt", "root": "sales/", "etag": '"e2"'},
    )

    assert v.handler(event, None) == {"released": 2}
    assert released == [("user-bkt", "alice/", '"e1"'), ("shared-bkt", "sales/", '"e2"')]


def test_holding_nothing_is_an_ORDINARY_outcome(released):
    """The give-up path reaches this verb holding nothing by construction — the acquire releases
    its first lock before reporting that it must wait — so this is the common case, not an edge."""
    assert v.handler({"requestId": "req-1"}, None) == {"released": 0}
    assert released == []
