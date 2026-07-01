"""Handler tests for infer-schema (SPEC-069 FR-001/FR-005/FR-006).

Real polars fixtures (Parquet / CSV / JSON) written to a temp dir; the S3 download is
stubbed to hand the handler the local fixture path. Asserts the type rules — CSV all
string (no inference), JSON date/datetime strings → date/timestamp, Parquet native
types — plus scan-error → terminal and transient-S3 → raised. Runnable under pytest OR
directly: ``python3 test_infer_schema.py``.
"""

import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl  # noqa: E402

import infer_schema as i  # noqa: E402
from tbcommon import clients  # noqa: E402
from tbcommon.errors import TerminalError  # noqa: E402

_REAL_DOWNLOAD = i._download_sample
_TMP = tempfile.mkdtemp()


def _use_fixture(path):
    i._download_sample = lambda bucket, key: path


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
        "ts": pl.Series([dt.datetime(2026, 1, 1, 12), dt.datetime(2026, 1, 2, 12)]),
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
    path = os.path.join(_TMP, "s.csv")
    with open(path, "w") as fh:
        fh.write("order_id,amount,ts\n1,2.50,2026-01-01\n2,3.75,2026-01-02\n")
    _use_fixture(path)
    out = i.handler(_event("csv"), None)
    # Every column string despite int/float/date-looking values.
    assert _types(out) == {"order_id": "string", "amount": "string", "ts": "string"}


def test_json_dates_are_parsed():
    path = os.path.join(_TMP, "s.ndjson")
    with open(path, "w") as fh:
        fh.write('{"id": 1, "d": "2026-01-01", "ts": "2026-01-01T12:00:00", "name": "a"}\n')
        fh.write('{"id": 2, "d": "2026-01-02", "ts": "2026-01-02T13:30:00", "name": "b"}\n')
    _use_fixture(path)
    out = i.handler(_event("json"), None)
    assert _types(out) == {"id": "bigint", "d": "date", "ts": "timestamp", "name": "string"}


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


def test_scan_error_is_terminal_schema_inference_failed():
    path = os.path.join(_TMP, "bad.parquet")
    with open(path, "w") as fh:
        fh.write("this is not a parquet file")
    _use_fixture(path)
    try:
        i.handler(_event("parquet"), None)
    except TerminalError as exc:
        assert exc.reason == "schema_inference_failed"
        return
    raise AssertionError("expected TerminalError(schema_inference_failed)")


def test_transient_s3_error_propagates():
    i._download_sample = _REAL_DOWNLOAD  # exercise the real download path

    class _FakeS3:
        def download_file(self, *a, **k):
            raise RuntimeError("ThrottlingException")

    clients._s3 = _FakeS3()
    try:
        i.handler(_event("parquet"), None)
    except TerminalError:
        raise AssertionError("transient S3 error must NOT be terminalized")
    except RuntimeError:
        return
    raise AssertionError("expected the transient error to propagate")


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
