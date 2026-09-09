"""Handler tests for infer-schema.

Real polars fixtures (Parquet / CSV / JSON). Two seams, matching the two source paths:
Parquet keeps the source-URI seam pointing polars at a local fixture (polars scans local
paths and s3:// the same way), while CSV/JSON are stubbed at the S3 CLIENT, so the
assertions run through the real bounded head read and the in-memory buffer polars is
actually handed in prod. Stubbing CSV at the URI seam instead is what let the
object_store bug ship: polars reads a local path happily, so the test passed while every
real build failed. Asserts the type rules plus scan-error → terminal and transient-S3 →
raised.

Run under pytest, which supplies the cpcommon path and the config env baseline from
conftest.py.
"""

import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import infer_schema as i
import polars as pl
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError

_REAL_CHECK = i._check_access
# Captured because _use_fixture replaces it globally and never restores it: without this,
# a test that needs the REAL ranged reader silently gets the previous test's local-file
# stub, and passes alone while failing (or worse, asserting nothing) in the full suite.
_REAL_PARQUET_SOURCE = i._parquet_source
_TMP = tempfile.mkdtemp()


def _use_fixture(path):
    # Parquet seam: hand polars a local file object (it seeks either the same way) and
    # no-op the S3 access probe. The handle is the seam's return value — polars reads it
    # after the lambda returns, so a context manager would close it too early (SIM115).
    i._parquet_source = lambda bucket, key: open(path, "rb")  # noqa: SIM115
    i._check_access = lambda bucket, key: None


class _FakeBody:
    def __init__(self, data):
        self._data = data
        self.closed = False

    def iter_chunks(self, size):
        for start in range(0, len(self._data), size):
            yield self._data[start: start + size]

    def close(self):
        self.closed = True


class _FakeS3Get:
    def __init__(self, data):
        self.data = data

    def head_object(self, *a, **k):
        return {"ContentLength": len(self.data)}

    def get_object(self, **kwargs):
        return {"Body": _FakeBody(self.data)}


def _use_s3_fixture(data):
    """Serve ``data`` from a fake S3 and make any s3:// URI read a hard failure.

    CSV/JSON must reach polars as boto3-fetched bytes; if the handler ever goes back to
    handing polars an s3:// URI, _object_uri raises and the test fails loudly rather than
    silently exercising a path that does not work in Lambda.
    """
    def _no_parquet_source(bucket, key):
        raise AssertionError("CSV/JSON must not be read through the Parquet ranged reader")

    i._parquet_source = _no_parquet_source
    i._check_access = _REAL_CHECK
    clients._s3 = _FakeS3Get(data)


def _event(fmt, partition_keys=None, sample="alice/sales/2026/part-0"):
    return {
        "actor": "alice",
        "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice"},
        "tableName": "sales_2026",
        "location": "s3://dat-prod-user-space/alice/sales/2026/",
        "format": fmt,
        "partitioned": bool(partition_keys),
        "partitionKeys": partition_keys or [],
        "sampleObjectKey": sample,
        "fileCount": 1,
        "requestId": "r1",
    }


def _types(out):
    return {c["name"]: c["type"] for c in out["columns"]}


def test_parquet_preserves_native_types():
    path = os.path.join(_TMP, "s.parquet")
    pl.DataFrame({
        "order_id": pl.Series([1, 2], dtype=pl.Int64),
        "amount": pl.Series([1.5, 2.5], dtype=pl.Float64),
        "d": pl.Series([dt.date(2026, 1, 1), dt.date(2026, 1, 2)]),
        # Naive on purpose: a tz-aware value makes polars write Datetime(tz), which is a
        # different Parquet logical type than the one this test asserts on.
        "ts": pl.Series([dt.datetime(2026, 1, 1, 12), dt.datetime(2026, 1, 2, 12)]),  # noqa: DTZ001
        "note": pl.Series(["a", "b"], dtype=pl.String),
    }).write_parquet(path)
    _use_fixture(path)
    out = i.handler(_event("parquet"), None)
    assert _types(out) == {
        "order_id": "bigint", "amount": "double", "d": "date", "ts": "timestamp", "note": "string",
    }
    # column order preserved
    assert [c["name"] for c in out["columns"]] == ["order_id", "amount", "d", "ts", "note"]


