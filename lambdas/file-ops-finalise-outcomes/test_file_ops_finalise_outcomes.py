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

    result = m.handler(_event([_cleared()], operation=operation), None)

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

    result = m.handler(_event(arrived), None)

    for record in result["outcomes"]:
        assert record["outcome"] in outcomes.TERMINALS
        assert record["outcome"] not in outcomes.GATE_VERDICTS


# ── The duplicate, and the state no earlier code describes ───────────────────


@pytest.mark.parametrize("reason", ["source_changed", "source_delete_failed", "delete_refused"])
def test_a_copied_item_whose_SOURCE_SURVIVED_is_a_duplicate(reason):
    """Not a success and not a failure: the user now holds the data in two places, and they have to
    be told, because only they can decide which copy to keep."""
    _install(deletions=[{"itemKey": "alice/a/", "deleted": 0, "failed": 2, "reason": reason}])

    result = m.handler(_event([_cleared()]), None)

    assert result["outcomes"][0]["outcome"] == "duplicate"
    assert result["outcomes"][0]["reason"] == reason


