"""Unit tests for the file-ops delete-source Lambda.

The only verb in this plane that removes a user's own files, in buckets with versioning off. Every
case here is one where the wrong implementation still looks like it worked: an unconfirmed item
deleted alongside confirmed ones, a refusal taking its siblings down with it, and a confirmed key
that names nothing falling through in silence.

Runnable under pytest or directly: python3 test_file_ops_delete_source.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_delete_source as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from focommon import notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"
_RESULTS_KEY = "file-ops/req-1/run-1/transfer-results.json"


class _FakeS3:
    def __init__(self, objects, heads):
        self._objects = dict(objects)
        self._heads = heads
        self.deleted = []
        self.written = {}

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

        source = self.written if Key in self.written else self._objects
        return {"Body": _Body(source[Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.written[Key] = json.loads(Body)

    def head_object(self, Bucket, Key):
        if Key not in self._heads:
            raise _S3Error("NoSuchKey")
        return {"ETag": self._heads[Key]}

    def delete_objects(self, Bucket, Delete):
        keys = [obj["Key"] for obj in Delete["Objects"]]
        self.deleted.extend(keys)
        return {"Errors": []}


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


def _item(item_key, label, keys):
    return {
        "itemKey": item_key,
        "label": label,
        "kind": "folder",
        "targetName": label,
        "objects": [
            {
                "srcBucket": "user-bkt",
                "srcKey": key,
                "relKey": key.removeprefix(item_key),
                "size": 1,
                "etag": '"e"',
                "destBucket": "user-bkt",
                "destKey": f"alice/out/{label}/{n}",
            }
            for n, key in enumerate(keys)
        ],
        "objectCount": len(keys),
        "totalBytes": len(keys),
    }


def _plan(items, operation="move"):
    return {
        "requestId": "req-1",
        "operation": operation,
        "submittedAt": "2026-08-20T10:00:00+00:00",
        "onConflict": "refuse",
        "actor": "alice",
        "executionArn": _EXECUTION,
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": {"bucket": "user-bkt", "prefix": "alice/out/"},
        "items": items,
        "itemCount": len(items),
        "objectCount": sum(i["objectCount"] for i in items),
        "totalBytes": sum(i["objectCount"] for i in items),
    }


def _install(items, deletable, operation="move", heads=None):
    all_keys = [o["srcKey"] for i in items for o in i["objects"]]
    fake = _FakeS3(
        {
            "file-ops/req-1/plan.json": _plan(items, operation),
            _RESULTS_KEY: {"deletable": deletable, "items": [], "operation": operation},
        },
        heads if heads is not None else dict.fromkeys(all_keys, '"e"'),
    )
    clients._s3 = fake
    return fake


def _event(operation="move"):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "execution": {"arn": _EXECUTION, "name": "run-1"},
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "planKey": "file-ops/req-1/plan.json",
        "transferResultsKey": _RESULTS_KEY,
        "objectCount": None,
    }


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── What is deleted ──────────────────────────────────────────────────────────


def test_only_the_CONFIRMED_items_keys_are_deleted():
    items = [_item("alice/a/", "a", ["alice/a/1"]), _item("alice/b/", "b", ["alice/b/1"])]
    fake = _install(items, ["alice/a/"])

    result = m.handler(_event(), None)

    assert fake.deleted == ["alice/a/"[:-1] + "/1"]
    assert result["deletedCount"] == 1


def test_the_subset_guard_refuses_an_unconfirmed_item():
    """The predicate itself. Kept separate from the wiring test below, which is what proves it
    actually runs — a guard that is correct and unreached protects nothing."""
    with pytest.raises(TerminalError) as caught:
        m._assert_subset({"alice/b/"}, {"alice/a/"})

    assert caught.value.reason == "forbidden"


# ── Conditionality ───────────────────────────────────────────────────────────


def test_a_MOVE_compares_the_ETag_the_PLAN_recorded():
    """The condition protects bytes that were just copied: an object modified between the copy and
    the deletion has a destination copy holding what is no longer the source."""
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    fake = _install(items, ["alice/a/"], heads={"alice/a/1": '"moved-on"'})

    m.handler(_event(), None)

    assert fake.deleted == []
    records = fake.written[_RESULTS_KEY]["deletions"]
    assert records[0]["reason"] == "source_changed"


def test_the_subset_guard_runs_once_per_item_IMMEDIATELY_BEFORE_its_keys_reach_S3(monkeypatch):
    """The compensating guard for the gate's weakened graph property, and this is the test that
    proves it is WIRED rather than merely correct.

    Step Functions has no per-item ``Choice`` over a list, so the machine can only assert that an
    empty ``deletable`` set never reaches this verb. The per-item half is carried here and in the
    collector, and it is worth nothing unless the check sits between the filter and the call.

    Asserted by INTERLEAVING: the recorded sequence must alternate guard-then-delete, so a guard
    hoisted above the loop — which would still pass an "is it called?" test — fails this one.
    """
    items = [_item("alice/a/", "a", ["alice/a/1"]), _item("alice/b/", "b", ["alice/b/1"])]
    fake = _install(items, ["alice/a/", "alice/b/"])
    events = []

    real_assert = m._assert_subset
    monkeypatch.setattr(
        m, "_assert_subset", lambda d, a: (events.append(("guard", sorted(d))), real_assert(d, a))[1]
    )
    real_delete = fake.delete_objects
    fake.delete_objects = lambda Bucket, Delete: (
        events.append(("delete", [o["Key"] for o in Delete["Objects"]])),
        real_delete(Bucket=Bucket, Delete=Delete),
    )[1]

    m._delete_source(_event())

    assert events == [
        ("guard", ["alice/a/"]),
        ("delete", ["alice/a/1"]),
        ("guard", ["alice/b/"]),
        ("delete", ["alice/b/1"]),
    ]
