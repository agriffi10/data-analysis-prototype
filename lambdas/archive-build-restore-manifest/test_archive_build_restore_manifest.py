"""Unit tests for the archive build-restore-manifest Lambda (SPEC-171 FR-003).

What only this verb can get wrong: the storage class being STATED rather than defaulted, the
destinations coming from the plan rather than being recomputed, and one manifest serving both
Maps. Runnable under pytest or directly: python3 test_archive_build_restore_manifest.py.
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

import archive_build_restore_manifest as m
import pytest
from arcommon import notify
from arcommon.config import RESTORE_STORAGE_CLASS
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"
_PLAN_KEY = f"archive/{_REQUEST_ID}/restore-plan.json"


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
        return json.dumps(self._payload).encode()


class _FakeS3:
    def __init__(self, plan, get_error=None):
        self._plan = plan
        self._get_error = get_error
        self.puts = []

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise self._get_error
        return {"Body": _Body(self._plan)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def _plan(objects=None, **overrides):
    objects = objects if objects is not None else [
        {"archiveKey": f"{_ARCHIVE_ROOT}reports/q1.csv", "destKey": "alice/reports/q1.csv", "bytes": 9},
        {"archiveKey": f"{_ARCHIVE_ROOT}empty/", "destKey": "alice/empty/", "bytes": 0},
    ]
    base = {
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID},
        "space": {"bucket": "user-bkt", "root": "alice/"},
        "objectCount": len(objects),
        "totalBytes": 9,
        "objects": objects,
    }
    base.update(overrides)
    return base


def _install(plan=None, get_error=None):
    fake = _FakeS3(plan if plan is not None else _plan(), get_error)
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
        "totalBytes": 9,
        "execution": {"name": "exec-1", "startedAt": "2026-08-12T09:30:00.000Z"},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().splitlines() if line]


def test_the_manifest_names_the_archive_as_source_and_the_space_as_destination():
    fake = _install()

    out = m.handler(_request(), None)

    assert out["transfer"]["itemCount"] == 2
    assert _lines(fake)[0] == {
        "srcBucket": "archive-bkt",
        "srcKey": f"{_ARCHIVE_ROOT}reports/q1.csv",
        "destBucket": "user-bkt",
        "destKey": "alice/reports/q1.csv",
        "size": 9,
        "storageClass": RESTORE_STORAGE_CLASS,
    }


def test_the_storage_class_is_STATED_on_every_item_and_is_never_omitted():
    """FR-003 AC2, and it is the difference between a restore and a very expensive no-op. The
    engine treats an absent class as "do not pass the argument", which is S3's default — but the
    object being copied FROM is a temporary retrieval copy of a GLACIER object, so a copy that
    said nothing would land the restored object back in GLACIER, where it expires to unreadable
    a few days later having looked like a success throughout."""
    fake = _install()

    m.handler(_request(), None)

    assert {line["storageClass"] for line in _lines(fake)} == {"STANDARD"}


def test_a_folder_placeholder_is_carried_so_an_empty_folder_comes_back():
    """FR-003 AC6. A zero-byte key ending in a slash is how an empty folder survived the
    archive; dropping it here would restore a user's tree with its empty folders missing."""
    fake = _install()

    m.handler(_request(), None)

    assert [line["destKey"] for line in _lines(fake)] == ["alice/reports/q1.csv", "alice/empty/"]


def test_the_destinations_come_from_the_plan_and_are_not_recomputed():
    """They were built by paths.origin_key and they are the keys the destination guard cleared.
    A builder that disagreed would put a user's files somewhere the guard never looked."""
    fake = _install(_plan(objects=[
        {"archiveKey": f"{_ARCHIVE_ROOT}odd", "destKey": "alice/somewhere/else.csv", "bytes": 1},
    ]))

    m.handler(_request(objectCount=1), None)

    assert _lines(fake)[0]["destKey"] == "alice/somewhere/else.csv"


def test_the_manifest_key_is_execution_unique_and_both_result_prefixes_are_reported():
    fake = _install()

    out = m.handler(_request(), None)

    assert "exec-1/" in out["transfer"]["manifestKey"]
    assert fake.puts[0]["Key"] == out["transfer"]["manifestKey"]
    assert out["transfer"]["retrievalResultsPrefix"].endswith("/retrieval-results")
    assert out["transfer"]["resultsPrefix"].endswith("/restore-results")


def test_a_plan_that_is_not_this_runs_refuses_and_notifies(_sink):
    _install(_plan(requestId="00000000-0000-4000-8000-000000000000"))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_superseded"
    assert _sink and _sink[0][0] == "alice"


def test_an_unstamped_execution_refuses_rather_than_falling_back_to_the_request_id():
    _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(execution={}), None)

    assert caught.value.reason == "malformed_event"


def test_an_unreadable_plan_refuses_the_whole_request():
    """A manifest short of its plan would retrieve and copy fewer objects than the guard
    cleared, and the collector compares it against the same plan — so both counts would agree
    and be wrong."""
    _install(get_error=_S3Error("NoSuchKey", 404))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_unreadable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
