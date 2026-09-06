"""The type table against Athena's documented vocabulary, and against cpcommon's inverse.

Two questions, and they fail differently. *Is the table total over what Athena can report?* — a
gap there is a legitimate query the converter refuses. *Does it agree with `map_dtype`?* — a
disagreement there is a Parquet file the table builder reads back with the wrong types, which
nothing else in the fleet would notice.
"""

import csv
import json
import os
import pathlib
import sys

import polars as pl
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon.errors import TerminalError
from cpcommon.type_mapping import map_dtype
from rccommon import types

#: Every DML type name on https://docs.aws.amazon.com/athena/latest/ug/data-types.html, in the
#: forms Athena reports them, PAIRED WITH THE DTYPE EACH MUST PRODUCE. The pairing is the point:
#: a corpus of names alone cannot see `tinyint` widened to Int64 or `char` turned into a Date,
#: because the agreement test below asserts over the IMAGE of the table and an image discards
#: which name produced which dtype. Both survived a full run before this was written as pairs.
#:
#: Transcribed from that page rather than remembered, and written as the reported strings —
#: parameterised where Athena parameterises — so the normaliser is exercised by the corpus
#: rather than by cases invented to suit it. `decimal` appears bare because that is how Athena
#: reports it; `athena_type_of` is what makes it parametric.
ATHENA_DML_TYPES = (
    ("boolean", pl.Boolean()),
    ("tinyint", pl.Int8()),
    ("smallint", pl.Int16()),
    ("int", pl.Int32()),
    ("integer", pl.Int32()),
    ("bigint", pl.Int64()),
    ("real", pl.Float32()),
    ("float", pl.Float32()),
    ("double", pl.Float64()),
    ("decimal(11,5)", pl.Decimal(11, 5)),
    ("decimal(15)", pl.Decimal(15, 0)),
    ("char", pl.String()),
    ("char(10)", pl.String()),
    ("varchar", pl.String()),
    ("varchar(255)", pl.String()),
    ("string", pl.String()),
    ("binary", pl.String()),
    ("varbinary", pl.String()),
    ("time", pl.String()),
    ("time(3)", pl.String()),
    ("time with time zone", pl.String()),
    ("date", pl.Date()),
    ("timestamp", pl.Datetime("us")),
    ("timestamp without time zone", pl.Datetime("us")),
    ("timestamp(3)", pl.Datetime("us")),
    ("timestamp(3) without time zone", pl.Datetime("us")),
    ("timestamp with time zone", pl.String()),
    ("timestamp(3) with time zone", pl.String()),
    ("interval year to month", pl.String()),
    ("interval day to second", pl.String()),
    ("array(integer)", pl.String()),
    ("array[integer]", pl.String()),
    ("map(varchar, integer)", pl.String()),
    ("row(a integer, b varchar)", pl.String()),
    ("struct<a:int,b:string>", pl.String()),
    ("json", pl.String()),
    ("uuid", pl.String()),
    ("ipaddress", pl.String()),
    ("HyperLogLog", pl.String()),
    ("P4HyperLogLog", pl.String()),
    ("SetDigest", pl.String()),
    ("QDigest", pl.String()),
    ("TDigest", pl.String()),
    ("unknown", pl.String()),
)

#: The dtypes only `map_dtype` knows, excluded from the agreement below BY CONSTRUCTION rather
#: than because they fail: the unsigned integers it widens into a larger signed Hive type, the
#: nested types this plane keeps as text, and a zoned datetime, which Athena reports under a
#: name this table keeps as text. Naming them is the point — an exclusion list nobody wrote down
#: is indistinguishable from an assertion that was quietly narrowed.
OUTSIDE_THE_AGREEMENT = (
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
    pl.List(pl.Int64),
    pl.Struct({"a": pl.Int64}),
    pl.Datetime("us", "UTC"),
)


@pytest.mark.parametrize(("reported", "expected"), ATHENA_DML_TYPES)
def test_every_type_athena_documents_maps_to_the_dtype_it_must(reported, expected):
    """Total over the vocabulary, disjoint between the two tables, and PINNED PER NAME.

    Per name is what makes this a guard rather than a census. A membership-only assertion
    passes with `tinyint` widened to Int64 and with `char` mapped to a Date, because the
    agreement test below asserts over the table's IMAGE and an image forgets which name
    produced which dtype — both mutations survived a full run before these pairs existed.

    Disjointness matters as much as totality: a name in both tables would take whichever
    branch runs first, so the losing table's entry would be dead while reading as coverage.
    """
    base = types.normalise(reported)
    mapped = base in types._MAPPED or base == "decimal"
    kept = base in types.TEXT_KEPT
    assert mapped != kept, f"{reported!r} normalises to {base!r}, in {'both' if mapped else 'neither'} table"
    assert types.polars_dtype(reported) == expected


