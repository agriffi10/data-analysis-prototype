"""polars dtype → Glue/Athena (Hive) type mapping (SPEC-069, pure).

The single source of truth for turning an inferred polars dtype into the Hive type
string that goes in the ``CREATE EXTERNAL TABLE`` column list. Pure and unit-tested
without AWS or a Lambda runtime. Nested types recurse (``List``→``array<…>``,
``Struct``→``struct<…>``). An unmappable dtype raises ``UnmappableTypeError`` carrying
the dtype; the handler adds the column name and turns it into terminal
``unmappable_type`` (FR-002).

Only exercised for Parquet / JSON — CSV columns are emitted as ``string`` directly
(no inference, SPEC-069 rule) and never reach this module.
"""

import polars as pl


class UnmappableTypeError(Exception):
    """A polars dtype with no Hive equivalent (e.g. Object/Binary/Time)."""

    def __init__(self, dtype):
        self.dtype = dtype
        super().__init__(str(dtype))


# Non-parametric dtypes → Hive. Parametric ones (Datetime/Decimal/List/Struct) are
# handled by isinstance below because they carry parameters.
_SIMPLE = [
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
    (pl.String, "string"),  # pl.Utf8 is an alias of pl.String
    (pl.Date, "date"),
]


def map_dtype(dtype):
    """Map a polars dtype to its Hive type string. Raises ``UnmappableTypeError``."""
    # Parametric types first (they carry precision/scale/inner/fields).
    if isinstance(dtype, pl.Datetime):
        return "timestamp"
    if isinstance(dtype, pl.Decimal):
        precision = dtype.precision or 38
        scale = dtype.scale or 0
        return f"decimal({precision},{scale})"
    if isinstance(dtype, pl.List):
        return f"array<{map_dtype(dtype.inner)}>"
    if isinstance(dtype, pl.Struct):
        fields = ",".join(f"{f.name}:{map_dtype(f.dtype)}" for f in dtype.fields)
        return f"struct<{fields}>"

    for cls, hive in _SIMPLE:
        if dtype == cls:
            return hive
    raise UnmappableTypeError(dtype)
