"""The acquire verb: what it returns, and what it must not destroy.

Two properties dominate this file, and both fail silently rather than loudly:

  - it is called in a LOOP and the machine replaces the whole state with its result, so a verb
    that returned only its own fields would erase the request on the first pass;
  - a cross-space request takes BOTH locks or NEITHER, so a waiter never holds one across the
    ``Wait`` and the give-up path has nothing left to free.
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

import file_ops_acquire_lock as v

ARN = "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"


@pytest.fixture(autouse=True)
def calls(monkeypatch):
    """Records every acquire and release, and lets a test decide which claims succeed."""
    log = {"acquired": [], "released": [], "refuse": set()}

    def _acquire(bucket, root, holder):
        log["acquired"].append((bucket, root, holder))
        if (bucket, root) in log["refuse"]:
            return False, None
        return True, f'"etag-{len(log["acquired"])}"'

    def _release(bucket, root, etag):
        log["released"].append((bucket, root, etag))

    monkeypatch.setattr(v.lock, "acquire", _acquire)
    monkeypatch.setattr(v.lock, "release", _release)
    return log


def _event(destination=None, attempt=None, **extra):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": "move" if destination else "delete",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": destination,
        "outcomes": [{"itemKey": "alice/a/", "label": "a", "outcome": "noop"}],
        "execution": {"arn": ARN},
    }
    if attempt is not None:
        event["lock"] = {"attempt": attempt}
    event.update(extra)
    return event


def test_a_single_space_takes_one_lock():
    result = v.handler(_event(), None)

    assert result["lock"]["acquired"] is True
    assert result["lock"]["attempt"] == 1
    assert len(result["lock"]["spaces"]) == 1


def test_a_cross_space_move_takes_TWO_locks(calls):
    result = v.handler(_event(destination={"bucket": "shared-bkt", "root": "sales/"}), None)

    assert result["lock"]["acquired"] is True
    assert len(result["lock"]["spaces"]) == 2
    assert len(calls["acquired"]) == 2


def test_losing_the_SECOND_lock_releases_the_first(calls):
    """The property that keeps a waiter from holding a lock across the Wait. Without it a
    cross-space request would wedge a space it never operated on for as long as it kept waiting.
    """
    # Refuse whichever space is claimed SECOND, computed from the digest order the verb uses —
    # refusing the first would leave nothing held, which is a different (and also correct) path.
    event = _event(destination={"bucket": "shared-bkt", "root": "sales/"})
    first, second = v._targets(event)
    calls["refuse"].add(second)

    result = v.handler(event, None)

    assert result["lock"]["acquired"] is False
    assert len(calls["released"]) == 1
    assert calls["released"][0][:2] == first
