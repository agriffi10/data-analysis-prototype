"""Unit tests for the archive check-destination-clear Lambda (SPEC-170 FR-004).

The guard's own rules — 403-is-occupied, the short-circuit, the bounded sample — have their
suite in ``archive-common``; this file exercises them THROUGH the real handler and covers what
only the verb can carry: the plan being read back and proved to be THIS run's, the actor being
notified, and the refusal reaching the user as a restore. Runnable under pytest or directly:
python3 test_archive_check_destination_clear.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_check_destination_clear as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"
_PLAN_KEY = f"archive/{_REQUEST_ID}/restore-plan.json"


class _S3Error(Exception):
    def __init__(self, code, status):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()


class _FakeS3:
    def __init__(self, plan, occupied=()):
        self._plan = plan
        self.occupied = set(occupied)
        self.heads = []

    def get_object(self, Bucket, Key):
        return {"Body": _Body(self._plan)}

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key in self.occupied:
            return {"ContentLength": 1}
        raise _S3Error("404", 404)


def _plan(objects=None, **overrides):
    objects = objects if objects is not None else [
        {"archiveKey": f"{_ARCHIVE_ROOT}reports/q1.csv", "destKey": "alice/reports/q1.csv", "bytes": 9},
        {"archiveKey": f"{_ARCHIVE_ROOT}notes.txt", "destKey": "alice/notes.txt", "bytes": 2},
    ]
    base = {
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID},
        "space": {"bucket": "user-bkt", "root": "alice/"},
        "objectCount": len(objects),
        "totalBytes": 11,
        "objects": objects,
    }
    base.update(overrides)
    return base


def _install(plan=None, occupied=()):
    fake = _FakeS3(plan if plan is not None else _plan(), occupied)
    clients._s3 = fake
    return fake


def _request(**overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID},
        "planKey": _PLAN_KEY,
        "objectCount": 2,
        "totalBytes": 11,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_a_clear_set_of_destinations_passes_and_threads_the_request_onward():
    fake = _install()

    out = m.handler(_request(), None)

    assert out["checkedCount"] == 2
    assert out["requestId"] == _REQUEST_ID
    assert out["planKey"] == _PLAN_KEY
    assert fake.heads == ["alice/reports/q1.csv", "alice/notes.txt"]


def test_one_occupied_destination_refuses_the_whole_restore_and_notifies(_sink):
    """S3 has no move and no rename: restoring on top of a file the user re-created since
    archiving would destroy it silently."""
    _install(occupied={"alice/notes.txt"})

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "destination_occupied"
    assert _sink and _sink[0][0] == "alice"


def test_the_message_names_the_path_the_user_would_recognise(_sink):
    """Relative to the space root — what they see in the file browser, not an s3:// URI."""
    _install(occupied={"alice/reports/q1.csv"})

    with pytest.raises(TerminalError):
        m.handler(_request(), None)

    text = _sink[0][1]
    assert "reports/q1.csv" in text
    assert "alice/reports/q1.csv" not in text
    assert text.startswith("Couldn't restore that: ")
    assert "may be more" in text


def test_a_plan_describing_another_run_is_refused_rather_than_guarded():
    """The plan's key is a pure function of the request id, so a second run under a reused id
    overwrites it — and a guard that checked THAT plan's destinations would clear a restore for
    a set of keys this run is not going to write."""
    _install(plan=_plan(requestId="00000000-0000-4000-8000-000000000000"))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_superseded"


def test_a_plan_short_of_the_count_it_records_is_refused():
    """A short plan means a guard that cleared fewer destinations than the restore will write."""
    _install(plan=_plan(objectCount=9))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_unreadable"


def test_an_entry_with_no_destination_is_refused_rather_than_skipped():
    _install(plan=_plan(objects=[{"archiveKey": f"{_ARCHIVE_ROOT}q1.csv", "bytes": 1}]))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_unreadable"


def test_the_guard_issues_no_head_at_all_when_the_plan_is_not_ours():
    """The identity check is cheap and total, and it runs FIRST: a guard that heads first and
    checks afterwards has already told itself the wrong answer."""
    fake = _install(plan=_plan(requestId="00000000-0000-4000-8000-000000000000"))

    with pytest.raises(TerminalError):
        m.handler(_request(), None)

    assert fake.heads == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
