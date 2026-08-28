"""Unit tests for the file-ops build-transfer-manifest Lambda.

The last gate before bytes move. The cases that matter are the ones where a wrong implementation
still produces a plausible manifest: a decided item contributing lines, an object travelling without
its size, and — the expensive one — an undeletable item being refused only after it has been copied.

Runnable under pytest or directly: python3 test_file_ops_build_transfer_manifest.py.
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

import file_ops_build_transfer_manifest as m
import pytest
from cpcommon import clients
from focommon import notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"


class _FakeS3:
    def __init__(self, plan):
        self._plan = plan
        self.puts = []

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

        return {"Body": _Body(self._plan)}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts.append({"Key": Key, "Body": Body})


def _item(item_key, label, keys, size=7):
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
                "size": size,
                "etag": '"e"',
                "destBucket": "user-bkt",
                "destKey": f"alice/out/{label}/{n}",
            }
            for n, key in enumerate(keys)
        ],
        "objectCount": len(keys),
        "totalBytes": size * len(keys),
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
        "totalBytes": sum(i["totalBytes"] for i in items),
    }


def _event(items, operation="move", outcomes=None):
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
    }


def _install(items, operation="move"):
    fake = _FakeS3(_plan(items, operation))
    clients._s3 = fake
    return fake


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().split("\n")]


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── What gets a line ─────────────────────────────────────────────────────────


def test_a_cleared_item_contributes_one_line_per_object():
    items = [_item("alice/a/", "a", ["alice/a/1", "alice/a/2"])]
    fake = _install(items)

    result = m._build_transfer_manifest(_event(items))

    assert result["transfer"]["itemCount"] == 2
    assert len(_lines(fake)) == 2


def test_an_item_with_ANY_other_outcome_contributes_ZERO_lines():
    """Its terminal was decided before this verb ran and nothing here may overwrite it."""
    items = [_item("alice/a/", "a", ["alice/a/1"]), _item("alice/b/", "b", ["alice/b/1"])]
    fake = _install(items)
    outcomes = [
        {"itemKey": "alice/a/", "label": "a", "outcome": "conflict", "reason": "destination_occupied"},
        {"itemKey": "alice/b/", "label": "b", "outcome": "cleared"},
    ]

    result = m._build_transfer_manifest(_event(items, outcomes=outcomes))

    assert [line["itemKey"] for line in _lines(fake)] == ["alice/b/"]
    assert result["transfer"]["itemCount"] == 1


# ── The deletability check, and WHERE it runs ────────────────────────────────


def test_an_UNDELETABLE_item_is_refused_HERE_having_copied_nothing():
    """THE placement finding. A personal folder holding a nested ``athenaresults/`` passes the front
    door — the browser's rule is root-anchored there — and expands with those objects in the plan.

    Refused after the copy instead, the item would be fully duplicated in the destination and
    undeletable at the source: a state the user cannot resolve through this plane at all. Refused
    here, it contributes no lines and nothing moved.
    """
    items = [_item("alice/a/", "a", ["alice/a/athenaresults/r.csv"])]
    fake = _install(items)

    result = m._build_transfer_manifest(_event(items))

    assert fake.puts == []
    assert result["outcomes"][0]["outcome"] == "protected"
    assert result["outcomes"][0]["reason"] == "delete_refused"


# ── What the collector needs back ────────────────────────────────────────────
