"""Unit tests for the archive initiate-restore Lambda (SPEC-171 FR-001).

The retrieval's own rules — the two tolerated codes, the attempt-everything-then-raise ordering
— have their suite in ``archive-common``; this file exercises them THROUGH the real handler and
covers what only the verb can carry: the batch shape the Map hands it, and the deliberate
ABSENCE of a failure notification. Runnable under pytest or directly:
python3 test_archive_initiate_restore.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_initiate_restore as m
import pytest
from arcommon.config import RESTORE_AVAILABILITY_DAYS, RESTORE_TIER
from cpcommon import clients

_ARCHIVE_ROOT = "personal/alice/archive/b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c/"


class _S3Error(Exception):
    def __init__(self, code, status=400):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class _FakeS3:
    def __init__(self, error=None):
        self.restores = []
        self._error = error

    def restore_object(self, **kwargs):
        self.restores.append(kwargs)
        error = self._error(kwargs) if callable(self._error) else self._error
        if error:
            raise error


def _install(error=None):
    fake = _FakeS3(error)
    clients._s3 = fake
    return fake


def _item(name="q1.csv"):
    return {
        "srcBucket": "archive-bkt",
        "srcKey": f"{_ARCHIVE_ROOT}reports/{name}",
        "destBucket": "user-bkt",
        "destKey": f"alice/reports/{name}",
        "size": 9,
        "storageClass": "STANDARD",
    }


def _batch(*items):
    return {"Items": list(items)}


def test_every_item_in_the_batch_is_asked_for_at_the_tier_and_window():
    fake = _install()

    out = m.handler(_batch(_item("a.csv"), _item("b.csv")), None)

    assert out == {"requested": 2}
    assert {call["Key"] for call in fake.restores} == {
        f"{_ARCHIVE_ROOT}reports/a.csv",
        f"{_ARCHIVE_ROOT}reports/b.csv",
    }
    assert fake.restores[0]["RestoreRequest"] == {
        "Days": RESTORE_AVAILABILITY_DAYS,
        "GlacierJobParameters": {"Tier": RESTORE_TIER},
    }


def test_an_already_in_progress_retrieval_does_not_fail_the_batch():
    """Which is what makes a re-submission after any later failure free rather than a second
    bill."""
    _install(error=_S3Error("RestoreAlreadyInProgress", 409))

    assert m.handler(_batch(_item("a.csv"), _item("b.csv")), None) == {"requested": 2}


def test_a_genuine_failure_raises_so_the_map_run_fails_and_nothing_is_copied():
    """FR-001 AC7. The retrieval Map tolerates no failure, so this raise is what stops the run —
    at which point the archive is untouched and the user simply re-submits."""
    _install(error=_S3Error("AccessDenied", 403))

    # The RAW fault propagates: the Map fails the child on it, and with
    # ToleratedFailurePercentage 0 that fails the Map Run and the run.
    with pytest.raises(_S3Error):
        m.handler(_batch(_item()), None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
