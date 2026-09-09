"""Unit tests for the table-share inspect-source Lambda (SPEC-090).

Pure logic, AWS stubbed: the Glue GetTable and the S3 listing are faked per case.
Asserts the shape rejections, the definition clone, the relative-key listing with
ignore rules, and the caps.
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

import table_share_inspect_source as m
from cpcommon import clients, config
from cpcommon.errors import TerminalError
from tscommon import config as ts_config
from tscommon import ddl

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


def _definition_at_cap():
    """A cloned definition sized to exactly the cap, shaped for the WORST render ratio.

    Property-shaped, not comment-shaped, and that choice is the fixture doing the work.
    ``ddl._lit`` backslash-escapes, so an apostrophe costs one byte in the JSON the cap
    measures and two in the rendered statement; what decides the ratio is the per-entry
    overhead it is spread over. A column comment pays ~40 bytes of JSON per entry and renders
    at about 1.7x, while a table property pays ~9 and renders at nearly the full 2x. Sizing
    against the gentler shape would certify a bound the harsher one breaches.

    The length is converged against the PRODUCTION serialisation rather than recomputed here:
    the loop grows the property, clones through the handler, and reads the size back off what
    inspect-source actually wrote. A fixture that measured itself would agree with nothing.

    Args:
      None.

    Returns:
      The ``(definition, value_length)`` pair sitting exactly at the cap.

    Raises:
      AssertionError: If the length does not converge.
    """
    length = ts_config.SHARE_MAX_DEFINITION_BYTES // 2

    def _clone(size):
        _setup(table=_table(parameters={"worst": "\'" * size}))
        m.handler(_event(), None)
        definition = _DEFINITIONS[-1]
        return definition, len(json.dumps(definition, separators=(",", ":")).encode())

    for _ in range(8):
        definition, actual = _clone(length)
        if actual == ts_config.SHARE_MAX_DEFINITION_BYTES:
            return definition, length
        length += ts_config.SHARE_MAX_DEFINITION_BYTES - actual
    raise AssertionError("the at-cap definition did not converge")


def test_an_at_cap_definition_still_renders_under_athenas_query_string_quota():
    """The cap's real budget is Athena's query string, so the cap is computed against it.

    ``SHARE_MAX_DEFINITION_BYTES`` stopped bounding the Step Functions state when the
    definition became a pointer; what it bounds now is the one CREATE EXTERNAL TABLE the
    definition is rendered into, and Athena refuses a query string over 262,144 bytes. A
    definition is measured as JSON and spent as DDL, and the two are not the same size.

    Three things are asserted and the first is what keeps the other two honest. The fixture is
    proved to sit ON the boundary — accepted at the cap, refused one byte past it — because a
    definition that had quietly drifted under the cap would render well inside the quota and
    this test would pass while measuring nothing.

    The headroom is asserted, not just the quota, and that is the difference between a guard
    and a coin flip. Raise the cap to 128 KiB and this same fixture renders to 99.8% of the
    quota, 460 bytes short of it — a number that fits rather than a bound that holds; at 64 KiB
    it lands at 49.8%. The assertion is 60%
    rather than the measured 49.8% deliberately, and the gap is what the guard tolerates: a
    new field in the clone may move the ratio a little and should not redden this. Measured,
    it still passes at 72 KiB and fails at 80 KiB, so the headroom costs a 12% cap raise and
    buys a 25% one.
    """
    definition, length = _definition_at_cap()

    _setup(table=_table(parameters={"worst": "\'" * (length + 1)}))
    _expect_reason("source_definition_too_large")

    rendered = ddl.render_create_external(
        definition, "recipient_db", "orders_copy", f"s3://{USER_BUCKET}/bob/shared/orders_copy/"
    )
    spent = len(rendered.encode())

    assert spent < _ATHENA_QUERY_STRING_QUOTA, (
        f"an at-cap definition renders to {spent} bytes, over Athena's "
        f"{_ATHENA_QUERY_STRING_QUOTA}-byte query string quota"
    )
    assert spent < _ATHENA_QUERY_STRING_QUOTA * 0.6, (
        f"an at-cap definition renders to {100 * spent / _ATHENA_QUERY_STRING_QUOTA:.1f}% of "
        "the quota; the cap is sized to land near half, and this margin is what makes it a "
        "bound rather than a fit"
    )
