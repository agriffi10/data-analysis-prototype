"""Unit tests for the file-send copy-objects Lambda as a BATCH verb (SPEC-166 FR-002).

The copy mechanics live in ``cpcommon.transfer.copy`` and are tested there — deliberately, since
the engine is shared with table-share. What this file holds is what is file-send's: the batch
contract with the Distributed Map, the per-item isolation the collector depends on, and the
property that this verb knows nothing about recipients, plans or requests. Runnable under pytest
or directly: python3 test_file_send_copy_objects.py.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_copy_objects as m
import pytest
from cpcommon import clients
from cpcommon.errors import TransientError

GIB = 1024**3
_SOURCE = pathlib.Path(__file__).resolve().parent / "file_send_copy_objects.py"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, copy_error=None):
        self.copies = []
        self.copy_error = copy_error

    def copy_object(self, **kwargs):
        error = self.copy_error(kwargs) if callable(self.copy_error) else self.copy_error
        if error:
            raise error
        self.copies.append(kwargs)
        return {}


def _install(copy_error=None):
    fake = _FakeS3(copy_error)
    clients._s3 = fake
    return fake


def _item(recipient="bob", key="alice/notes.txt", size=512, kind="user"):
    return {
        "recipient": recipient,
        "kind": kind,
        "srcBucket": "user-bkt",
        "srcKey": key,
        "destBucket": "user-bkt",
        "destKey": f"{recipient}/shared_files/{key}",
        "size": size,
    }


def test_a_batch_copies_every_item_and_reports_the_count():
    fake = _install()

    outcome = m.handler({"Items": [_item(key="alice/a.csv"), _item(key="alice/b.csv")]}, None)

    assert outcome == {"copied": 2, "failures": []}
    assert len(fake.copies) == 2


def test_one_deterministic_failure_does_not_cost_its_siblings_their_copy():
    """The batch SUCCEEDS while reporting the failure, which is why the collector must read
    SUCCEEDED_n.json as well as FAILED_n.json."""
    _install(copy_error=lambda kwargs: _S3Error("NoSuchKey") if "b.csv" in kwargs["Key"] else None)

    outcome = m.handler(
        {"Items": [_item(key="alice/a.csv"), _item(recipient="carol", key="alice/b.csv")]}, None
    )

    assert outcome["copied"] == 1
    assert outcome["failures"] == [{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]


def test_a_transient_failure_raises_so_the_map_retries_the_whole_batch():
    """Correct and cheap: the copy is idempotent and the conflict guard has already run."""
    _install(copy_error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        m.handler({"Items": [_item()]}, None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
