"""Unit tests for the archive update-receipt Lambda (SPEC-171 FR-004, FR-006).

One function serves three stages of a restore, and each has a DIFFERENT failure contract — which
is the thing this file mostly exists to pin. Before the bill a failed write fails the run; after
the data has landed it must not; and the third stage always raises whatever the write did.
Runnable under pytest or directly: python3 test_archive_update_receipt.py.
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

import archive_update_receipt as m
import pytest
from arcommon import notify, receipt
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

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
    fake = _install()

    m.handler(_request(), None)

    assert "s3://user-bkt/alice/" in _written(fake)


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


def test_the_incomplete_stage_still_raises_when_the_receipt_could_not_be_written(_sink):
    """The data that landed has landed either way, and the raise is the outcome that matters.
    A receipt fault swallowing the partial-restore failure would report a SUCCESS over a restore
    that put back 40 of 100 files."""
    _install(put_error=_S3Error("AccessDenied", 403))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(status="incomplete"), None)

    assert caught.value.reason == "restore_incomplete"
    assert _sink and _sink[0][0] == "alice"


def test_the_receipts_sentence_and_the_failures_tokens_come_from_ONE_source():
    """**Found while writing this file, and it is the kind of split that only shows up when the
    two disagree.** The seed says which STAGE is being recorded; the collector's verdict says
    what HAPPENED. Carried on both, the number written onto the receipt and the number in the
    notification would have two sources — and a user comparing them would have no way to tell
    which was right.

    Asserted by seeding a contradiction: whatever the `restore` block claims, both outputs must
    report what the run actually did.
    """
    fake = _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(
            _request(
                status="incomplete",
                restore={
                    "status": "incomplete",
                    "requestedAt": "2026-08-12T09:30:00.000Z",
                    "restored": 999,
                    "expected": 999,
                },
                transferOutcome={"copied": 40, "failed": 60, "expected": 100, "complete": False},
            ),
            None,
        )

    assert caught.value.tokens == {"restored": "40", "total": "100"}
    assert "40 of 100" in _written(fake)
    assert "999" not in _written(fake)


# ── the rewrite itself ──────────────────────────────────────────────────────


def test_the_archive_lines_survive_the_rewrite_untouched():
    """**THE POINT OF REWRITING RATHER THAN RE-RENDERING.** The archive's own start time is the
    one field no restore run can recompute, so a fresh render would silently blank it — on the
    only durable record the user has of what was archived and when."""
    fake = _install()

    m.handler(_request(), None)
    written = _written(fake)

    assert "2026-08-10 14:02:11 UTC" in written
    assert _ARCHIVE_ID in written
    assert "1204" in written
    assert "7.8 GB" in written


def test_an_absent_receipt_is_composed_fresh_rather_than_leaving_the_restore_unrecorded():
    """Reachable only when S3 PROVED the receipt is gone. Every field is exact except the
    archive's own start time, which cannot be recovered — which is exactly why the ordinary path
    rewrites."""
    fake = _install(existing=None)

    m.handler(_request(), None)
    written = _written(fake)

    assert f"Request ID:        {_ARCHIVE_ID}" in written
    assert "Requested:         -" in written
    assert "s3://user-bkt/alice/" in written


def test_the_composed_receipt_names_the_ARCHIVES_id_and_not_this_runs():
    """They are deliberately different values (SPEC-170 FR-001), and the one that belongs on
    this document is the one that opened it — it is what a user pastes to restore again."""
    fake = _install(existing=None)

    m.handler(_request(), None)

    assert _REQUEST_ID not in _written(fake)


def test_an_ambiguous_read_fails_rather_than_overwriting_a_receipt_it_could_not_read():
    """The guard's 403-is-occupied discipline applied to a write. Composing a fresh document on
    a 403 would destroy the archive's timestamp over a permissions blip."""
    _install(get_error=_S3Error("AccessDenied", 403))

    with pytest.raises(_S3Error):
        m.handler(_request(status="requested"), None)


def test_a_throttle_stays_transient_so_the_states_retry_reruns_the_verb():
    _install(put_error=_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        m.handler(_request(), None)


def test_a_shared_space_restore_names_the_shared_bucket_and_root():
    fake = _install()

    m.handler(
        _request(
            source={"bucket": "shared-bkt", "root": "team-x/", "kind": "shared", "name": "team-x"},
        ),
        None,
    )

    assert "s3://shared-bkt/team-x/" in _written(fake)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
