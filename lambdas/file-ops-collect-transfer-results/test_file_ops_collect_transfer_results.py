"""Unit tests for the file-ops collect-transfer-results Lambda.

This verb decides which items may have their source REMOVED, so every case here is one where the
wrong implementation still reports success: a FAILED-only read over a batch that succeeded while
carrying failures, a skip branch recognised by the absence of an export, and an item with one failed
object still landing in the deletable set.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_collect_transfer_results as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from focommon import notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"


class _FakeS3:
    """Serves the plan and the Map Run export, and records the results document written back."""

    def __init__(self, plan, objects=None):
        self._objects = {"file-ops/req-1/plan.json": plan, **(objects or {})}
        self.written = {}

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

        if Key in self.written:
            return {"Body": _Body(self.written[Key])}
        return {"Body": _Body(self._objects[Key])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.written[Key] = json.loads(Body)


def _item(item_key, label, count):
    return {
        "itemKey": item_key,
        "label": label,
        "kind": "folder",
        "targetName": label,
        "objects": [
            {
                "srcBucket": "user-bkt",
                "srcKey": f"{item_key}{n}",
                "relKey": str(n),
                "size": 1,
                "etag": '"e"',
                "destBucket": "user-bkt",
                "destKey": f"alice/out/{label}/{n}",
            }
            for n in range(count)
        ],
        "objectCount": count,
        "totalBytes": count,
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


def _export(records):
    """Builds a Map Run export: a run manifest plus one SUCCEEDED result file."""
    return {
        "run-manifest.json": {"ResultFiles": {"SUCCEEDED": [{"Key": "succeeded_0.json"}]}},
        "succeeded_0.json": records,
    }


def _event(items, operation="move", outcomes=None, transfer=None, map_run=True):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "execution": {"arn": _EXECUTION, "name": "run-1"},
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "destination": {"bucket": "user-bkt", "root": "alice/", "prefix": "alice/out/"},
        "planKey": "file-ops/req-1/plan.json",
        "objectCount": None,
        "outcomes": outcomes
        if outcomes is not None
        else [
            {"itemKey": i["itemKey"], "label": i["label"], "outcome": "cleared"} for i in items
        ],
        "transfer": transfer,
        **(
            {"mapRun": {"ResultWriterDetails": {"Bucket": "admin-bkt", "Key": "run-manifest.json"}}}
            if map_run
            else {}
        ),
    }


def _install(plan, objects=None):
    fake = _FakeS3(plan, objects)
    clients._s3 = fake
    return fake


def _transfer(items, operation="move"):
    total = sum(i["objectCount"] for i in items)
    return {
        "manifestBucket": "admin-bkt",
        "manifestKey": "file-ops/req-1/run-1/transfer-manifest.jsonl",
        "resultsBucket": "admin-bkt",
        "resultsPrefix": "file-ops/req-1/results",
        "itemCount": 0 if operation == "delete" else total,
        "itemLines": [
            {"itemKey": i["itemKey"], "lines": 0 if operation == "delete" else i["objectCount"]}
            for i in items
        ],
    }


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


def _results(fake):
    return next(v for k, v in fake.written.items() if k.endswith("transfer-results.json"))


# ── The gate ─────────────────────────────────────────────────────────────────


def test_an_item_whose_objects_ALL_copied_is_deletable():
    items = [_item("alice/a/", "a", 3)]
    fake = _install(_plan(items), _export([{"Output": json.dumps({"copied": 3, "failures": []})}]))

    result = m.handler(_event(items, transfer=_transfer(items)), None)

    assert result["deletableCount"] == 1
    assert _results(fake)["deletable"] == ["alice/a/"]


def test_an_item_with_ONE_failed_object_is_NOT_deletable():
    """THE per-item property, and the one the graph walk deliberately does not claim to prove.

    Step Functions has no per-item ``Choice`` over a list, so the commit gate can only assert that an
    EMPTY deletable set cannot reach the deletion. This test and delete-source's subset assertion are
    the two layers that carry the per-item half.

    NAMED MUTATION: delete the ``if failed or short`` branch below the fixture's reach and this test
    goes red on its own.
    """
    items = [_item("alice/a/", "a", 3)]
    fake = _install(
        _plan(items),
        _export([
            {"Output": json.dumps({
                "copied": 2,
                "failures": [{"itemKey": "alice/a/", "reason": "copy_failed"}],
            })}
        ]),
    )

    result = m.handler(_event(items, transfer=_transfer(items)), None)

    assert result["deletableCount"] == 0
    assert _results(fake)["deletable"] == []
    assert result["outcomes"][0]["outcome"] == "copy_failed"


# ── The skip branch ──────────────────────────────────────────────────────────


def test_a_MOVE_with_no_export_RAISES_rather_than_marking_everything_deletable():
    """The skip branch is recognised POSITIVELY, by the operation, never by the absence of a Map
    output.

    Implemented the natural way — "no mapRun, therefore the skip branch" — a move that arrived here
    without an export would mark every cleared item deletable and the next state would delete a
    source nothing had copied.
    """
    items = [_item("alice/a/", "a", 3)]
    _install(_plan(items))

    with pytest.raises(TerminalError) as caught:
        m.handler(_event(items, transfer=None, map_run=False), None)

    assert caught.value.reason == "transfer_results_unreadable"