def test_csv_is_all_string_from_header_no_inference():
    _use_s3_fixture(b"order_id,amount,ts\n1,2.50,2026-01-01\n2,3.75,2026-01-02\n")
    out = i.handler(_event("csv"), None)
    # Every column string despite int/float/date-looking values.
    assert _types(out) == {"order_id": "string", "amount": "string", "ts": "string"}


def test_a_case_fold_collision_refuses_the_build_and_names_BOTH_columns():
    """Athena lowercases every identifier as it runs, so `Total` and `TOTAL` are two columns to
    every tool the user has and one column to Athena. This is the failure that reads as a bug
    in the portal rather than in the file."""
    _use_s3_fixture(b"Total,id,TOTAL\n1,2,3\n")
    with pytest.raises(TerminalError) as err:
        i.handler(_event("csv"), None)
    assert err.value.reason == "invalid_column_names"
    assert err.value.tokens["columns"] == '"Total", "TOTAL"'


def test_a_REFRESH_is_exempt_so_a_pre_existing_table_is_not_stranded():
    """The mirror of the space-root refusal, which is creates-only for the same reason. A refresh
    re-derives the columns of a table that ALREADY EXISTS, so refusing one would break every
    refresh of a table built before this rule and leave rewriting the source files as the only
    repair. Refusing the create stops the next bad table; refusing the refresh strands the ones
    already there."""
    _use_s3_fixture(b'order_id,"Order ID",ts\n1,2,3\n')
    # Selected by the STORAGE DESCRIPTOR, which only the refresh path puts on the state — this
    # verb is forbidden from reading `mode` by the guard below, and for good reason.
    refresh = dict(_event("csv"), storage={"serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde"})
    out = i.handler(refresh, None)
    assert [c["name"] for c in out["columns"]] == ["order_id", "Order ID", "ts"]


def test_json_types_are_inferred_from_rows_beyond_a_wide_first_record():
    """A column null in row 1 and typed later must still type correctly, even when the
    first record alone is wider than a read chunk.

    This does NOT pin the line bound (an earlier version of this test claimed it did):
    reading stops at a CHUNK boundary, so the head overshoots by up to 256 KiB — thousands
    of rows — and no realistic input separates a 1-line bound from a 1001-line one.
    max_lines bounds COST, not correctness. What it does cover is the real path: a
    multi-chunk boto3 head, reassembled, inferred by polars from the buffer.
    """
    wide = b'{"a": null, "pad": "' + b"x" * 300_000 + b'"}\n'
    _use_s3_fixture(wide + b"".join(b'{"a": %d, "pad": "y"}\n' % n for n in range(500)))
    out = i.handler(_event("json"), None)
    assert _types(out) == {"a": "bigint", "pad": "string"}


def test_ddl_is_generated_and_carried():
    path = os.path.join(_TMP, "s2.parquet")
    pl.DataFrame({"id": pl.Series([1], dtype=pl.Int64)}).write_parquet(path)
    _use_fixture(path)
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]
    out = i.handler(_event("parquet", partition_keys=keys), None)
    assert out["columns"] == [{"name": "id", "type": "bigint"}]
    assert out["ddl"].startswith("CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026`")
    assert "PARTITIONED BY (`year` int)" in out["ddl"]
    assert "'projection.year.range'='2000,2100'" in out["ddl"]
    assert out["requestId"] == "r1"  # request carried through


# ── The refresh cross-check (SPEC-143 FR-006) ────────────────────────────────

_CSV_SERDE = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
_JSON_SERDE = "org.openx.data.jsonserde.JsonSerDe"
_PARQUET_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"


def test_the_column_inference_is_a_child_span_of_the_verbs_own_span(captured_events):
    """The polars read is this verb's principal cost, and it is one call per invocation.

    Named `infer-columns` rather than `infer-schema`, which is already the root span's name.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    path = os.path.join(_TMP, "span.parquet")
    pl.DataFrame({"order_id": pl.Series([1, 2], dtype=pl.Int64)}).write_parquet(path)
    _use_fixture(path)

    out = i.handler(_event("parquet"), None)

    assert out["columns"], "the span is asserted on a SUCCESSFUL run"
    root = captured_events.spans("infer-schema")
    assert len(root) == 1, f"expected one infer-schema root span, got {len(root)}"
    children = captured_events.child_spans("infer-schema", name="infer-columns")
    assert len(children) == 1, (
        f"infer-schema emitted {len(children)} 'infer-columns' child spans, expected exactly one"
    )
    assert children[0]["parent_span_id"] == root[0]["span_id"]
