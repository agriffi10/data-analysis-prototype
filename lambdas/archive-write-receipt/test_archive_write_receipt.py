"""Unit tests for the archive write-receipt Lambda (SPEC-169 FR-006).

The last state, and the only artifact of an archive the user can see. The document's format has
its own suite in ``archive-common``; what is tested here is the verb's own decision — that a
failed write fails the RUN, even though the data is safely archived, because a user with no
receipt has no id and therefore no route to a restore.
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

import archive_write_receipt as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ROOT = f"personal/alice/archive/{_REQUEST_ID}/"


_INDEX_KEY = "alice/system_settings/archive/index.json"


class _S3Error(Exception):
    def __init__(self, code, status=400):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """The receipt's write, plus the index's conditional read and write.

    ``puts`` records the receipt writes the verb's own contract is about; the index lives in
    ``objects`` and honours If-Match / If-None-Match, because the index is a compare-and-swap and a
    fake that ignored the conditions would let an index test pass without the index code running.
    """

    def __init__(self, error=None, index_error=None):
        self.puts = []
        self.index_puts = 0
        self.objects = {}
        self._error = error
        self._index_error = index_error

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _S3Error("NoSuchKey", 404)
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType, IfMatch=None, IfNoneMatch=None):
        if Key == _INDEX_KEY:
            self.index_puts += 1
            if self._index_error:
                raise self._index_error
            current = self.objects.get(Key)
            if IfNoneMatch == "*" and current is not None:
                raise _S3Error("ConditionalRequestConflict", 409)
            if IfMatch is not None and (current is None or current[1] != IfMatch):
                raise _S3Error("PreconditionFailed", 412)
            self.objects[Key] = (Body, f'"etag-{self.index_puts}"')
            return {}
        if self._error:
            raise self._error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}

    def index(self):
        return json.loads(self.objects[_INDEX_KEY][0])


def _install(error=None, index_error=None):
    fake = _FakeS3(error, index_error)
    clients._s3 = fake
    return fake


def _event(space_bucket="user-bkt", name="alice", archive=None):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {
            "bucket": space_bucket,
            "root": f"{name}/",
            "kind": "personal",
            "name": name,
            "items": [{"kind": "folder", "key": f"{name}/reports/"}],
        },
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "receiptBucket": space_bucket,
            "receiptKey": f"{name}/archive/{_REQUEST_ID}/receipt.txt",
            **(archive or {}),
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


# ── The name, and the index ─────────────────────────────────────────────────


def test_the_receipt_opens_with_the_archives_name_or_a_placeholder():
    fake = _install()

    m.handler(_event(archive={"name": "Q1 reports"}), None)
    m.handler(_event(), None)

    named, unnamed = (put["Body"].decode().splitlines()[0] for put in fake.puts)
    assert named.split(":", 1) == ["Name", "              Q1 reports"]
    assert unnamed.split(":", 1)[1].strip() == "-"


def test_the_archive_is_recorded_in_the_spaces_index_after_its_receipt():
    fake = _install()

    result = m.handler(_event(archive={"indexKey": _INDEX_KEY, "name": "Q1 reports"}), None)

    assert result["receiptKey"] == f"alice/archive/{_REQUEST_ID}/receipt.txt"
    (entry,) = fake.index()["archives"]
    assert entry["archiveId"] == _REQUEST_ID
    assert entry["name"] == "Q1 reports"
    assert entry["archivedAt"] == "2026-08-10T14:02:11.123Z"
    assert entry["items"] == [{"kind": "folder", "path": "reports/"}]
    assert entry["totalBytes"] == 8_412_339_201
    assert entry["restore"] is None


def test_an_archive_whose_receipt_failed_is_not_indexed():
    """The receipt folder is what puts an archive in the restore list, so a label with no receipt
    would label a row the list never shows."""
    fake = _install(error=_S3Error("AccessDenied", 403))

    with pytest.raises(TerminalError):
        m.handler(_event(archive={"indexKey": _INDEX_KEY}), None)

    assert fake.index_puts == 0


def test_an_index_that_cannot_be_written_does_not_fail_a_completed_archive():
    fake = _install(index_error=_S3Error("AccessDenied", 403))

    result = m.handler(_event(archive={"indexKey": _INDEX_KEY}), None)

    assert fake.index_puts == 1
    assert result["receiptKey"] == f"alice/archive/{_REQUEST_ID}/receipt.txt"


def test_a_run_validated_before_the_index_existed_is_simply_not_indexed():
    """Deploy skew: an execution the old front door validated carries no index key."""
    fake = _install()

    result = m.handler(_event(), None)

    assert fake.index_puts == 0
    assert result["receiptKey"] == f"alice/archive/{_REQUEST_ID}/receipt.txt"
