"""Unit tests for the archive poll-restore Lambda (SPEC-171 FR-002).

The header rule and the paged sweep have their suite in ``archive-common``; this file exercises
them THROUGH the real handler and covers what only the verb can carry: the progress record being
read before the sweep and written after it, and the two booleans the ASL Choice branches on being
computed HERE rather than compared in the machine. Runnable under pytest or directly:
python3 test_archive_poll_restore.py.
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

import archive_poll_restore as m
import pytest
from arcommon import notify
from arcommon.config import RESTORE_MAX_POLLS
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"
_PLAN_KEY = f"archive/{_REQUEST_ID}/restore-plan.json"
_PROGRESS_KEY = f"archive/{_REQUEST_ID}/restore-progress.json"

_DONE = {"Restore": 'ongoing-request="false", expiry-date="Fri, 21 Dec 2029 00:00:00 GMT"'}
_WORKING = {"Restore": 'ongoing-request="true"'}


class _S3Error(Exception):
    def __init__(self, code, status=400):
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
    def __init__(self, plan, progress=None, heads=None):
        self._plan = plan
        self._progress = progress
        self._heads = heads or {}
        self.headed = []
        self.puts = []

    def get_object(self, Bucket, Key):
        if Key.endswith("restore-progress.json"):
            if self._progress is None:
                raise _S3Error("NoSuchKey", 404)
            return {"Body": _Body(self._progress)}
        return {"Body": _Body(self._plan)}

    def head_object(self, Bucket, Key):
        self.headed.append(Key)
        found = self._heads.get(Key, _DONE)
        if isinstance(found, Exception):
            raise found
        return found

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def _plan(count=3):
    objects = [
        {"archiveKey": f"{_ARCHIVE_ROOT}f{n}.csv", "destKey": f"alice/f{n}.csv", "bytes": 1}
        for n in range(count)
    ]
    return {
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID},
        "space": {"bucket": "user-bkt", "root": "alice/"},
        "objectCount": count,
        "totalBytes": count,
        "objects": objects,
    }


def _install(count=3, progress=None, heads=None):
    fake = _FakeS3(_plan(count), progress, heads)
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
        "objectCount": 3,
        "totalBytes": 3,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_a_finished_retrieval_reports_complete_and_the_loop_can_leave():
    fake = _install()

    out = m.handler(_request(), None)

    assert out["restorePoll"]["complete"] is True
    assert out["restorePoll"]["exhausted"] is False
    assert out["restorePoll"]["completedThrough"] == 3
    assert set(fake.headed) == {f"{_ARCHIVE_ROOT}f{n}.csv" for n in range(3)}


def test_a_running_retrieval_reports_incomplete_and_records_where_it_got_to():
    fake = _install(heads={f"{_ARCHIVE_ROOT}f1.csv": _WORKING})

    out = m.handler(_request(), None)

    assert out["restorePoll"]["complete"] is False
    assert json.loads(fake.puts[0]["Body"])["pollCount"] == 1
    assert fake.puts[0]["Key"] == _PROGRESS_KEY


def test_the_iteration_count_advances_from_the_recorded_one_and_not_from_zero():
    """The loop's budget is counted across ITERATIONS, not within one, so a poll that read no
    progress would reset the count every time and the loop would never exhaust — it would spin
    until the machine's own ceiling instead, which reports the wrong cause."""
    fake = _install(
        progress={"pollCount": 5, "completedThrough": 0, "objectCount": 3},
        heads={f"{_ARCHIVE_ROOT}f0.csv": _WORKING},
    )

    out = m.handler(_request(), None)

    assert out["restorePoll"]["pollCount"] == 6
    assert json.loads(fake.puts[0]["Body"])["pollCount"] == 6


def test_the_budget_running_out_reports_exhausted_rather_than_looping_on():
    _install(
        progress={"pollCount": RESTORE_MAX_POLLS - 1, "completedThrough": 0, "objectCount": 3},
        heads={f"{_ARCHIVE_ROOT}f0.csv": _WORKING},
    )

    out = m.handler(_request(), None)

    assert out["restorePoll"]["exhausted"] is True
    assert out["restorePoll"]["complete"] is False


def test_a_complete_sweep_on_the_last_iteration_is_NOT_exhausted():
    """`exhausted` is only true when the budget ran out AND the retrieval had not finished.
    Reported the other way, a restore that completed on its final poll would be refused after
    six hours of waiting for it."""
    _install(progress={"pollCount": RESTORE_MAX_POLLS - 1, "completedThrough": 0, "objectCount": 3})

    out = m.handler(_request(), None)

    assert out["restorePoll"]["complete"] is True
    assert out["restorePoll"]["exhausted"] is False


def test_an_object_nothing_ever_asked_for_refuses_and_notifies(_sink):
    """FR-002 AC3. Read as "not yet" it would burn every remaining iteration and then report a
    timeout for something that was never going to complete."""
    _install(heads={f"{_ARCHIVE_ROOT}f2.csv": {"StorageClass": "GLACIER"}})

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "restore_never_requested"
    assert _sink and _sink[0][0] == "alice"


def test_the_recorded_progress_spares_the_heads_below_it():
    fake = _install(
        count=3,
        progress={"pollCount": 1, "completedThrough": 2, "objectCount": 3},
    )

    m.handler(_request(), None)

    assert fake.headed == [f"{_ARCHIVE_ROOT}f2.csv"]


def test_a_plan_that_is_not_this_runs_refuses():
    fake = _install()
    fake._plan["requestId"] = "00000000-0000-4000-8000-000000000000"

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_superseded"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