def test_a_name_in_neither_table_refuses_and_names_the_column():
    """The positive control for the sweep above: the vocabulary is closed, so an unmodelled
    name refuses rather than degrading to text. Without this the parametrised test passes on a
    table that maps everything to String."""
    with pytest.raises(TerminalError) as err:
        types.schema_of([{"name": "weird", "type": "geometry"}])
    assert err.value.reason == "unsupported_column_type"
    assert err.value.tokens["column"] == "weird"
    assert "geometry" in err.value.detail


def test_a_zoned_timestamp_is_text_and_is_not_reduced_to_a_naive_one():
    """The normalisation trap, asserted rather than described: cutting a reported type at its
    first bracket maps `timestamp(3) with time zone` onto `timestamp`, which types a zoned
    column as naive and silently drops the zone the characters carry."""
    assert types.polars_dtype("timestamp(3) with time zone") == pl.String()
    assert types.polars_dtype("timestamp(3) without time zone") == pl.Datetime("us")
    assert types.polars_dtype("timestamp(3)") == pl.Datetime("us")


def test_a_decimals_parameters_come_from_the_sibling_fields_and_a_bare_one_refuses():
    assert types.athena_type_of({"name": "a", "type": "decimal", "precision": 10, "scale": 2}) == "decimal(10,2)"
    assert types.athena_type_of({"name": "a", "type": "decimal", "precision": 15}) == "decimal(15,0)"
    assert types.athena_type_of({"name": "a", "type": "bigint"}) == "bigint"
    assert types.polars_dtype("decimal(10,2)") == pl.Decimal(10, 2)
    with pytest.raises(TerminalError) as err:
        types.athena_type_of({"name": "amount", "type": "decimal"})
    assert err.value.reason == "unsupported_column_type"
    assert err.value.tokens["column"] == "amount"


def test_the_table_and_cpcommons_inverse_agree_over_every_dtype_this_table_produces():
    """The round trip that makes "save as Parquet, then build a table" compose.

    Asserted over the IMAGE of `polars_dtype` — every dtype this table can produce — because
    that is the set a written Parquet file can carry. The reverse direction is not asserted and
    could not be: `map_dtype` knows dtypes this table never produces, listed in
    OUTSIDE_THE_AGREEMENT above with the reason each is outside.
    """
    produced = {types.polars_dtype(name) for name, _ in ATHENA_DML_TYPES}
    assert len(produced) > 1, "the image collapsed to one dtype, so the agreement is vacuous"
    for dtype in produced:
        assert types.polars_dtype(map_dtype(dtype)) == dtype, f"{dtype} does not survive the round trip"
    for dtype in OUTSIDE_THE_AGREEMENT:
        # Self-validating rather than documentary: each entry must be one `map_dtype` knows AND
        # one this table genuinely cannot reproduce. Without the second half the tuple could be
        # emptied, or filled with dtypes that DO round-trip, and still pass — so it would record
        # an exclusion nobody had checked.
        assert map_dtype(dtype), f"{dtype} is excluded but map_dtype does not know it"
        assert types.polars_dtype(map_dtype(dtype)) != dtype, (
            f"{dtype} round-trips after all, so excluding it hides a case the assertion covers"
        )


def test_normalisation_removes_nested_parameter_groups_rather_than_the_outermost():
    """The loop is a fixed point, not one pass. A single `sub` leaves the inner group behind on
    a nested type, and the leftover text is a name in neither table — so the failure is a
    refusal of a legitimate column rather than a wrong dtype, which is the safer direction but
    still a conversion the user cannot run."""
    assert types.normalise("row(a integer, b array(varchar))") == "row"
    assert types.normalise("map(varchar, array(row(x int)))") == "map"
    assert types.polars_dtype("array(map(varchar, integer))") == pl.String()


def test_the_schema_is_built_in_result_order():
    schema = types.schema_of(
        [
            {"name": "b", "type": "varchar(255)"},
            {"name": "a", "type": "bigint"},
            {"name": "c", "type": "decimal", "precision": 10, "scale": 2},
        ]
    )
    assert list(schema) == ["b", "a", "c"]
    assert schema == {"b": pl.String(), "a": pl.Int64(), "c": pl.Decimal(10, 2)}


