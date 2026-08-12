"""Unit tests for the archive write-manifest Lambda (SPEC-169 FR-006).

The first state on the commit branch. Its contents have their own suite in ``archive-common``;
what is tested here is the verb's own two jobs — assembling the record from the state, and
failing the WHOLE REQUEST at the cheapest moment on this plane, with the user still holding every
file.

Runnable under pytest or directly: python3 test_archive_write_manifest.py.
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

import archive_write_manifest as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ROOT = f"personal/alice/archive/{_REQUEST_ID}/"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, error=None):
        self.puts = []
        self._error = error

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._error:
            raise self._error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(error=None):
    fake = _FakeS3(error)
    clients._s3 = fake
    return fake


def _event():
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "execution": {"name": "arch-exec-1", "startedAt": "2026-08-10T14:02:11.123Z"},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
        "transferOutcome": {"copied": 1204, "failed": 0, "expected": 1204, "complete": True},
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_the_record_is_assembled_from_the_state_and_the_stamped_execution():
    """The time is the execution's start, not a clock read here: this file is written before the
    deletion and the receipt after it, so two now() calls would disagree by however long the
    deletion took."""
    fake = _install()

    result = m.handler(_event(), None)
    body = json.loads(fake.puts[0]["Body"])

    assert result["manifestKey"] == f"{_ARCHIVE_ROOT}_manifest.json"
    assert fake.puts[0]["Bucket"] == "archive-bkt"
    assert body["archivedAt"] == "2026-08-10T14:02:11.123Z"
    assert body["actor"] == "alice"
    assert (body["objectCount"], body["totalBytes"]) == (1204, 8_412_339_201)


def test_a_write_failure_fails_the_whole_request_before_anything_is_deleted(_no_real_notifications):
    """The cheapest moment on this plane for a failure: the user still holds every file, and the
    archive copy is left to the bucket's own lifecycle."""
    _install(error=_S3Error("AccessDenied"))

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "manifest_write_failed"
    assert "nothing was deleted" in _no_real_notifications[0][1]


def test_a_retryable_fault_is_not_terminalized():
    """The state's Retry re-runs the verb, which is safe because the key is a pure function of
    the archive root and the write is a whole-object PUT."""
    _install(error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_the_request_travels_through_to_the_deletion():
    fake = _install()

    result = m.handler(_event(), None)

    assert result["requestId"] == _REQUEST_ID
    assert result["source"]["name"] == "alice"
    assert result["archive"]["root"] == _ARCHIVE_ROOT
    assert len(fake.puts) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
