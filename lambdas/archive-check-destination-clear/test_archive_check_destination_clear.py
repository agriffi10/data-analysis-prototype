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
        # SPEC-171: the machine SEEDS which pass this is. The verb never infers it — "the
        # retrieval has not run" and "the retrieval reported nothing" look identical from inside
        # a handler, and getting it wrong tells a user their retrieval is warm when it never ran.
        "guard": {"stage": "before"},
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
    # A SET, not a list: `heads` records thread completion order inside the pool, which is not a
    # property of this verb and would be a latent flake asserted as one.
    assert set(fake.heads) == {"alice/reports/q1.csv", "alice/notes.txt"}


def test_one_occupied_destination_refuses_the_whole_restore_and_notifies(_sink):
    """S3 has no move and no rename: restoring on top of a file the user re-created since
    archiving would destroy it silently."""
    _install(occupied={"alice/notes.txt"})

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "destination_occupied"
    assert _sink and _sink[0][0] == "alice"


# ── SPEC-171: the SECOND pass, and why it is worded differently ─────────────


def test_the_second_pass_after_the_retrieval_refuses_with_its_own_reason(_sink):
    """**THE STATE THAT KEEPS SPEC-170'S GUARANTEE TRUE AT THE MOMENT OF THE WRITE.** SPEC-171
    puts three to five BILLED hours between this guard and the copy — during which the receipt
    tells the user a restore is in flight and they have every reason to be working in their own
    space. Re-creating a file in that window is not an exotic race; it is the ordinary case this
    guard was written for, arriving late. With versioning off, one check at the start would let
    the copy-back overwrite it silently, report SUCCESS, and then sweep the vault.

    The reason code differs because the two refusals leave the user somewhere different: after
    the retrieval the objects are already out of Glacier and stay ready for a few days, so a
    prompt second attempt costs neither the wait nor the bill again — a fact they cannot infer.
    """
    _install(occupied={"alice/notes.txt"})

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(guard={"stage": "after"}), None)

    assert caught.value.reason == "destination_occupied_after_retrieval"
    assert _sink and "already been retrieved" in _sink[0][1]
    assert "not mean another long wait" in _sink[0][1]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