#: The real Athena result set, captured from the workgroup rather than written here. The point of
#: a captured fixture is that it can DISAGREE with the code — a hand-written one only ever
#: restates what its author believed.
_CAPTURE = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
CAPTURED_CSV = _CAPTURE / "athena_result_all_types.csv"
CAPTURED_COLUMNS = _CAPTURE / "athena_result_all_types_columns.json"


def _captured():
    """The captured ColumnInfo, as name-to-type."""
    return {c["Name"]: c["Type"] for c in json.loads(CAPTURED_COLUMNS.read_text(encoding="utf-8"))}


def test_every_type_the_captured_execution_reports_is_one_the_table_maps():
    """The corpus above is transcribed from Athena's docs; this is what Athena actually sent.

    Both kinds of evidence are needed. The docs say what CAN arrive; the capture says what DID,
    in the spellings the service really uses — `int` for an `integer` cast, `float` for `real`,
    `string` for `varchar`, `array` with no element type. A table satisfying only the documented
    spellings would refuse a real query.
    """
    reported = _captured()
    assert len(reported) == 24, "the capture lost columns; it is no longer the execution it names"
    for name, reported_type in reported.items():
        column = {"name": name, "type": reported_type, "precision": 10, "scale": 2}
        assert isinstance(types.polars_dtype(types.athena_type_of(column)), pl.DataType), (
            f"{reported_type!r}, from a real execution, is unmapped"
        )


def test_the_two_halves_of_the_capture_describe_the_same_execution():
    """The fixture is a PAIR, and nothing else here holds the halves together.

    Every other test reads one file or the other. So a column renamed in the JSON, reordered
    against the CSV, or dropped from either side leaves a fixture that still passes while no
    longer being one execution — and the converter's own rule is positional: `scan_csv` applied
    to a metadata schema renames columns by POSITION when the names disagree, silently. A pair
    that disagreed would be a fixture demonstrating the exact bug the converter's header check
    exists to catch, while asserting the check is unnecessary.
    """
    with CAPTURED_CSV.open(encoding="utf-8", newline="") as handle:
        header, *rows = list(csv.reader(handle))
    described = [c["Name"] for c in json.loads(CAPTURED_COLUMNS.read_text(encoding="utf-8"))]
    assert described == header, (
        "the metadata and the CSV no longer name the same columns in the same order, so the two "
        "files are not one execution any more"
    )
    assert len(rows) == 1, (
        f"the capture holds {len(rows)} data rows rather than one, so it is no longer the single "
        "row every assertion here indexes into"
    )
    assert len(rows[0]) == len(header), (
        f"the data row has {len(rows[0])} fields against {len(header)} columns, so the capture "
        "demonstrates a shape Athena did not write"
    )


def test_the_capture_shows_athena_reporting_decimal_without_its_parameters():
    """The premise the describe-results change rests on, in Athena's own bytes.

    The query cast this column `decimal(10,2)`. If the parameters travelled in `Type`, carrying
    `precision`/`scale` separately would be dead weight.
    """
    assert _captured()["c_decimal"] == "decimal", "the parameters arrived in Type after all"
    composed = types.athena_type_of({"name": "c_decimal", "type": "decimal", "precision": 10, "scale": 2})
    assert types.polars_dtype(composed) == pl.Decimal(10, 2)


def test_athena_writes_null_unquoted_and_an_empty_string_quoted():
    """FR-001's distinction, read off the bytes Athena wrote rather than off a hand-made CSV.

    This is the assertion a fixture built here could not honestly make. The row carries
    `CAST('' AS varchar)` and `CAST(NULL AS varchar)` side by side, so the difference is visible
    as `""` against a bare empty field — and the reader must preserve it, because collapsing the
    two turns every absent value into a present empty one.
    """
    row = CAPTURED_CSV.read_text(encoding="utf-8").splitlines()[1]
    assert '"hi","ab","",,' in row, (
        "the capture no longer shows a quoted empty string beside an unquoted NULL, so this test "
        "asserts about a file that does not demonstrate the rule any more"
    )

    frame = pl.read_csv(
        CAPTURED_CSV,
        schema_overrides={"c_empty": pl.String, "c_null_text": pl.String, "c_null_bigint": pl.Int64},
        infer_schema_length=0,
    )
    assert frame["c_empty"][0] == "", "a quoted empty field is an empty STRING"
    assert frame["c_null_text"][0] is None, "an unquoted empty field is NULL"
    assert frame["c_null_bigint"][0] is None, "and so is one in a numeric column"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
