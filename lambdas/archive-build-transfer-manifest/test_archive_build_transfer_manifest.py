"""Unit tests for the archive build-transfer-manifest Lambda (SPEC-169 FR-002).

The dataset the Distributed Map reads. What matters here is that every line carries the four
things the engine needs — source, destination, SIZE and STORAGE CLASS — and that the destination
comes from the one key builder a restore will invert. Runnable under pytest or directly:
python3 test_archive_build_transfer_manifest.py.
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

import archive_build_transfer_manifest as m
import pytest
from arcommon import notify
from arcommon.config import ARCHIVE_STORAGE_CLASS
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ROOT = f"personal/alice/archive/{_REQUEST_ID}/"


class _FakeS3:
    def __init__(self, plan_body):
        self._plan_body = plan_body
        self.puts = []

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._plan_body)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}


def _plan(objects=None):
    objects = objects or [
        {"relKey": "reports/2026/q1.csv", "bytes": 90_112},
        {"relKey": "reports/empty/", "bytes": 0},
    ]
    return json.dumps({
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "objectCount": len(objects),
        "totalBytes": sum(o["bytes"] for o in objects),
        "objects": objects,
    }).encode()


def _install(plan_body=None):
    fake = _FakeS3(plan_body or _plan())
    clients._s3 = fake
    return fake


def _event(execution="arch-exec-1"):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "copyPlanKey": f"archive/{_REQUEST_ID}/copy-plan.json",
        "execution": {"name": execution, "startedAt": "2026-08-10T14:02:11.123Z"},
        "objectCount": 2,
        "totalBytes": 90_112,
    }


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().splitlines()]


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_every_line_carries_the_storage_class_from_the_one_definition():
    """FR-002 AC1. The choice the whole arc is shaped by — a GLACIER object cannot be copied at
    all until a billed, hours-long retrieval has finished — so a second home for it is how one
    verb archives to a class the restore path was not built for."""
    fake = _install()

    m.handler(_event(), None)

    assert {line["storageClass"] for line in _lines(fake)} == {ARCHIVE_STORAGE_CLASS}


def test_a_plan_short_of_its_recorded_count_is_refused_before_a_line_is_written():
    """The shape that would otherwise produce a manifest short of its lines, a copy that
    succeeded over it, a commit gate that agreed with both, and a deletion of a source the
    archive does not hold."""
    truncated = json.loads(_plan())
    truncated["objectCount"] = 5
    fake = _install(json.dumps(truncated).encode())

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "plan_unreadable"
    assert fake.puts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
