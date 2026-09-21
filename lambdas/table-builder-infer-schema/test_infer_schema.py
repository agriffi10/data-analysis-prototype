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
import io
import json
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import infer_schema as i
import polars as pl
import pytest
import test_bounded_read as ranged_s3
from cpcommon import bounded_read, clients
from cpcommon.errors import TerminalError

_REAL_CHECK = i._check_access
# Captured because _use_fixture replaces it globally and never restores it: without this,
# a test that needs the REAL ranged reader silently gets the previous test's local-file
# stub, and passes alone while failing (or worse, asserting nothing) in the full suite.
_REAL_PARQUET_SOURCE = i._parquet_source
_TMP = tempfile.mkdtemp()
_ARABIC_INDIC_DIGITS = str.maketrans("0123456789", "".join(chr(0x0660 + n) for n in range(10)))


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


def _ndjson(*rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()


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


def _use_ranged_s3(blob):
    """Serve ``blob`` through the real Parquet reader, S3 answering ranges as S3 does."""
    i._parquet_source = _REAL_PARQUET_SOURCE
    i._check_access = _REAL_CHECK
    fake = ranged_s3.RangedS3(blob)
    clients._s3 = fake
    return fake


def test_a_parquet_sample_is_typed_from_its_footer_alone():
    blob = io.BytesIO()
    pl.DataFrame({
        "order_id": pl.Series(range(50_000), dtype=pl.Int64),
        "amount": pl.Series([1.5] * 50_000, dtype=pl.Float64),
    }).write_parquet(blob, row_group_size=5_000)
    data = blob.getvalue()
    fake = _use_ranged_s3(data)

    out = i.handler(_event("parquet"), None)

    assert _types(out) == {"order_id": "bigint", "amount": "double"}
    assert fake.served == struct.unpack("<I", data[-8:-4])[0] + 8, "only the trailer and the footer"


def _not_parquet():
    return b"PAR1" + bytes(64) + b"PAR2"


def _footer_over_the_bound():
    """Built when the test runs, not at collection, so 32 MiB is not held for the whole suite."""
    declared = bounded_read.DEFAULT_PROBE_MAX_BYTES + 1
    return b"PAR1" + bytes(declared) + struct.pack("<I", declared) + b"PAR1"


@pytest.mark.parametrize(
    ("build", "reason"),
    [(_not_parquet, "does not end in PAR1"), (_footer_over_the_bound, "probe bound")],
    ids=["not-parquet", "footer-over-the-bound"],
)
def test_a_parquet_sample_whose_footer_the_probe_will_not_read_refuses_the_build(build, reason):
    """Refused as the unreadable file it is, and in the new reader's own words: a refusal from
    anywhere else would carry polars' text instead, which is how this tells the two apart."""
    fake = _use_ranged_s3(build())

    with pytest.raises(TerminalError) as err:
        i.handler(_event("parquet"), None)

    assert err.value.reason == "schema_inference_failed"
    assert reason in err.value.detail
    assert len(fake.ranges) == 1, "no footer may be fetched once the trailer refuses"


def test_a_parquet_footer_polars_panics_on_refuses_the_build_rather_than_faulting():
    """A panic is not an ``Exception``, so a bare ``except Exception`` lets it escape as a fault
    the actor is never told about by name; it must end as the same refusal as any other file the
    probe cannot read."""
    _use_ranged_s3(ranged_s3.PANICKING_PARQUET.read_bytes())

    with pytest.raises(TerminalError) as err:
        i.handler(_event("parquet"), None)

    assert err.value.reason == "schema_inference_failed"
    assert "thrift" in err.value.detail.lower(), "the refusal must come from polars' own read"


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


def test_a_json_integer_too_large_for_bigint_is_refused_by_the_column_it_is_in():
    """polars infers such a column as a 128-bit integer, which no Athena type holds, so the build
    is refused by name rather than declaring a ``bigint`` column that cannot hold its values."""
    _use_s3_fixture(_ndjson({"id": 1, "big": 9223372036854775808}))

    with pytest.raises(TerminalError) as err:
        i.handler(_event("json"), None)

    assert err.value.reason == "unmappable_type"
    assert "column 'big'" in err.value.detail


def test_json_strings_in_every_shape_athena_reads_are_typed_date_and_timestamp():
    """The positive control for the two refusals below: both timestamp branches at their widest
    fraction and offset, each a value Athena was run against and read back as the same date or
    instant."""
    _use_s3_fixture(_ndjson({
        "day": "2024-02-29",
        "nine_digits": "2024-01-01 10:00:00.123456789",
        "t_no_seconds": "2024-01-01T10:00+02:00",
        "t_zulu": "2024-01-01T10:00:00.1234567Z",
        "t_compact": "2024-01-01T10:00:00+0200",
        "t_widest": "2024-01-01T10:00:00-18:00",
    }))
    out = i.handler(_event("json"), None)
    assert _types(out) == {
        "day": "date", "nine_digits": "timestamp", "t_no_seconds": "timestamp",
        "t_zulu": "timestamp", "t_compact": "timestamp", "t_widest": "timestamp",
    }


def test_one_value_athena_would_roll_over_leaves_its_column_a_string():
    """Athena reads ``2024-13-45`` back as 2025-02-14 and an hour of 25 as the next day, with no
    error and no NULL, so a well-shaped impossible value must keep its column a string. ``ok``
    shares the sample, so a string elsewhere is not the detector failing to run."""
    _use_s3_fixture(_ndjson(
        {"ok": "2024-01-01", "month13": "2024-01-01", "zero": "2024-01-01", "feb30": "2024-01-01",
         "hour25": "2024-01-01 10:00:00"},
        {"ok": "2024-12-31", "month13": "2024-13-45", "zero": "0000-00-00", "feb30": "2024-02-30",
         "hour25": "2024-01-01 25:00:00"},
    ))
    out = i.handler(_event("json"), None)
    assert _types(out) == {"ok": "date", "month13": "string", "zero": "string", "feb30": "string", "hour25": "string"}


def test_a_value_athena_refuses_to_read_leaves_its_column_a_string():
    """Each of these fails every query that reads its column, so none may be promised as a date
    or timestamp: a non-ASCII digit, a zone or missing seconds after a space, a tenth fraction
    digit, an offset minute past 59, and an offset wider than eighteen hours."""
    _use_s3_fixture(_ndjson({
        "ok": "2024-01-01T10:00:00Z",
        "arabic_digits": "2024-01-01".translate(_ARABIC_INDIC_DIGITS),
        "space_zulu": "2024-01-01 10:00:00Z",
        "space_no_seconds": "2024-01-01 10:00",
        "space_ten_digits": "2024-01-01 10:00:00.1234567891",
        "t_ten_digits": "2024-01-01T10:00:00.1234567891Z",
        "minute_75": "2024-01-01T10:00:00+02:75",
        "past_18h": "2024-01-01T10:00:00-18:30",
    }))
    out = i.handler(_event("json"), None)
    assert _types(out) == {
        "ok": "timestamp", "arabic_digits": "string", "space_zulu": "string", "space_no_seconds": "string",
        "space_ten_digits": "string", "t_ten_digits": "string", "minute_75": "string", "past_18h": "string",
    }


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


def test_a_csv_header_naming_a_partition_key_first_builds_with_that_column_renamed_in_place():
    """The export shape a groupby writes: the key first. OpenCSVSerde takes fields in order, so
    leaving `Year` out would read `id` from the file's year field, and there is no way through a
    refusal but rewriting every file. So the create builds, keeping the file's column where it is
    under a name that cannot collide, and the columns carried on stay the file's own.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _use_s3_fixture(b"Year,id,region\n2025,1,south\n")
    keys = [{"name": "year", "type": "string", "values": ["2025"]}]

    out = i.handler(_event("csv", partition_keys=keys), None)

    assert "(`year_in_file` string, `id` string, `region` string) PARTITIONED BY" in out["ddl"]
    assert [c["name"] for c in out["columns"]] == ["Year", "id", "region"]


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
