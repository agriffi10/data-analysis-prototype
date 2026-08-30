"""Unit tests for the table-builder diff-schema Lambda (SPEC-144).

`compute_diff` is pure and tested directly against column-list pairs; the verb is tested
for the two decisions it owns — the removal opt-in and the no-op short circuit.

Runnable under pytest OR directly: ``python3 test_diff_schema.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "dat-prod-user-space")
os.environ.setdefault("SHARED_SPACE_BUCKET", "dat-prod-shared-space")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import json

import diff_schema as m
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


def _cols(*pairs):
    return [{"name": n, "type": t} for n, t in pairs]


def _event(existing, inferred, *, allow_removals=False, partition_keys=()):
    return {
        "mode": "refresh",
        "actor": "alice",
        "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/", "database": "alice"},
        "tableName": "sales_2026",
        "requestId": "r1",
        "allowRemovals": allow_removals,
        "partitionKeys": [{"name": n} for n in partition_keys],
        "existingColumns": existing,
        "columns": inferred,
    }


def _expect_reason(event, reason):
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── compute_diff: pure classification (FR-001) ───────────────────────────────


def test_an_identical_schema_is_unchanged():
    diff = m.compute_diff(_cols(("a", "string"), ("b", "bigint")), _cols(("a", "string"), ("b", "bigint")), set())

    assert diff == {"changed": False, "added": [], "removed": [], "retyped": [], "unchanged": 2}


def test_all_four_classes_at_once():
    diff = m.compute_diff(
        _cols(("keep", "string"), ("gone", "bigint"), ("widened", "int")),
        _cols(("keep", "string"), ("widened", "bigint"), ("fresh", "double")),
        set(),
    )

    assert diff["added"] == [{"name": "fresh", "type": "double"}]
    assert diff["removed"] == [{"name": "gone", "type": "bigint"}]
    assert diff["retyped"] == [{"name": "widened", "from": "int", "to": "bigint"}]
    assert diff["unchanged"] == 1
    assert diff["changed"] is True


# ── The removal opt-in (FR-003) ──────────────────────────────────────────────


def test_a_removal_without_the_opt_in_is_refused_and_names_the_columns():
    queue = _arm_notifications()
    event = _event(_cols(("keep", "string"), ("gone", "bigint")), _cols(("keep", "string")))

    exc = _expect_reason(event, "columns_removed")

    assert json.loads(exc.tokens["removedNames"]) == ["gone"]
    body = json.loads(queue.calls[0]["MessageBody"])
    assert "gone" in body["message"]
    assert body["link"] == "/query?refreshTable=alice.sales_2026&removed=gone"


# ── Shape + observability ────────────────────────────────────────────────────


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
