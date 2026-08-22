"""Unit tests for the file-ops finalise-outcomes Lambda.

This verb is what stops a gate verdict reaching a terminal, so the cases that matter are the ones
where an item ends the run wearing the wrong word: ``cleared`` surviving to the notification, a
``delete`` that removed nothing reported as a duplicate, and a copied item whose source survived
reported as a success.

Runnable under pytest or directly: python3 test_file_ops_finalise_outcomes.py.
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

import file_ops_finalise_outcomes as m
import pytest
from cpcommon import clients
from focommon import notify, outcomes

_RESULTS_KEY = "file-ops/req-1/run-1/transfer-results.json"


class _FakeS3:
    def __init__(self, results):
        self._results = results

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

        return {"Body": _Body(self._results)}


def _install(deletions=None, items=None):
    fake = _FakeS3({"deletable": [], "items": items or [], "deletions": deletions or []})
    clients._s3 = fake
    return fake


def _event(arrived, operation="move", results_key=_RESULTS_KEY):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "source": {
            "kind": "personal",
            "name": "alice",
            "bucket": "user-bkt",
            "root": "alice/",
            "items": [{"key": "alice/a/", "kind": "folder", "targetName": "a"}],
        },
        "destination": {"kind": "shared", "name": "sales", "prefix": "sales/out/"},
        "outcomes": arrived,
        **({"transferResultsKey": results_key} if results_key else {}),
    }


def _cleared(item_key="alice/a/", label="a"):
    return {"itemKey": item_key, "label": label, "outcome": "cleared"}


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── No gate verdict reaches a terminal ───────────────────────────────────────


@pytest.mark.parametrize(
    "operation,expected", [("move", "moved"), ("copy", "copied"), ("delete", "deleted")]
)
def test_a_committed_item_becomes_its_operations_terminal_success(operation, expected):
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 3, "failed": 0, "reason": ""}])

    result = m._finalise_outcomes(_event([_cleared()], operation=operation))

    assert result["outcomes"][0]["outcome"] == expected


def test_NO_gate_verdict_survives_to_a_terminal():
    """``cleared`` means "may proceed". An item still wearing it when the machine finishes is
    indistinguishable from "moved successfully" to the producer that words the notification, and
    that difference is the whole per-item model.

    Asserted over every outcome the run ends with, not just the one this fixture exercises.
    """
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 1, "failed": 0, "reason": ""}])
    arrived = [
        _cleared(),
        {"itemKey": "alice/p/", "label": "p", "outcome": "protected", "reason": "archive_read_only"},
        {"itemKey": "alice/n/", "label": "n", "outcome": "noop"},
    ]

    result = m._finalise_outcomes(_event(arrived))

    for record in result["outcomes"]:
        assert record["outcome"] in outcomes.TERMINALS
        assert record["outcome"] not in outcomes.GATE_VERDICTS


def test_a_COPY_finalises_without_any_deletion_having_run():
    """``delete-source`` does not run on a copy — the graph proves there is no path — which is
    exactly why this verb exists: without it every successful item on a copy run would arrive at the
    terminal still labelled ``cleared``."""
    clients._s3 = _FakeS3({"deletable": [], "items": []})

    result = m._finalise_outcomes(_event([_cleared()], operation="copy", results_key=None))

    assert result["outcomes"][0]["outcome"] == "copied"


# ── The duplicate, and the state no earlier code describes ───────────────────


@pytest.mark.parametrize("reason", ["source_changed", "source_delete_failed", "delete_refused"])
def test_a_copied_item_whose_SOURCE_SURVIVED_is_a_duplicate(reason):
    """Not a success and not a failure: the user now holds the data in two places, and they have to
    be told, because only they can decide which copy to keep."""
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 0, "failed": 2, "reason": reason}])

    result = m._finalise_outcomes(_event([_cleared()]))

    assert result["outcomes"][0]["outcome"] == "duplicate"
    assert result["outcomes"][0]["reason"] == reason


def test_a_DELETE_that_removed_nothing_is_NOT_a_duplicate():
    """Nothing was copied, so "you now have it twice" would be a false sentence — and ``copy_failed``
    names a copy that never happened. One state, one code."""
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 0, "failed": 1,
                         "reason": "delete_refused"}])

    result = m._finalise_outcomes(_event([_cleared()], operation="delete"))

    assert result["outcomes"][0]["outcome"] == "delete_failed"
    assert result["outcomes"][0]["reason"] == "delete_refused"


def test_an_unrecognised_deletion_reason_still_produces_a_WORDABLE_outcome():
    """A record nothing can word is a notification the user never gets."""
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 0, "failed": 1, "reason": ""}])

    result = m._finalise_outcomes(_event([_cleared()]))

    assert result["outcomes"][0]["outcome"] == "duplicate"
    assert result["outcomes"][0]["reason"] == "source_delete_failed"


# ── The terminal's payload ───────────────────────────────────────────────────


def test_the_terminal_carries_BOTH_spaces_the_prefix_and_every_items_targetName():
    """The full set is what a re-submit has to rebuild into a valid request: the SOURCE space is not
    derivable from an absolute key, and a rename's ``targetName`` has no other source."""
    _install(
        deletions=[{"itemKey": "alice/a/", "deleted": 1, "failed": 0, "reason": ""}],
        items=[{"itemKey": "alice/a/", "objects": 3, "failed": 0}],
    )

    summary = m._finalise_outcomes(_event([_cleared()]))["summary"]

    assert summary["operation"] == "move"
    assert summary["source"] == {"kind": "personal", "name": "alice"}
    assert summary["destination"] == {"kind": "shared", "name": "sales", "prefix": "sales/out/"}
    assert summary["items"] == [{"itemKey": "alice/a/", "kind": "folder", "targetName": "a"}]
    assert summary["counts"] == [{"itemKey": "alice/a/", "objects": 3, "failed": 0}]


def test_a_run_where_EVERY_item_was_refused_still_reaches_the_ordinary_terminal():
    """"Nothing could be done" is a result, not a failure of the request."""
    clients._s3 = _FakeS3({"deletable": [], "items": []})
    arrived = [
        {"itemKey": "alice/a/", "label": "a", "outcome": "conflict", "reason": "destination_occupied"},
        {"itemKey": "alice/b/", "label": "b", "outcome": "protected", "reason": "archive_read_only"},
    ]

    result = m._finalise_outcomes(_event(arrived, results_key=None))

    assert result["outcomes"] == arrived
    assert "summary" in result


def test_the_ORDER_a_person_reads_is_preserved():
    """The list is what the notification is built from, and an item must not move to the end of it
    because its outcome was decided last."""
    _install(deletions=[{"itemKey": "alice/b/", "deleted": 1, "failed": 0, "reason": ""}])
    arrived = [
        {"itemKey": "alice/a/", "label": "a", "outcome": "noop"},
        _cleared("alice/b/", "b"),
        {"itemKey": "alice/c/", "label": "c", "outcome": "source_empty", "reason": "source_empty"},
    ]

    result = m._finalise_outcomes(_event(arrived))

    assert [r["itemKey"] for r in result["outcomes"]] == ["alice/a/", "alice/b/", "alice/c/"]
