"""Unit tests for the build-transfer-manifest Lambda (SPEC-160 FR-001).

The expansion arithmetic (N recipients x M objects), the destination keys being byte-identical
to the ones the per-recipient copy produced before this spec, the refused recipients
contributing nothing, the empty path, and the execution-unique key. Runnable under pytest or
directly: python3 test_table_share_build_transfer_manifest.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_build_transfer_manifest as m
from cpcommon import clients
from tscommon import copy_plan


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


def test_the_destination_is_the_key_the_old_copy_produced():
    """FR-001 AC2 — the destination is the recipient's resolved prefix plus the relative key,
    which is exactly what tscommon.copy concatenated per recipient before this spec."""
    fake = _setup()
    m.handler(_event([{"status": "ok", "recipient": _resolved("bob")}]), None)

    assert [(line["srcKey"], line["destKey"]) for line in _lines(fake)] == [
        ("alice/sales/part-0.parquet", "bob/shared_tables/orders_copy/part-0.parquet"),
        (
            "alice/sales/year=2025/part-1.parquet",
            "bob/shared_tables/orders_copy/year=2025/part-1.parquet",
        ),
    ]


def test_every_line_carries_its_recipient_kind_and_buckets():
    fake = _setup()
    m.handler(_event([{"status": "ok", "recipient": _resolved("team", kind="space", bucket="shared-bkt")}]), None)

    line = _lines(fake)[0]
    assert line["recipient"] == "team"
    assert line["kind"] == "space"
    assert line["srcBucket"] == "user-bkt"
    assert line["destBucket"] == "shared-bkt"
    assert line["size"] == 10


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


def test_no_accepted_recipient_writes_no_manifest():
    """FR-001 AC4 — itemCount 0, nothing written, and the Choice skips the Map."""
    fake = _setup()
    m.copy_plan.load = lambda key: (_ for _ in ()).throw(AssertionError("the plan was read"))

    out = m.handler(
        _event([{"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "error": {}}]),
        None,
    )

    assert out["transfer"]["itemCount"] == 0
    assert out["transfer"]["manifestKey"] == ""
    assert fake.puts == []


def test_the_manifest_key_is_execution_unique():
    """FR-001 AC5 — NOT beside copy-plan.json on the bare digest.

    Two executions of the same request accept different recipients, so a shared key would let
    the later one's manifest be copied by the earlier one's Map Run.
    """
    fake = _setup()
    event = _event([{"status": "ok", "recipient": _resolved("bob")}])

    out = m.handler(event, None)

    digest = copy_plan.request_digest(event)
    assert out["transfer"]["manifestKey"] == f"table-share/{digest}/exec-1/transfer-manifest.jsonl"
    assert fake.puts[0]["Key"] == out["transfer"]["manifestKey"]
    assert out["transfer"]["manifestKey"] != copy_plan.plan_key(event)

    second = m.handler({**event, "execution": {"name": "exec-2"}}, None)
    assert second["transfer"]["manifestKey"] != out["transfer"]["manifestKey"]


def test_the_results_prefix_is_execution_unique_too():
    _setup()
    event = _event([{"status": "ok", "recipient": _resolved("bob")}])
    out = m.handler(event, None)
    digest = copy_plan.request_digest(event)
    assert out["transfer"]["resultsPrefix"] == f"table-share/{digest}/exec-1/results"


def test_an_unstamped_execution_refuses_rather_than_sharing_a_key():
    _setup()
    with pytest.raises(ValueError):
        m.handler({**_event([{"status": "ok", "recipient": _resolved("bob")}]), "execution": {}}, None)


def test_the_request_is_threaded_onward_unchanged():
    _setup()
    event = _event([{"status": "ok", "recipient": _resolved("bob")}])
    out = m.handler(event, None)
    assert {k: out[k] for k in event} == event


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
