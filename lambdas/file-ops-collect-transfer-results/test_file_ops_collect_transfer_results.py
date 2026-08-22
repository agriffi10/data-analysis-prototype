"""Unit tests for the file-ops collect-transfer-results Lambda.

This verb decides which items may have their source REMOVED, so every case here is one where the
wrong implementation still reports success: a FAILED-only read over a batch that succeeded while
carrying failures, a skip branch recognised by the absence of an export, and an item with one failed
object still landing in the deletable set.

Runnable under pytest or directly: python3 test_file_ops_collect_transfer_results.py.
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

    result = m._collect_transfer_results(_event(items, transfer=_transfer(items)))

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

    result = m._collect_transfer_results(_event(items, transfer=_transfer(items)))

    assert result["deletableCount"] == 0
    assert _results(fake)["deletable"] == []
    assert result["outcomes"][0]["outcome"] == "copy_failed"


def test_one_item_failing_leaves_its_SIBLING_deletable():
    """Per-item partial execution: a select-all move must still move what it can."""
    items = [_item("alice/a/", "a", 2), _item("alice/b/", "b", 2)]
    fake = _install(
        _plan(items),
        _export([
            {"Output": json.dumps({
                "copied": 3,
                "failures": [{"itemKey": "alice/a/", "reason": "copy_failed"}],
            })}
        ]),
    )

    result = m._collect_transfer_results(_event(items, transfer=_transfer(items)))

    assert _results(fake)["deletable"] == ["alice/b/"]
    assert result["deletableCount"] == 1


def test_a_SUCCEEDED_batch_carrying_failures_is_still_attributed():
    """Step Functions files a child by its EXECUTION STATUS, not by what its payload says, and the
    batch copier deliberately succeeds while carrying per-item failures.

    A collector reading only ``FAILED_n.json`` would report universal success — and here that
    success is what authorises a DELETION.
    """
    items = [_item("alice/a/", "a", 2)]
    _install(
        _plan(items),
        _export([
            {"Output": json.dumps({
                "copied": 1,
                "failures": [{"itemKey": "alice/a/", "reason": "copy_failed"}],
            })}
        ]),
    )

    result = m._collect_transfer_results(_event(items, transfer=_transfer(items)))

    assert result["deletableCount"] == 0


def test_an_export_SHORT_of_the_manifest_fails_the_WHOLE_request():
    """An omitted line is unattributable — it belongs to an item nobody can name — so it is a
    property of the run rather than of an item."""
    items = [_item("alice/a/", "a", 3)]
    _install(_plan(items), _export([{"Output": json.dumps({"copied": 2, "failures": []})}]))

    with pytest.raises(TerminalError) as caught:
        m._collect_transfer_results(_event(items, transfer=_transfer(items)))

    assert caught.value.reason == "transfer_results_unreadable"


def test_an_item_whose_manifest_lines_DISAGREE_with_the_plan_is_not_deletable():
    """The second shortfall that keeps an item out: the copy reported no failure, but fewer lines
    were written for it than the plan holds objects, so something was never offered to the Map.

    **The two sides of this check must come from different places or it proves nothing.** The plan's
    per-item ``objectCount`` is one side; the other is what ``build-transfer-manifest`` actually
    WROTE, counted from the lines themselves. An earlier version reported the plan's own
    ``objectCount`` back as the line count, which made the comparison a tautology no fixture could
    fail honestly — the input below was one the builder could not emit.

    The divergence this catches is real and unguarded elsewhere: ``plan.load`` sums actual objects
    against the TOP-LEVEL count only, never per item, so an item whose ``objectCount`` disagrees with
    its own object list passes the plan reader.
    """
    items = [_item("alice/a/", "a", 3)]
    # An item whose recorded count exceeds its actual objects: the plan reader accepts it (its own
    # check is the top-level total), and the builder writes one line per real object.
    items[0]["objectCount"] = 4
    plan = _plan(items)
    plan["objectCount"] = 3
    transfer = _transfer(items)
    transfer["itemCount"] = 3
    transfer["itemLines"] = [{"itemKey": "alice/a/", "lines": 3}]
    _install(plan, _export([{"Output": json.dumps({"copied": 3, "failures": []})}]))

    result = m._collect_transfer_results(_event(items, transfer=transfer))

    assert result["deletableCount"] == 0
    assert result["outcomes"][0]["outcome"] == "copy_failed"


# ── The skip branch ──────────────────────────────────────────────────────────


def test_a_DELETE_reaches_the_gate_through_the_skip_branch_with_every_item_deletable():
    """Without this the delete operation reaches the fail-closed Default and removes nothing, which
    is the whole operation silently not working."""
    items = [_item("alice/a/", "a", 3), _item("alice/b/", "b", 1)]
    fake = _install(_plan(items, "delete"))

    result = m._collect_transfer_results(
        _event(items, operation="delete", transfer=_transfer(items, "delete"), map_run=False)
    )

    assert result["deletableCount"] == 2
    assert _results(fake)["deletable"] == ["alice/a/", "alice/b/"]


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
        m._collect_transfer_results(_event(items, transfer=None, map_run=False))

    assert caught.value.reason == "transfer_results_unreadable"


def test_a_run_where_NOTHING_was_cleared_is_an_ordinary_empty_result():
    """Every item refused upstream is a result, not a fault: no transfer was reported and none was
    expected."""
    items = [_item("alice/a/", "a", 2)]
    fake = _install(_plan(items))
    outcomes = [{"itemKey": "alice/a/", "label": "a", "outcome": "conflict", "reason": "destination_occupied"}]

    result = m._collect_transfer_results(
        _event(items, outcomes=outcomes, transfer=None, map_run=False)
    )

    assert result["deletableCount"] == 0
    assert _results(fake)["deletable"] == []
    assert result["outcomes"] == outcomes


# ── What rides, and what does not ────────────────────────────────────────────


def test_the_deletable_list_and_the_counts_travel_by_POINTER():
    """At the selection cap these are over the 256 KB state limit, and the overflow would land on
    THIS verb's result — after the copy — where ``States.DataLimitExceeded`` escapes every Catch."""
    items = [_item("alice/a/", "a", 2)]
    _install(_plan(items), _export([{"Output": json.dumps({"copied": 2, "failures": []})}]))

    result = m._collect_transfer_results(_event(items, transfer=_transfer(items)))

    assert "deletable" not in result
    assert isinstance(result["deletableCount"], int)
    assert result["transferResultsKey"].endswith("transfer-results.json")


def test_the_outcome_list_is_carried_FORWARD_rather_than_recreated():
    """Three verbs before this one decided items, and each of those records has to reach the
    notification."""
    items = [_item("alice/a/", "a", 2)]
    _install(_plan(items), _export([{"Output": json.dumps({"copied": 2, "failures": []})}]))
    arrived = [
        {"itemKey": "alice/p/", "label": "p", "outcome": "protected", "reason": "archive_read_only"},
        {"itemKey": "alice/a/", "label": "a", "outcome": "cleared"},
    ]

    result = m._collect_transfer_results(_event(items, outcomes=arrived, transfer=_transfer(items)))

    assert result["outcomes"][0] == arrived[0]
    assert len(result["outcomes"]) == 2
