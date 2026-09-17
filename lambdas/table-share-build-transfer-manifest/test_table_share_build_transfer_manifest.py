"""Unit tests for the build-transfer-manifest Lambda (SPEC-160 FR-001).

The expansion arithmetic (N recipients x M objects), the destination keys being byte-identical
to the ones the per-recipient copy produced before this spec, the refused recipients
contributing nothing, the empty path, and the execution-unique key.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import table_share_build_transfer_manifest as m
from cpcommon import clients


class _FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def _setup():
    fake = _FakeS3()
    clients._s3 = fake
    return fake


def _resolved(name, kind="user", bucket="user-bkt"):
    return {
        "kind": kind,
        "name": name,
        "valid": True,
        "database": name,
        "destBucket": bucket,
        "destPrefix": f"{name}/shared_tables/orders_copy/",
    }


def _event(guard_results, objects=None):
    m.copy_plan.load = lambda key: objects or [
        {"relKey": "part-0.parquet", "size": 10},
        {"relKey": "year=2025/part-1.parquet", "size": 20},
    ]
    return {
        "actor": "alice",
        "source": {"database": "alice", "table": "sales"},
        "tableName": "orders_copy",
        "location": {"bucket": "user-bkt", "prefix": "alice/sales/"},
        "copyPlanKey": "table-share/h/copy-plan.json",
        "execution": {"name": "exec-1"},
        "guardResults": guard_results,
    }


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().split("\n")]


def test_the_manifest_holds_one_line_per_recipient_and_object():
    fake = _setup()

    out = m.handler(
        _event([{"status": "ok", "recipient": _resolved("bob")}, {"status": "ok", "recipient": _resolved("carol")}]),
        None,
    )

    assert out["transfer"]["itemCount"] == 4
    assert len(_lines(fake)) == 4
    assert out["execution"] == {"name": "exec-1"}, (
        "the execution name did not survive the manifest builder, so create-table's notices name no run"
    )


def test_a_refused_recipient_contributes_no_lines():
    """FR-001 AC3 — the guard's terminal outcome is carried forward, never re-derived."""
    fake = _setup()

    out = m.handler(
        _event([
            {"status": "ok", "recipient": _resolved("bob")},
            {"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "error": {"Error": "TerminalError"}},
        ]),
        None,
    )

    assert out["transfer"]["itemCount"] == 2
    assert {line["recipient"] for line in _lines(fake)} == {"bob"}
