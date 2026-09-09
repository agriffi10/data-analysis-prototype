"""Unit tests for the archive update-receipt Lambda (SPEC-171 FR-004, FR-006).

One function serves three stages of a restore, and each has a DIFFERENT failure contract — which
is the thing this file mostly exists to pin. Before the bill a failed write fails the run; after
the data has landed it must not; and the third stage always raises whatever the write did.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_update_receipt as m
import pytest
from arcommon import notify, receipt
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"
_RECEIPT_KEY = f"alice/archive/{_ARCHIVE_ID}/receipt.txt"

_EXISTING = receipt.render(
    {
        "requestId": _ARCHIVE_ID,
        "startedAt": "2026-08-10T14:02:11.123Z",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
    }
)


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
        return self._payload


class _FakeS3:
    def __init__(self, existing=_EXISTING, get_error=None, put_error=None):
        self._existing = existing
        self._get_error = get_error
        self._put_error = put_error
        self.puts = []

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise self._get_error
        if self._existing is None:
            raise _S3Error("NoSuchKey", 404)
        return {"Body": _Body(self._existing.encode())}

    def put_object(self, **kwargs):
        if self._put_error:
            raise self._put_error
        self.puts.append(kwargs)


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _request(status="restored", **overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "archiveId": _ARCHIVE_ID,
            "receiptBucket": "user-bkt",
            "receiptKey": _RECEIPT_KEY,
        },
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
        "transferOutcome": {"copied": 1204, "failed": 0, "expected": 1204, "complete": True},
        "restore": {"status": status, "requestedAt": "2026-08-12T09:30:00.000Z"},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _written(fake):
    return fake.puts[0]["Body"].decode()


# ── the three stages ────────────────────────────────────────────────────────


def test_the_requested_stage_marks_the_receipt_before_anything_is_billed():
    """FR-006 AC4. The user is about to wait 3-5 hours and this is the only durable place that
    says a restore is in flight."""
    fake = _install()

    out = m.handler(_request(status="requested"), None)

    assert out["receiptKey"] == _RECEIPT_KEY
    assert fake.puts[0]["Key"] == _RECEIPT_KEY
    assert "Restore requested: 2026-08-12 09:30:00 UTC" in _written(fake).replace("   ", "")
    assert "Restored to:" in _written(fake)


def test_the_restored_stage_names_where_the_data_landed():
    """**The assertion has to be on the `Restored to` LINE, not on the document.** `render`
    already emits `Original path: s3://user-bkt/alice/`, and the rewrite keeps every other line
    verbatim — so "the destination appears somewhere in the text" is true however the restore
    line is filled in. Measured: forcing `restore_lines` to return a placeholder left the
    document-wide version of this test GREEN."""
    fake = _install()

    m.handler(_request(), None)

    line = next(
        ln for ln in _written(fake).splitlines() if ln.startswith(receipt.RESTORED_TO_LABEL)
    )
    assert line.split(":", 1)[1].strip() == "s3://user-bkt/alice/"


def test_the_incomplete_stage_ALWAYS_raises_after_recording_what_it_can():
    """FR-004, and it is the rollback verb's shape: record the outcome, then fail deliberately.
    The message names all three things a user needs — how many came back, that the archive is
    intact under the same id, and that re-requesting will report the files that did land."""
    fake = _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(
            _request(
                status="incomplete",
                transferOutcome={"copied": 40, "failed": 60, "expected": 100, "complete": False},
            ),
            None,
        )

    assert caught.value.reason == "restore_incomplete"
    assert caught.value.tokens == {"restored": "40", "total": "100"}
    assert "did not finish" in _written(fake)
    assert "40 of 100" in _written(fake)


# ── the rewrite itself ──────────────────────────────────────────────────────
