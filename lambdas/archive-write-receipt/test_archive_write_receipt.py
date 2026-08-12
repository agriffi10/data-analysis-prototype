"""Unit tests for the archive write-receipt Lambda (SPEC-169 FR-006).

The last state, and the only artifact of an archive the user can see. The document's format has
its own suite in ``archive-common``; what is tested here is the verb's own decision — that a
failed write fails the RUN, even though the data is safely archived, because a user with no
receipt has no id and therefore no route to a restore.

Runnable under pytest or directly: python3 test_archive_write_receipt.py.
"""

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

import archive_write_receipt as m
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
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}


def _install(error=None):
    fake = _FakeS3(error)
    clients._s3 = fake
    return fake


def _event(space_bucket="user-bkt", name="alice"):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": space_bucket, "root": f"{name}/", "kind": "personal", "name": name},
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "receiptBucket": space_bucket,
            "receiptKey": f"{name}/archive/{_REQUEST_ID}/receipt.txt",
        },
        "execution": {"name": "arch-exec-1", "startedAt": "2026-08-10T14:02:11.123Z"},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
        "deletedCount": 1204,
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_the_receipt_lands_in_the_space_the_archive_came_from():
    """Its own bucket, under the space's own root — the personal and shared cases differ in the
    bucket and in nothing else, which is the asymmetry with the archive key that carries a
    `personal/` or `shared/` segment precisely because those two namespaces meet there."""
    fake = _install()

    result = m.handler(_event(), None)

    assert result["receiptKey"] == f"alice/archive/{_REQUEST_ID}/receipt.txt"
    assert fake.puts[0]["Bucket"] == "user-bkt"
    assert fake.puts[0]["ContentType"].startswith("text/plain")


def test_a_shared_space_receipt_goes_to_the_shared_bucket_under_the_space_name():
    fake = _install()
    event = _event(space_bucket="shared-bkt", name="team-space")
    event["source"]["kind"] = "shared"

    result = m.handler(event, None)

    assert result["receiptKey"] == f"team-space/archive/{_REQUEST_ID}/receipt.txt"
    assert fake.puts[0]["Bucket"] == "shared-bkt"


def test_the_document_carries_the_counts_and_both_paths():
    fake = _install()

    m.handler(_event(), None)
    text = fake.puts[0]["Body"].decode()

    fields = dict(line.split(":", 1) for line in text.strip().splitlines())
    fields = {label: value.strip() for label, value in fields.items()}

    assert fields["Request ID"] == _REQUEST_ID
    assert fields["Original path"] == "s3://user-bkt/alice/"
    assert fields["Archived path"] == f"s3://archive-bkt/{_ARCHIVE_ROOT}"
    assert fields["Files archived"] == "1204"
    assert fields["Total size"] == "7.8 GB (8412339201 bytes)"


def test_a_failed_write_fails_the_run_and_says_the_data_is_archived(_no_real_notifications):
    """FR-006 AC7. The data IS archived and the source IS gone by this point — but a user with no
    receipt has no id and therefore no route to a restore, so the run is failed and the message
    names the request id, which makes it recoverable by hand."""
    _install(error=_S3Error("AccessDenied"))

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "receipt_write_failed"

    message = _no_real_notifications[0][1]
    assert "were archived" in message
    assert _REQUEST_ID in message
    assert "nothing was deleted" not in message


def test_a_retryable_fault_is_not_terminalized():
    """The state's Retry re-runs the verb — safe, because the key is a pure function of the
    request and the write is a whole-object PUT."""
    _install(error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
