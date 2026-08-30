"""Unit tests for the archive inspect-archive Lambda (SPEC-170 FR-003).

The lookup rules have their own suite in ``archive-common``; this file exercises them THROUGH
the real handler and covers what only the verb can carry: the plan pointer coming back on the
state, the OBJECT LIST not coming back with it, and the actor being notified before the Catch
records a refusal. Runnable under pytest or directly:
python3 test_archive_inspect_archive.py.
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

import archive_inspect_archive as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"


class _S3Error(Exception):
    def __init__(self, code, status=404):
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
    def __init__(self, archived=(), manifest=None):
        self._archived = list(archived)
        self._manifest = manifest
        self.puts = []

    def get_paginator(self, name):
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": s} for k, s in outer._archived if k.startswith(Prefix)
                    ]
                }

        return _P()

    def get_object(self, Bucket, Key):
        if self._manifest is None:
            raise _S3Error("NoSuchKey")
        return {"Body": _Body(self._manifest)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _request(**overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "kind": "personal",
            "name": "alice",
        },
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "archiveId": _ARCHIVE_ID,
        },
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_the_plan_comes_back_as_a_POINTER_and_the_object_list_does_not():
    """At ARCHIVE_MAX_OBJECTS the list is tens of megabytes against a 256 KB payload limit, and
    States.DataLimitExceeded escapes every Catch — which on this plane is a run that told the
    user nothing at all."""
    fake = _install(archived=[(f"{_ARCHIVE_ROOT}reports/q1.csv", 90_112)])

    out = m.handler(_request(), None)

    assert out["planKey"] == f"archive/{_REQUEST_ID}/restore-plan.json"
    assert (out["objectCount"], out["totalBytes"]) == (1, 90_112)
    assert "objects" not in out
    assert not any(isinstance(value, list) for value in out.values()), (
        "nothing list-shaped may ride on the state — that is the payload limit's own shape"
    )
    assert fake.puts[0]["Bucket"] == "admin-bkt"


def test_an_archive_that_is_not_there_refuses_and_notifies_the_actor(_sink):
    _install(archived=[])

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "archive_not_found"
    assert _sink and _sink[0][0] == "alice"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
