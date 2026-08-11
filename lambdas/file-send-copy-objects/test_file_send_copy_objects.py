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
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
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


def test_a_failure_names_the_recipient_pair_and_never_the_key():
    """The failure list rides the exported result and then the state, and keys are the unbounded
    term. The kind travels with the name because a destination is that PAIR."""
    _install(copy_error=_S3Error("AccessDenied"))

    outcome = m.handler({"Items": [_item(recipient="finance", kind="space")]}, None)

    assert outcome["failures"] == [{"recipient": "finance", "kind": "space", "reason": "copy_failed"}]


def test_a_transient_failure_raises_so_the_map_retries_the_whole_batch():
    """Correct and cheap: the copy is idempotent and the conflict guard has already run."""
    _install(copy_error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        m.handler({"Items": [_item()]}, None)


def test_an_empty_batch_is_not_an_error():
    """Reachable through a Map whose manifest emptied between the Choice and the run; reporting
    zero copies is the honest answer and keeps the export attributable."""
    _install()

    assert m.handler({"Items": []}, None) == {"copied": 0, "failures": []}


def test_the_verb_knows_nothing_about_this_plane_beyond_its_reason_code():
    """FR-002. Every destination was resolved upstream and written into the manifest — a verb
    that reached for the request or the copy plan would be re-deciding a question the guard has
    already answered, one batch at a time."""
    source = _SOURCE.read_text()

    for forbidden in ("copy_plan", "recipient_location", "destination_key", "fscommon"):
        assert forbidden not in source, f"copy-objects reached for {forbidden}"


def test_the_engine_is_the_shared_one():
    """SPEC-166 Out of Scope: if something is missing from cpcommon.transfer it is added THERE
    and table-share gets it too. A forked copier here is a spec failure, and this is the check
    that would catch one being written."""
    assert "from cpcommon.transfer import copy" in _SOURCE.read_text()
    assert m.copy_mod.__name__ == "cpcommon.transfer.copy"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
