"""Pure polars dtype → Glue/Athena (Hive) type mapping for the data-quality probe.

Turns an inferred polars dtype into the Hive type string the manifest records and
SPEC-111 puts straight into its CREATE EXTERNAL TABLE column list. Nested types recurse
(List→array, Struct→struct). An unmappable dtype raises UnmappableTypeError carrying the
dtype; the verb adds the column name and turns it into a terminal. Only exercised for
Parquet / JSON — CSV columns are emitted as string directly (SPEC-111 FR-002's
OpenCSVSerde reads everything as string, which is what makes its TRY_CAST checks work).

WHY THIS LIVES IN THE VERB DIR, NOT dqcommon: it imports polars, and the dqcommon LAYER
is attached to all nine DQ verbs while the polars layer is attached to inspect-source
ALONE (SPEC-108 FR-003). A polars-importing module inside dqcommon would be an import
error waiting for whichever verb touched it. table-builder puts its equivalent in the
verb dir (table-builder-infer-schema/type_mapping.py) for the same reason.

DUPLICATION, KNOWINGLY: this is a near-copy of that file. Consolidating the two into a
shared home is a cross-arc refactor of a shipped verb, out of scope for SPEC-110 — it is
tracked separately. Keep the two in sync until then.
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


def map_dtype(dtype) -> str:
    """Map a polars dtype to its Hive type string; raises UnmappableTypeError."""
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
