"""The Athena type Athena reported, turned into the polars dtype the writers see.

The CSV Athena writes is entirely strings, so the frame's types come from the execution's
metadata and never from looking at the values. That is the whole point: a column of
numeric-looking strings declared ``varchar`` stays text, where an inferring reader would
silently turn an account number into a float.

**The vocabulary is closed and does not fall back.** A name that is neither mapped nor listed
as text-kept refuses the conversion, because a closed vocabulary with a fallback is not closed
— the fallback is where an unmodelled type quietly becomes the wrong column.

**A decimal's parameters do not arrive in the type string.** Athena reports the bare name and
puts the precision and scale in ``ColumnInfo``'s sibling fields, which is why AWS's own SDK for
pandas composes ``decimal(p,s)`` itself rather than reading one. ``athena_type_of`` is this
repo's copy of that composition, and it is the only place the two halves are joined.

**Normalisation removes parameter groups; it does not cut at the first bracket.** Cutting maps
``timestamp(3) with time zone`` to ``timestamp``, which types a zoned column as naive — the one
normalisation error that corrupts a value instead of refusing it. Everything Athena parameterises
(``varchar(255)``, ``array(integer)``, ``row(a integer, b varchar)``) survives the removal with
its base name intact.

Attributes:
  TEXT_KEPT: The Athena types written as the characters Athena rendered. Nested values are here
    because reconstructing structure from rendered text is a parser this arc does not build;
    the zoned and interval types because polars has no dtype that preserves what they carry;
    the approximate-function digests because they are opaque binary summaries.
  _MAPPED: The types with a real polars dtype. ``timestamp without time zone`` is the same type
    as ``timestamp`` under a longer name, so both land on a naive microsecond datetime.
  _PARAMS: A balanced parameter group, in each of the three bracket styles Athena uses —
    round for the DML forms, angled for the Hive/DDL ones, and square because the docs page
    spells the DML array type ``ARRAY[element]``.
  _DECIMAL: The one type whose parameters change the dtype rather than only bounding it.
  _DECIMAL_PARAMS: Its precision and optional scale, wherever they are written.
"""

import re

import polars as pl
from cpcommon.errors import TerminalError

from . import reasons

__all__ = ["TEXT_KEPT", "athena_type_of", "normalise", "polars_dtype", "schema_of"]

TEXT_KEPT = frozenset(
    {
        "json",
        "binary",
        "varbinary",
        "array",
        "map",
        "row",
        "struct",
        "ipaddress",
        "uuid",
        "time",
        "time with time zone",
        "timestamp with time zone",
        "interval year to month",
        "interval day to second",
        "hyperloglog",
        "p4hyperloglog",
        "setdigest",
        "qdigest",
        "tdigest",
        "unknown",
    }
)

_MAPPED: dict[str, pl.DataType] = {
    "boolean": pl.Boolean(),
    "tinyint": pl.Int8(),
    "smallint": pl.Int16(),
    "int": pl.Int32(),
    "integer": pl.Int32(),
    "bigint": pl.Int64(),
    "real": pl.Float32(),
    "float": pl.Float32(),
    "double": pl.Float64(),
    "date": pl.Date(),
    "timestamp": pl.Datetime("us"),
    "timestamp without time zone": pl.Datetime("us"),
    "varchar": pl.String(),
    "char": pl.String(),
    "string": pl.String(),
}

_PARAMS = re.compile(r"\([^()]*\)|<[^<>]*>|\[[^\[\]]*\]")

_DECIMAL = "decimal"

_DECIMAL_PARAMS = re.compile(r"\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)")


def normalise(athena_type: str) -> str:
    """Reduces a reported type to the base name the tables are keyed by.

    Args:
      athena_type: The type as Athena reported it, parameters and all.

    Returns:
      The lower-cased base name with every parameter group removed and its whitespace
      collapsed, so ``TIMESTAMP(3) WITH TIME ZONE`` and ``timestamp with time zone`` are one
      key while ``timestamp`` stays a different one.

    Raises:
      None.
    """
    reduced = athena_type.strip().lower()
    while True:
        stripped = _PARAMS.sub("", reduced)
        if stripped == reduced:
            break
        reduced = stripped
    return re.sub(r"\s+", " ", reduced).strip()


def athena_type_of(column: dict) -> str:
    """Renders one described column into the canonical type string this module maps.

    Only ``decimal`` needs rendering: every other parameterised type carries its parameters in
    the string already, and this module discards them. A ``decimal`` that arrives ALREADY
    parametric is returned untouched — Athena is not observed to send that shape, but refusing
    a type string carrying everything needed would be a refusal of a correct input.

    Args:
      column: A described column — ``name``, ``type``, and ``precision``/``scale`` when Athena
        reported them.

    Returns:
      The type string, with ``decimal`` rendered as ``decimal(p,s)``.

    Raises:
      TerminalError: ``unsupported_column_type`` for a decimal carrying no precision. Athena
        does not produce that shape, and inventing a scale would silently round the values.
    """
    reported = str(column.get("type") or "")
    if normalise(reported) != _DECIMAL:
        return reported
    if _DECIMAL_PARAMS.search(reported):
        return reported
    precision, scale = column.get("precision"), column.get("scale")
    if not isinstance(precision, int) or isinstance(precision, bool):
        raise TerminalError(
            reasons.UNSUPPORTED_COLUMN_TYPE,
            f"decimal column {column.get('name')!r} carries no precision",
            tokens={"column": str(column.get("name") or "")},
        )
    exact = scale if isinstance(scale, int) and not isinstance(scale, bool) else 0
    return f"{_DECIMAL}({precision},{exact})"


def polars_dtype(athena_type: str) -> pl.DataType:
    """Maps one Athena type to the polars dtype a column of it is read as.

    Args:
      athena_type: The type string, canonical per ``athena_type_of``.

    Returns:
      The dtype. A text-kept type maps to ``String``, holding the characters Athena rendered.

    Raises:
      TerminalError: ``unsupported_column_type`` for a name in neither table, and for a
        ``decimal`` whose parameters will not parse.
    """
    base = normalise(athena_type)
    if base == _DECIMAL:
        match = _DECIMAL_PARAMS.search(athena_type)
        if not match:
            raise TerminalError(
                reasons.UNSUPPORTED_COLUMN_TYPE, f"{athena_type!r} carries no decimal parameters"
            )
        return pl.Decimal(int(match.group(1)), int(match.group(2) or 0))
    if base in _MAPPED:
        return _MAPPED[base]
    if base in TEXT_KEPT:
        return pl.String()
    raise TerminalError(reasons.UNSUPPORTED_COLUMN_TYPE, f"unknown Athena type {athena_type!r}")


def schema_of(columns: list[dict]) -> dict[str, pl.DataType]:
    """Builds the polars schema for a described result set, in result order.

    Args:
      columns: The described columns, as describe-results emitted them.

    Returns:
      Column name to dtype, ordered as the result set is.

    Raises:
      TerminalError: ``unsupported_column_type`` naming the offending column, so the user is
        told which column their query has to change.
    """
    schema: dict[str, pl.DataType] = {}
    for column in columns:
        name = str(column.get("name") or "")
        try:
            schema[name] = polars_dtype(athena_type_of(column))
        except TerminalError as err:
            raise TerminalError(
                err.reason, f"column {name!r}: {err.detail}", tokens={"column": name}
            ) from err
    return schema
