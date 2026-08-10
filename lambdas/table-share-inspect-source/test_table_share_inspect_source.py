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

import pytest
import table_share_inspect_source as m
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

USER_BUCKET = config.USER_SPACE_BUCKET


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


def _event():
    return {
        "actor": "alice",
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": "bob", "valid": True}],
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


def test_the_definition_travels_by_pointer_and_not_on_the_state():
    """SPEC-161 FR-002 AC1 — the state carries a key; the columns live in the object.

    Asserted on the emitted dict rather than only on the written content, because the
    regression that undoes this spec is putting the value BACK beside the key, which every
    other test here would still pass.
    """
    _setup(table=_table())
    out = m.handler(_event(), None)

    assert out["definitionKey"] == "table-share/h/definition.json"
    assert "tableDefinition" not in out
    assert len(_DEFINITIONS) == 1


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


def test_managed_table_is_rejected():
    _setup(table=_table(table_type="MANAGED_TABLE"))
    _expect_reason("source_not_external")


def test_catalog_partitioned_is_rejected():
    _setup(table=_table(partition_keys=[{"Name": "year", "Type": "string"}]))
    _expect_reason("source_catalog_partitioned")


def test_location_outside_data_buckets_is_rejected():
    _setup(table=_table(location="s3://random-bucket/data/"))
    _expect_reason("source_location_unsupported")


def test_unparseable_location_is_rejected():
    for bad in [None, "", "file:///tmp/x", "s3://bucket-only"]:
        _setup(table=_table(location=bad))
        _expect_reason("source_location_unsupported")


def test_object_level_location_lists_empty():
    # An object-level LOCATION normalizes to a prefix that lists nothing → source_empty.
    _setup(table=_table(location=f"s3://{USER_BUCKET}/alice/sales/file.parquet"), objects=[])
    _expect_reason("source_empty")


def test_missing_source_table_is_terminal():
    _setup(glue_error="EntityNotFoundException")
    _expect_reason("source_not_found")


def test_lf_denied_source_is_terminal():
    _setup(glue_error="AccessDeniedException")
    _expect_reason("source_not_readable")


def test_other_glue_error_is_transient():
    _setup(glue_error="ThrottlingException")
    try:
        m.handler(_event(), None)
    except TransientError:
        return
    raise AssertionError("expected TransientError")


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


def test_empty_source_is_terminal():
    _setup(table=_table(), objects=[])
    _expect_reason("source_empty")


def test_object_count_cap():
    original = m.config.SHARE_MAX_OBJECTS
    m.config.SHARE_MAX_OBJECTS = 2
    try:
        _setup(table=_table(), objects=[(f"alice/sales/p{i}.parquet", 1) for i in range(3)])
        _expect_reason("source_too_large")
    finally:
        m.config.SHARE_MAX_OBJECTS = original


def test_total_bytes_cap():
    original = m.config.SHARE_MAX_TOTAL_BYTES
    m.config.SHARE_MAX_TOTAL_BYTES = 120
    try:
        _setup(table=_table(), objects=[("alice/sales/a.parquet", 100), ("alice/sales/b.parquet", 100)])
        _expect_reason("source_too_large")
    finally:
        m.config.SHARE_MAX_TOTAL_BYTES = original




def test_an_oversized_table_definition_is_a_whole_request_terminal():
    """SPEC-161 FR-002 AC4 — the bound is Athena's, not Step Functions', and it still bites.

    The definition no longer rides on the state, so the 256 KB payload limit is not what sizes
    this any more. What does is Athena's 262,144-byte query-string quota, which is hard: the
    whole definition renders into one CREATE EXTERNAL TABLE, and a statement over it is
    refused. Rejected here, before the write and before any recipient runs, so nobody gets a
    definition object that cannot be rendered.
    """
    wide = _table()
    wide["StorageDescriptor"]["Columns"] = [
        {"Name": f"column_number_{i:04d}", "Type": "string", "Comment": "c" * 255} for i in range(1000)
    ]
    _setup(table=wide)

    with pytest.raises(TerminalError) as excinfo:
        m.handler(_event(), None)

    assert excinfo.value.reason == "source_definition_too_large"
    assert not _DEFINITIONS, "a refused share must leave no definition object behind"


def test_an_ordinary_wide_table_is_still_accepted():
    """The other side of the boundary — the cap must not reject a normal wide table."""
    ordinary = _table()
    ordinary["StorageDescriptor"]["Columns"] = [
        {"Name": f"column_number_{i:03d}", "Type": "string"} for i in range(200)
    ]
    _setup(table=ordinary)

    assert m.handler(_event(), None)["copyPlanKey"]


def test_a_hundred_commented_columns_with_projection_is_accepted():
    """SPEC-161 FR-002 AC3 — the shape the arc exists for, at the old cap's breaking point.

    100 columns each carrying a 255-character comment serialise to roughly 32 KiB, which is
    exactly where SHARE_MAX_DEFINITION_BYTES used to sit. It is the concrete table the spec
    names, and under the old cap it was a coin flip.
    """
    keys = [{"Name": "dt", "Type": "string"}]
    wide = _table(
        partition_keys=keys,
        parameters={
            "projection.enabled": "true",
            "projection.dt.type": "date",
            "projection.dt.range": "2020-01-01,NOW",
            "storage.location.template": f"s3://{USER_BUCKET}/alice/sales/dt=${{dt}}/",
        },
    )
    wide["StorageDescriptor"]["Columns"] = [
        {"Name": f"column_number_{i:03d}", "Type": "string", "Comment": "c" * 255} for i in range(100)
    ]
    _setup(table=wide, objects=[("alice/sales/dt=2025-01-01/part-0.parquet", 10)])

    out = m.handler(_event(), None)

    assert out["definitionKey"] == "table-share/h/definition.json"
    assert len(_DEFINITIONS[-1]["columns"]) == 100
    assert _DEFINITIONS[-1]["tableProperties"]["projection.enabled"] == "true"


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
