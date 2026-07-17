"""Pure polars dtype → Glue/Athena (Hive) type mapping — the ONE copy (SPEC-110 follow-up).

Turns an inferred polars dtype into the Hive type string that goes into a
CREATE EXTERNAL TABLE column list. Nested types recurse (List→array, Struct→struct). An
unmappable dtype raises UnmappableTypeError carrying the dtype; each caller adds the
column name and turns it into its own domain's terminal reason.

Callers: table-builder's infer-schema (SPEC-069) and data-quality's inspect-source
(SPEC-110). It lived in table-builder's verb dir, was copied into data-quality's, and was
consolidated here before the file-converter arc (SPEC-117) made a third copy.

╔══════════════════════════════════════════════════════════════════════════════════════╗
║ THIS MODULE IMPORTS polars, AND cpcommon IS ATTACHED TO EVERY CONTROL-PLANE VERB.    ║
║                                                                                      ║
║ Importing it from a verb that does NOT attach a polars layer is an ImportError at    ║
║ COLD START. Only two functions carry polars today:                                   ║
║   • table-builder-infer-schema  (the table-builder-polars layer)                     ║
║   • data-quality-inspect-source (the data-quality-polars layer)                      ║
║ Every other verb attaches cpcommon WITHOUT polars — 15+ of them.                     ║
║                                                                                      ║
║ Living here is safe ONLY because cpcommon/__init__.py imports no submodules, so this ║
║ file is loaded if and only if something explicitly imports it. Do not add            ║
║ `from . import type_mapping` to that __init__ — it would break every polars-free     ║
║ verb the instant it was deployed, which is the shape of the PR #196 outage (a        ║
║ shared layer's import-time requirement that only some functions can satisfy).        ║
║                                                                                      ║
║ Adding a polars-carrying verb? Give it `cpcommon: true` AND a polars layer in        ║
║ deploy-lambdas.yml's matrix, and check the combined per-function size guard.         ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
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
