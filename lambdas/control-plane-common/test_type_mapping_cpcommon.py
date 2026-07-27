"""Unit tests for cpcommon.type_mapping — the pure polars→Hive dtype mapping.

The union of the two suites this consolidates (table-builder-infer-schema/
test_type_mapping.py and data-quality-inspect-source/test_dq_type_mapping.py), so the
merge loses no coverage: table-builder's brought the pl.Utf8 alias and list-of-list;
data-quality's brought the unsigned ints, the unparameterised Decimal(), and the wider
unmappable set.

No AWS / Lambda runtime — just polars dtype objects → Hive strings. Runnable under pytest
or directly: python3 test_type_mapping_cpcommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl
import pytest
from cpcommon.type_mapping import UnmappableTypeError, map_dtype


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
        (pl.Utf8, "string"),  # alias of pl.String
        (pl.Date, "date"),
    ],
)
def test_simple_dtypes(dtype, hive):
    assert map_dtype(dtype) == hive


def test_date_and_datetime_are_typed_not_string():
    """The date rule: date/timestamp, never string."""
    assert map_dtype(pl.Date) == "date"
    assert map_dtype(pl.Datetime("us")) == "timestamp"
    assert map_dtype(pl.Datetime("ns")) == "timestamp"
    assert map_dtype(pl.Datetime("ns", "UTC")) == "timestamp"


def test_decimal_carries_precision_and_scale():
    assert map_dtype(pl.Decimal(10, 2)) == "decimal(10,2)"


def test_decimal_defaults_when_unparameterised():
    assert map_dtype(pl.Decimal()) == "decimal(38,0)"


def test_list_recurses():
    assert map_dtype(pl.List(pl.Int64)) == "array<bigint>"
    assert map_dtype(pl.List(pl.List(pl.String))) == "array<array<string>>"


def test_struct_recurses():
    assert map_dtype(pl.Struct({"id": pl.Int64, "name": pl.String})) == "struct<id:bigint,name:string>"


def test_struct_nested_inside_a_list():
    assert map_dtype(pl.List(pl.Struct({"x": pl.Date}))) == "array<struct<x:date>>"


@pytest.mark.parametrize("dtype", [pl.Object, pl.Binary, pl.Time])
def test_unmappable_dtypes_raise_carrying_the_dtype(dtype):
    with pytest.raises(UnmappableTypeError) as err:
        map_dtype(dtype)
    assert err.value.dtype == dtype


def test_importing_cpcommon_does_not_pull_in_polars():
    """The constraint that makes this module's home safe (see its docstring).

    cpcommon is attached to EVERY control-plane verb, but polars only to the two that
    read Parquet footers. This module is therefore loaded only when explicitly imported —
    if cpcommon/__init__.py ever gained `from . import type_mapping`, every polars-free
    verb would ImportError at cold start. Asserting on the __init__ SOURCE rather than
    sys.modules keeps this honest: polars is already imported in this test process.
    """
    import pathlib

    import cpcommon

    source = pathlib.Path(cpcommon.__file__).read_text()
    assert "type_mapping" not in source, "cpcommon/__init__.py must not import type_mapping"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
