"""Unit tests for the data-quality polars dtype → Hive mapping (SPEC-110 FR-005).

Mirrors table-builder-infer-schema/test_type_mapping.py, because dq_type_mapping.py is a
near-copy of that module (see its docstring — consolidation is tracked separately). These
types land verbatim in SPEC-111's CREATE EXTERNAL TABLE column list, so they are pinned
here rather than trusted to the twin's tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl  # noqa: E402
import pytest  # noqa: E402

from dq_type_mapping import UnmappableTypeError, map_dtype  # noqa: E402


@pytest.mark.parametrize(
    "dtype,hive",
    [
        (pl.Int8, "tinyint"),
        (pl.Int16, "smallint"),
        (pl.Int32, "int"),
        (pl.Int64, "bigint"),
        (pl.UInt8, "smallint"),
        (pl.UInt16, "int"),
        (pl.UInt32, "bigint"),
        (pl.UInt64, "bigint"),
        (pl.Float32, "float"),
        (pl.Float64, "double"),
        (pl.Boolean, "boolean"),
        (pl.String, "string"),
        (pl.Date, "date"),
    ],
)
def test_simple_dtypes(dtype, hive):
    assert map_dtype(dtype) == hive


def test_datetime_is_timestamp_regardless_of_precision():
    assert map_dtype(pl.Datetime("us")) == "timestamp"
    assert map_dtype(pl.Datetime("ns", "UTC")) == "timestamp"


def test_decimal_carries_precision_and_scale():
    assert map_dtype(pl.Decimal(10, 2)) == "decimal(10,2)"


def test_decimal_defaults_when_unparameterised():
    assert map_dtype(pl.Decimal()) == "decimal(38,0)"


def test_list_recurses():
    assert map_dtype(pl.List(pl.Int64)) == "array<bigint>"


def test_struct_recurses():
    assert map_dtype(pl.Struct({"a": pl.Int64, "b": pl.String})) == "struct<a:bigint,b:string>"


def test_nested_list_of_struct():
    assert map_dtype(pl.List(pl.Struct({"a": pl.Date}))) == "array<struct<a:date>>"


@pytest.mark.parametrize("dtype", [pl.Binary, pl.Time, pl.Object])
def test_unmappable_dtypes_raise_carrying_the_dtype(dtype):
    with pytest.raises(UnmappableTypeError) as err:
        map_dtype(dtype)
    assert err.value.dtype == dtype


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
