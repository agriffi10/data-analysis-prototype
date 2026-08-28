"""Unit tests for the file-send inspect-source Lambda (SPEC-165).

The expansion rules and the caps have their own suite in ``file-send-common``; this file
exercises them THROUGH the real handler, and covers what only the verb can carry: the plan
pointer coming back on the state, the object list not coming back with it, and the sender being
notified before the Catch records a refusal. Runnable under pytest or directly:
python3 test_file_send_inspect_source.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_inspect_source as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from fscommon import notify


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, objects):
        self._objects = objects
        self.puts = []

    def get_paginator(self, name):
        objects = self._objects

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": s}
                        for k, s in sorted(objects.items())
                        if k.startswith(Prefix)
                    ]
                }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key]}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(objects):
    fake = _FakeS3(objects)
    clients._s3 = fake
    return fake


def _event(items=None):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }


@pytest.fixture
def notified(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, message, **kw: sent.append((user, message)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, message, **kw: sent.append((user, message)))
    return sent


def test_the_state_carries_the_plans_KEY_and_its_totals():
    _install({"alice/reports/q1.csv": 10, "alice/reports/2026/q2.csv": 20})

    result = m.handler(_event(), None)

    assert result["copyPlanKey"] == "file-send/req-1/copy-plan.json"
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 30


def test_a_refusal_notifies_the_sender_before_it_raises(notified):
    """The decorator's emit, which is what keeps a whole-request refusal from reaching the user
    as silence plus a failed execution they cannot see."""
    _install({"alice/empty/DO_NOT_DELETE.txt": 180})

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([{"kind": "folder", "key": "alice/empty/"}]), None)

    assert caught.value.reason == "nothing_to_send"
    assert notified == [("alice", "Couldn't send: there was nothing to send in what you selected.")]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


