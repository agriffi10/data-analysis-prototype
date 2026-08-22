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

    result = m._delete_source(_event())

    assert fake.deleted == ["alice/a/"[:-1] + "/1"]
    assert result["deletedCount"] == 1


def test_it_deletes_the_PLANS_keys_rather_than_listing_the_prefix():
    """SPEC-187's Premise 1. This plane's lock serialises its own executions and nothing else — not
    uploads, not create-folder, not the six other control planes — so an object written into the
    folder between the expansion and the commit was never copied.

    A prefix-listing delete would remove it silently and unrecoverably, versioning off. The accepted
    cost is an orphan, which is visible and recoverable where the alternative is neither.
    """
    items = [_item("alice/a/", "a", ["alice/a/1", "alice/a/2"])]
    fake = _install(items, ["alice/a/"], heads={"alice/a/1": '"e"', "alice/a/2": '"e"',
                                                "alice/a/arrived-later": '"e"'})

    m._delete_source(_event())

    assert "alice/a/arrived-later" not in fake.deleted


def test_a_confirmed_item_that_names_NO_plan_item_deletes_nothing_and_is_RECORDED():
    """It never falls through silently: an unmatched key means the two documents disagree, and
    saying so is what makes that visible."""
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    fake = _install(items, ["alice/a/", "alice/ghost/"])

    m._delete_source(_event())

    records = fake.written[_RESULTS_KEY]["deletions"]
    ghost = next(r for r in records if r["itemKey"] == "alice/ghost/")
    assert ghost == {"itemKey": "alice/ghost/", "deleted": 0, "failed": 0,
                     "reason": "source_delete_failed"}
    assert fake.deleted == ["alice/a/1"]


def test_an_item_outside_the_confirmed_set_RAISES_before_reaching_S3():
    """The compensating guard for the gate's weakened graph property, checked at the boto boundary.

    NAMED MUTATION: remove the ``if item_key not in deletable: continue`` skip and this raises
    rather than deleting an unconfirmed item.
    """
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    _install(items, ["alice/a/"])

    with pytest.raises(TerminalError) as caught:
        m._assert_subset({"alice/b/"}, {"alice/a/"})

    assert caught.value.reason == "forbidden"


# ── Per-item isolation ───────────────────────────────────────────────────────


def test_a_REFUSED_item_fails_alone_and_its_siblings_are_still_deleted():
    """Scoped per item, not over the whole list. A whole-list refusal would be the whole-request
    reversion this plane's model forbids — and on a move it runs AFTER the copy, so it would leave
    every item copied and nothing deleted: a full duplicate of the entire selection."""
    items = [
        _item("alice/a/", "a", ["alice/a/athenaresults/r.csv"]),
        _item("alice/b/", "b", ["alice/b/1"]),
    ]
    fake = _install(items, ["alice/a/", "alice/b/"])

    result = m._delete_source(_event())

    assert fake.deleted == ["alice/b/1"]
    records = {r["itemKey"]: r for r in fake.written[_RESULTS_KEY]["deletions"]}
    assert records["alice/a/"]["reason"] == "delete_refused"
    assert records["alice/b/"]["failed"] == 0
    assert result["deletedCount"] == 1


def test_a_nested_marker_survives_and_the_REST_of_the_selection_goes():
    """The marker's whole purpose is to make its own folder undeletable. It costs its item and
    nothing else."""
    items = [
        _item("alice/a/", "a", ["alice/a/DO_NOT_DELETE.txt"]),
        _item("alice/b/", "b", ["alice/b/1"]),
    ]
    fake = _install(items, ["alice/a/", "alice/b/"])

    m._delete_source(_event())

    assert fake.deleted == ["alice/b/1"]
    records = {r["itemKey"]: r for r in fake.written[_RESULTS_KEY]["deletions"]}
    assert records["alice/a/"]["reason"] == "marker_not_deletable"


# ── Conditionality ───────────────────────────────────────────────────────────


def test_a_MOVE_compares_the_ETag_the_PLAN_recorded():
    """The condition protects bytes that were just copied: an object modified between the copy and
    the deletion has a destination copy holding what is no longer the source."""
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    fake = _install(items, ["alice/a/"], heads={"alice/a/1": '"moved-on"'})

    m._delete_source(_event())

    assert fake.deleted == []
    records = fake.written[_RESULTS_KEY]["deletions"]
    assert records[0]["reason"] == "source_changed"


def test_a_DELETE_is_UNCONDITIONAL_deliberately():
    """A move's conditional delete protects bytes that were copied; a delete has no copy, and an
    object modified since the expansion is still one the user asked to remove."""
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    fake = _install(items, ["alice/a/"], operation="delete", heads={"alice/a/1": '"moved-on"'})

    result = m._delete_source(_event("delete"))

    assert fake.deleted == ["alice/a/1"]
    assert result["deletedCount"] == 1


def test_the_per_item_records_travel_by_POINTER_rather_than_on_the_state():
    items = [_item("alice/a/", "a", ["alice/a/1"])]
    fake = _install(items, ["alice/a/"])

    result = m._delete_source(_event())

    assert "deletions" not in result
    assert "deletions" in fake.written[_RESULTS_KEY]
