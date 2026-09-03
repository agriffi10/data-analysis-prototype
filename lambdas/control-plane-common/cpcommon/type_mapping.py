"""Pure polars dtype to Glue/Athena (Hive) type mapping — the one copy.

Turns an inferred polars dtype into the Hive type string that goes into a
CREATE EXTERNAL TABLE column list. Nested types recurse. An unmappable dtype raises
``UnmappableTypeError`` carrying the dtype; each caller adds the column name and turns it
into its own domain's terminal reason.

This module imports polars, and every control-plane verb resolves cpcommon. **The old hazard has
inverted:** importing this from a verb without a polars layer used to be an ImportError at cold
start, and the image installs polars for every function, so it now succeeds — quietly, and at the
cost of polars' import time on a verb that has no use for it. Living here is safe only because
``cpcommon/__init__.py`` imports no submodules, so this file loads if and only if something
explicitly imports it. Never add it to that ``__init__``. Read ``lambdas/info/shared-layer.md`` before adding a polars-carrying verb.

Attributes:
  _SIMPLE: Non-parametric dtypes to Hive. Parametric ones carry parameters and are handled
    by isinstance checks in ``map_dtype``.
"""

import polars as pl


class UnmappableTypeError(Exception):
    """A polars dtype with no Hive equivalent, such as Object, Binary or Time.

    Attributes:
      dtype: The dtype that could not be mapped.
    """

    def __init__(self, dtype):
        """Records the offending dtype as both an attribute and the message.

        Args:
          dtype: The polars dtype with no Hive equivalent.

        Returns:
          None.

        Raises:
          None.
        """
        self.dtype = dtype
        super().__init__(str(dtype))


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
    (pl.String, "string"),
    (pl.Date, "date"),
]


def map_dtype(dtype) -> str:
    """Maps a polars dtype to its Hive type string, recursing through nested types.

    Parametric types are matched first, because they carry precision, scale, inner type or
    fields that the simple equality table cannot express.

    Args:
      dtype: The polars dtype to map.

    Returns:
      The Hive type string.

    Raises:
      UnmappableTypeError: If the dtype, or any nested dtype, has no Hive equivalent.
    """
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
