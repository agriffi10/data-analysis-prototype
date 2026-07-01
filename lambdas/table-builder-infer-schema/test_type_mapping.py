"""Unit tests for the pure polars→Hive dtype mapping (SPEC-069 FR-002).

No AWS / Lambda runtime — just polars dtype objects → Hive strings, incl. nested and
the date-parsing rule (Date→date / Datetime→timestamp). Runnable under pytest OR
directly: ``python3 test_type_mapping.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl  # noqa: E402
from type_mapping import UnmappableTypeError, map_dtype  # noqa: E402


def test_integers():
    assert map_dtype(pl.Int8) == "tinyint"
    assert map_dtype(pl.Int16) == "smallint"
    assert map_dtype(pl.Int32) == "int"
    assert map_dtype(pl.Int64) == "bigint"


def test_floats_bool_string():
    assert map_dtype(pl.Float32) == "float"
    assert map_dtype(pl.Float64) == "double"
    assert map_dtype(pl.Boolean) == "boolean"
    assert map_dtype(pl.String) == "string"
    assert map_dtype(pl.Utf8) == "string"


def test_date_and_datetime_are_typed():
    # The date-parsing rule: date/timestamp, not string.
    assert map_dtype(pl.Date) == "date"
    assert map_dtype(pl.Datetime("us")) == "timestamp"
    assert map_dtype(pl.Datetime("ns")) == "timestamp"


def test_decimal_carries_precision_scale():
    assert map_dtype(pl.Decimal(10, 2)) == "decimal(10,2)"


def test_nested_list_and_struct():
    assert map_dtype(pl.List(pl.Int64)) == "array<bigint>"
    assert map_dtype(pl.List(pl.List(pl.String))) == "array<array<string>>"
    struct = pl.Struct({"id": pl.Int64, "name": pl.String})
    assert map_dtype(struct) == "struct<id:bigint,name:string>"
    # struct nested inside a list
    assert map_dtype(pl.List(pl.Struct({"x": pl.Date}))) == "array<struct<x:date>>"


def test_unmappable_dtype_raises():
    try:
        map_dtype(pl.Object)
    except UnmappableTypeError as exc:
        assert exc.dtype == pl.Object
        return
    raise AssertionError("expected UnmappableTypeError")


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
