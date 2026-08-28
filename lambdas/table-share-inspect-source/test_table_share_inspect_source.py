"""Unit tests for the table-share inspect-source Lambda (SPEC-090).

Pure logic, AWS stubbed: the Glue GetTable and the S3 listing are faked per case.
Asserts the shape rejections, the definition clone, the relative-key listing with
ignore rules, and the caps. Runnable under pytest or directly:
python3 test_table_share_inspect_source.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import table_share_inspect_source as m
from cpcommon import clients, config
from cpcommon.errors import TerminalError

USER_BUCKET = config.USER_SPACE_BUCKET

#: Athena's maximum query string, in bytes. A HARD quota — not adjustable via Service Quotas
#: (docs.aws.amazon.com/athena/latest/ug/service-limits.html, checked 2026-08-10). It is what
#: SHARE_MAX_DEFINITION_BYTES became a sanity check against once the definition left the state.
_ATHENA_QUERY_STRING_QUOTA = 262_144


class _GlueError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeGlue:
    def __init__(self, table=None, error_code=None):
        self._table = table
        self._error_code = error_code

    def get_table(self, DatabaseName, Name):
        if self._error_code:
            raise _GlueError(self._error_code)
        return {"Table": self._table}


class _FakeS3:
    """Just enough of the list paginator for list_data_objects."""

    def __init__(self, contents):
        self._contents = contents

    def get_paginator(self, name):
        contents = self._contents

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "Size": s} for k, s in contents]}

        return _P()


def _table(
    location=f"s3://{USER_BUCKET}/alice/sales/",
    table_type="EXTERNAL_TABLE",
    partition_keys=None,
    parameters=None,
):
    return {
        "Name": "orders",
        "TableType": table_type,
        "PartitionKeys": partition_keys or [],
        "Parameters": {"transient_lastDdlTime": "123", "EXTERNAL": "TRUE", **(parameters or {})},
        "StorageDescriptor": {
            "Location": location,
            "Columns": [
                {"Name": "id", "Type": "bigint"},
                {"Name": "note", "Type": "string", "Comment": "free text"},
            ],
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                "Parameters": {"serialization.format": "1"},
            },
        },
    }


def _plan_writes():
    """Capture what inspect-source writes to the copy plan.

    The object list travels by POINTER now (tscommon.copy_plan) — inline it reached 95% of
    Step Functions' 256 KB state payload at the shipped caps. Tests assert the written
    CONTENT, which is the same list they used to read off the state.
    """
    written = []
    # No local restore: conftest's snapshot covers every shared-layer module since
    # SPEC-153 FR-004, tscommon included.
    m.copy_plan.write = lambda request, objects: (written.append(objects) or "table-share/h/copy-plan.json")
    return written


#: What inspect-source wrote to the definition object, most recent last (SPEC-161 FR-002).
#: Same pointer discipline as the plan above, and the same test consequence: the assertions
#: that used to read ``out["tableDefinition"]`` read the written content instead.
_DEFINITIONS: list = []


def _setup(table=None, objects=None, glue_error=None):
    clients._glue = _FakeGlue(table=table, error_code=glue_error)
    plan = _plan_writes()
    _DEFINITIONS.clear()
    m.copy_plan.write_definition = lambda request, definition: (
        _DEFINITIONS.append(definition) or "table-share/h/definition.json"
    )
    clients._s3 = _FakeS3(objects if objects is not None else [("alice/sales/part-0.parquet", 100)])
    return plan


def _event(recipients=1):
    return {
        "actor": "alice",
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": f"bob{i}", "valid": True} for i in range(recipients)],
    }


def _expect_reason(reason):
    try:
        m.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


def test_flat_external_table_emits_copy_plan():
    plan = _setup(table=_table())
    out = m.handler(_event(), None)
    assert out["location"] == {"bucket": USER_BUCKET, "prefix": "alice/sales/"}
    assert plan[-1] == [{"relKey": "part-0.parquet", "size": 100}]
    assert out["copyPlanKey"] == "table-share/h/copy-plan.json"
    assert out["objectCount"] == 1
    assert "objects" not in out  # the list must NOT ride on the state
    assert out["partitioned"] is False
    # The threaded request context is preserved for the Map.
    assert out["actor"] == "alice" and out["tableName"] == "orders_copy"


def test_clone_carries_definition_and_strips_source_metadata():
    _setup(table=_table(parameters={"classification": "parquet"}))
    m.handler(_event(), None)
    d = _DEFINITIONS[-1]
    assert d["columns"] == [
        {"name": "id", "type": "bigint"},
        {"name": "note", "type": "string", "comment": "free text"},
    ]
    assert d["serde"]["serializationLibrary"].endswith("ParquetHiveSerDe")
    assert d["inputFormat"].endswith("MapredParquetInputFormat")
    assert d["tableType"] == "EXTERNAL_TABLE"
    assert d["tableProperties"] == {"classification": "parquet"}  # bookkeeping keys stripped
    assert "location" not in {k.lower() for k in d}  # LOCATION never travels in the clone


def test_projection_partitioned_table_passes_with_props():
    keys = [{"Name": "year", "Type": "string"}]
    params = {
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": "2020,2026",
        "storage.location.template": f"s3://{USER_BUCKET}/alice/sales/year=${{year}}/",
    }
    _setup(table=_table(partition_keys=keys, parameters=params),
           objects=[("alice/sales/year=2025/part-0.parquet", 10)])
    out = m.handler(_event(), None)
    assert out["partitioned"] is True
    d = _DEFINITIONS[-1]
    assert d["partitionKeys"] == [{"name": "year", "type": "string"}]
    assert d["tableProperties"]["projection.enabled"] == "true"
    assert d["tableProperties"]["storage.location.template"].endswith("year=${year}/")


def test_view_is_rejected():
    _setup(table=_table(table_type="VIRTUAL_VIEW"))
    _expect_reason("source_is_view")


def test_location_outside_data_buckets_is_rejected():
    _setup(table=_table(location="s3://random-bucket/data/"))
    _expect_reason("source_location_unsupported")


def test_missing_source_table_is_terminal():
    _setup(glue_error="EntityNotFoundException")
    _expect_reason("source_not_found")


def test_listing_applies_ignore_rules_and_relative_keys():
    plan = _setup(
        table=_table(),
        objects=[
            ("alice/sales/part-0.parquet", 100),
            ("alice/sales/year=2025/part-1.parquet", 50),
            ("alice/sales/DO_NOT_DELETE.txt", 5),
            ("alice/sales/athenaresults/run.csv", 10),
            ("alice/sales/_temporary/x", 10),
            ("alice/sales/.hidden", 10),
            ("alice/sales/empty.parquet", 0),
            ("alice/sales/", 0),
        ],
    )
    m.handler(_event(), None)
    assert plan[-1] == [
        {"relKey": "part-0.parquet", "size": 100},
        {"relKey": "year=2025/part-1.parquet", "size": 50},
    ]


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
