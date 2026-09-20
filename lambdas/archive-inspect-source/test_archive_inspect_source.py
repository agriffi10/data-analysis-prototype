"""Unit tests for the archive inspect-source Lambda (SPEC-169 FR-001).

The expansion rules and the caps have their own suite in ``archive-common``; this file exercises
them THROUGH the real handler and covers what only the verb can carry: the plan pointer coming
back on the state, the object list NOT coming back with it, and the actor being notified before
the Catch records a refusal.
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

import archive_inspect_source as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
#: The execution name the machine stamps onto the state before this verb runs. It is here
#: because the stamp precedes inspect-source on the archive arm, so a fixture without it is a
#: shape the machine cannot produce.
_EXECUTION = "e4a1c0d2-5b6f-4e37-9a80-1c2d3e4f5a6b"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, objects, archived=()):
        self._objects = objects
        self._archived = list(archived)
        self.puts = []
        self.listed = []

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=None):
        self.listed.append({"Bucket": Bucket, "Prefix": Prefix})
        found = [{"Key": key} for key in self._archived if key.startswith(Prefix)]
        return {"KeyCount": len(found), "Contents": found}

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


def _install(objects, archived=()):
    fake = _FakeS3(objects, archived)
    clients._s3 = fake
    return fake


def _event(items=None):
    return {
        "requestId": _REQUEST_ID,
        "mode": "archive",
        "actor": {"username": "alice"},
        "execution": {"name": _EXECUTION, "startedAt": "2026-09-17T09:30:00.000Z"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "kind": "personal",
            "name": "alice",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "archive": {
            "bucket": "archive-bkt",
            "root": f"personal/alice/archive/{_REQUEST_ID}/",
            "receiptBucket": "user-bkt",
            "receiptKey": f"alice/archive/{_REQUEST_ID}/receipt.txt",
        },
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)), raising=False)
    return sent


def test_the_plan_key_comes_back_and_the_object_list_does_not():
    """At ARCHIVE_MAX_OBJECTS the plan is tens of megabytes against a 256 KB payload limit, and
    States.DataLimitExceeded escapes every Catch here (States.ALL does not match it and none
    names it) — which on this plane is a run that deleted nothing and told nobody. What rides is
    the pointer, the count and the byte total."""
    fake = _install({"alice/reports/a.csv": 5, "alice/reports/b.csv": 7})

    result = m.handler(_event(), None)

    assert result["copyPlanKey"] == f"archive/{_REQUEST_ID}/copy-plan.json"
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 12
    assert "objects" not in result
    assert len(json.dumps(result).encode()) < 4096
    assert fake.puts[0]["Bucket"] == "admin-bkt"
    # The stamp runs ABOVE this verb, and this state is threaded Payload.$=$ with
    # OutputPath=$.Payload — so the verb's return REPLACES the state, and $.execution survives
    # only because the verb echoes its input. That is a behavioural property where it used to be
    # a structural one, and nothing downstream would fail loudly if it stopped holding: the
    # manifest key would simply refuse as malformed on every archive.
    assert result["execution"] == {"name": _EXECUTION, "startedAt": "2026-09-17T09:30:00.000Z"}


def test_a_refusal_notifies_the_actor_before_the_catch_records_it(_no_real_notifications):
    """The decorator is what makes a refusal a message rather than a silent failed execution;
    the machine's own NotifyFailure then suppresses the duplicate on the TerminalError name."""
    _install({})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "nothing_to_archive"
    assert [user for user, _ in _no_real_notifications] == ["alice"]


def test_a_request_id_that_has_been_used_before_is_refused_before_anything_is_read(
    _no_real_notifications,
):
    """**Found in review.** The request id is browser-supplied and is the WHOLE identity of an
    archive: the plan, the archive prefix, the record and the receipt are keyed on it alone. The
    queue's FIFO dedup window is five minutes against a three-hour ceiling, and this arc's live
    checks submit hand-crafted messages, so a reused id is reachable.

    What it costs is not a duplicate. Two archives mix under one prefix that SPEC-170 will list
    and restore wholesale, the first run's record and receipt are overwritten, and — if the second
    run fails its commit gate — its ROLLBACK deletes the FIRST archive's objects out of a bucket
    with versioning off. That last one is unrecoverable, which is why this refuses rather than
    being left to the producer's conventions.

    **And it tells nobody.** The objects under the prefix are the first run's, and that run
    reports under this id; a second message saying nothing was archived would sit beside its
    "Archived". The run after it is the positive control: the same actor, through the same
    decorator, IS told a refusal that is not silent.
    """
    fake = _install(
        {"alice/reports/a.csv": 5},
        archived=[f"personal/alice/archive/{_REQUEST_ID}/reports/old.csv"],
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)
    silent = list(_no_real_notifications)
    _install({})
    with pytest.raises(TerminalError) as told:
        m.handler(_event(), None)

    assert err.value.reason == "request_id_reused"
    assert fake.puts == []
    assert silent == []
    assert told.value.reason == "nothing_to_archive"
    assert [user for user, _ in _no_real_notifications] == ["alice"]
