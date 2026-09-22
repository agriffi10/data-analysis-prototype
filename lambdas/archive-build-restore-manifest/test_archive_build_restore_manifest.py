"""Unit tests for the archive build-restore-manifest Lambda (SPEC-171 FR-003).

What only this verb can get wrong: the storage class being STATED rather than defaulted, the
destinations coming from the plan rather than being recomputed, and one manifest serving both
Maps.
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
    """Every line is flagged as a folder placeholder or not, and the block counts the files.
    The plan's second object is an empty folder's placeholder, which is carried so the folder
    comes back and left out of the count so no sentence calls it a file."""
    fake = _install()

    out = m.handler(_request(), None)

    assert out["transfer"]["itemCount"] == 2
    assert out["transfer"]["fileCount"] == 1
    assert _lines(fake)[0] == {
        "srcBucket": "archive-bkt",
        "srcKey": f"{_ARCHIVE_ROOT}reports/q1.csv",
        "destBucket": "user-bkt",
        "destKey": "alice/reports/q1.csv",
        "size": 9,
        "storageClass": RESTORE_STORAGE_CLASS,
        "ifAbsent": True,
        "folder": False,
    }
    assert _lines(fake)[1]["folder"] is True


def test_a_folder_placeholder_is_carried_so_an_empty_folder_comes_back():
    """FR-003 AC6. A zero-byte key ending in a slash is how an empty folder survived the
    archive; dropping it here would restore a user's tree with its empty folders missing."""
    fake = _install()

    m.handler(_request(), None)

    assert [line["destKey"] for line in _lines(fake)] == ["alice/reports/q1.csv", "alice/empty/"]


def test_a_plan_that_is_not_this_runs_refuses_and_notifies(_sink):
    _install(_plan(requestId="00000000-0000-4000-8000-000000000000"))

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "plan_superseded"
    assert _sink and _sink[0][0] == "alice"


def test_every_line_the_restore_writes_refuses_to_overwrite():
    """**The property the whole conditional copy-back rests on, asserted over EVERY line rather
    than the first.** A builder that set it on the first item and not the rest would pass the
    shape assertion above and leave most of a restore overwriting silently."""
    fake = _install()

    m.handler(_request(), None)

    lines = _lines(fake)
    assert len(lines) > 1, "one line is not a population — this test is measuring nothing"
    assert all(line["ifAbsent"] is True for line in lines)


def test_the_archive_arm_writes_no_condition_at_all():
    """The other end of the same guarantee, and it is about the ABSENCE of a key rather than a
    false value: an archive's copy writes under a prefix the claim makes one run's alone, so a
    condition there buys nothing and costs a comparison on every retried batch. Asserted against
    the SOURCE of the archive's own builder — absent in the manifest is what makes absent in the
    request."""
    import pathlib

    verb = pathlib.Path(__file__).resolve().parent.parent / "archive-build-transfer-manifest"
    sources = [p for p in verb.glob("*.py") if not p.name.startswith("test_")]
    assert sources, "the archive's manifest builder has no production module"
    assert "ifAbsent" not in "".join(p.read_text() for p in sources)
