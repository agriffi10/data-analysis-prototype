"""Unit tests for the archive inspect-archive Lambda (SPEC-170 FR-003).

The lookup rules have their own suite in ``archive-common``; this file exercises them THROUGH
the real handler and covers what only the verb can carry: the plan pointer coming back on the
state, the OBJECT LIST not coming back with it, and the actor being notified before the Catch
records a refusal. Runnable under pytest or directly:
python3 test_archive_inspect_archive.py.
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

import archive_inspect_archive as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"


class _S3Error(Exception):
    def __init__(self, code, status=404):
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
    def __init__(self, archived=(), manifest=None):
        self._archived = list(archived)
        self._manifest = manifest
        self.puts = []

    def get_paginator(self, name):
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": s} for k, s in outer._archived if k.startswith(Prefix)
                    ]
                }

        return _P()

    def get_object(self, Bucket, Key):
        if self._manifest is None:
            raise _S3Error("NoSuchKey")
        return {"Body": _Body(self._manifest)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _request(**overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "kind": "personal",
            "name": "alice",
        },
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "archiveId": _ARCHIVE_ID,
        },
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_the_plan_comes_back_as_a_POINTER_and_the_object_list_does_not():
    """At ARCHIVE_MAX_OBJECTS the list is tens of megabytes against a 256 KB payload limit, and
    States.DataLimitExceeded escapes every Catch — which on this plane is a run that told the
    user nothing at all."""
    fake = _install(archived=[(f"{_ARCHIVE_ROOT}reports/q1.csv", 90_112)])

    out = m.handler(_request(), None)

    assert out["planKey"] == f"archive/{_REQUEST_ID}/restore-plan.json"
    assert (out["objectCount"], out["totalBytes"]) == (1, 90_112)
    assert "objects" not in out
    assert not any(isinstance(value, list) for value in out.values()), (
        "nothing list-shaped may ride on the state — that is the payload limit's own shape"
    )
    assert fake.puts[0]["Bucket"] == "admin-bkt"


def test_the_written_plan_carries_every_destination_and_its_size():
    """SPEC-172 tells the user how much is coming back and SPEC-171 bounds its wait on these."""
    fake = _install(
        archived=[(f"{_ARCHIVE_ROOT}reports/q1.csv", 90_112), (f"{_ARCHIVE_ROOT}notes.txt", 12)]
    )

    m.handler(_request(), None)
    written = json.loads(fake.puts[0]["Body"])

    assert written["objects"] == [
        {
            "archiveKey": f"{_ARCHIVE_ROOT}reports/q1.csv",
            "destKey": "alice/reports/q1.csv",
            "bytes": 90_112,
        },
        {"archiveKey": f"{_ARCHIVE_ROOT}notes.txt", "destKey": "alice/notes.txt", "bytes": 12},
    ]
    assert written["objectCount"] == 2
    assert written["archive"]["archiveId"] == _ARCHIVE_ID


def test_the_request_is_threaded_onward_whole():
    """Every downstream state and every failure seed reads the request at the TOP level."""
    _install(archived=[(f"{_ARCHIVE_ROOT}q1.csv", 1)])

    out = m.handler(_request(), None)

    assert out["requestId"] == _REQUEST_ID
    assert out["mode"] == "restore"
    assert out["archive"]["root"] == _ARCHIVE_ROOT


def test_an_archive_that_is_not_there_refuses_and_notifies_the_actor(_sink):
    _install(archived=[])

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "archive_not_found"
    assert _sink and _sink[0][0] == "alice"


def test_the_refusal_is_worded_as_a_restore_and_names_the_id(_sink):
    """The two modes share one body table under two prefixes, and `mode` rides on the request —
    so a user who clicked Restore is not told an archive failed."""
    _install(archived=[])

    with pytest.raises(TerminalError):
        m.handler(_request(), None)

    text = _sink[0][1]
    assert text.startswith("Couldn't restore that: ")
    assert _ARCHIVE_ID in text


def test_a_record_that_disagrees_with_the_listing_refuses_before_the_plan_is_written():
    """A damaged archive leaves nothing behind in the admin bucket."""
    fake = _install(
        archived=[(f"{_ARCHIVE_ROOT}q1.csv", 1)],
        manifest={"objectCount": 4},
    )

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "restore_archive_incomplete"
    assert fake.puts == []


def test_a_missing_record_is_recorded_rather_than_refused():
    """FR-003 AC5. The manifest is not load-bearing; a restore that refused for want of a
    convenience record would be the failure mode the self-describing key layout prevents."""
    _install(archived=[(f"{_ARCHIVE_ROOT}q1.csv", 1)], manifest=None)

    out = m.handler(_request(), None)

    assert out["manifestPresent"] is False


def test_a_record_that_agrees_is_recorded_as_present():
    _install(archived=[(f"{_ARCHIVE_ROOT}q1.csv", 1)], manifest={"objectCount": 1})

    assert m.handler(_request(), None)["manifestPresent"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
