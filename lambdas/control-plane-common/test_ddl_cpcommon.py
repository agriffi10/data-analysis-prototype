"""Golden-string tests for the pure DDL generator (SPEC-069, moved to cpcommon in SPEC-111).

No AWS / polars — asserts the exact generated CREATE EXTERNAL TABLE for flat
Parquet, partitioned CSV (integer projection + OpenCSVSerde all-string), partitioned
JSON, and a string enum partition key.

The first five tests came UNCHANGED from table-builder's ``test_ddl.py``, deliberately:
they are what proved the module move did not alter that arc's shipped output. Their
golden strings gained ``portal.managed`` in SPEC-143 — the one intended change to that
output since. The tests below them cover the ``storage`` override SPEC-111 added for the
data-quality arc's divergent SerDes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import ddl as ddl_module
from cpcommon.ddl import (
    build_create_table_ddl,
    quote,
    quote_dml,
)

LOC = "s3://dat-prod-user-space/alice/sales/2026/"
_HERE = os.path.dirname(os.path.abspath(__file__))


# ── Rebuilding from a captured definition (SPEC-144 FR-004) ──────────────────

#: What `clone_definition` captures for each format the create path writes — the Glue
#: SerdeInfo/format pair, as it comes BACK from the catalog rather than as it went in.
_CAPTURED = {
    "parquet": {
        "serializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
        "parameters": {"serialization.format": "1"},
        "inputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
        "outputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
    },
    "csv": {
        # NOTE the single backslash: Hive unescapes the '\\' the DDL source writes, so this
        # is what Glue hands back. Re-rendering it verbatim produces a DIFFERENT statement.
        "serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
        "parameters": {"separatorChar": ",", "quoteChar": '"', "escapeChar": "\\"},
        "inputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "outputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
    },
    "json": {
        "serializationLibrary": "org.openx.data.jsonserde.JsonSerDe",
        "parameters": {},
        "inputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "outputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
    },
}


def test_quote_escapes_an_embedded_backtick():
    """The DDL half of the pair below, and the sharper one: `quote` wraps names this portal
    does NOT choose — a column read out of a file header, a partition key derived from an S3
    folder segment. Unescaped, one backtick closed the quote and the rest of the value became
    DDL. `cpcommon.columns` refuses such a name wherever it is checked, but this is the layer
    that renders, and a renderer that is safe only because someone else validated first is one
    refactor away from not being safe."""
    assert quote("ab`c") == "`ab``c`"
    assert quote("x` string, `injected") == "`x`` string, ``injected`"


def test_quote_dml_escapes_an_embedded_double_quote():
    """A CSV header can contain anything. Unescaped, this ends the identifier early and
    the rest of the name is parsed as SQL."""
    assert quote_dml('he said "hi"') == '"he said ""hi"""'


# ── SPEC-151 FR-006: every DDL literal goes through literal() ───────────────
#
# `literal()` has sat in this module all along and is already used for column comments,
# but TBLPROPERTIES and LOCATION were rendered with raw f-string quotes. Blast radius is
# SELF-SCOPED — a user can only reach a table in their own database, and Athena rejects
# multi-statement DDL — so this is robustness, not cross-tenant escalation. The sharper
# path is data-quality, where both the LOCATION and the partition values come from S3 KEY
# SEGMENTS, so a folder named `year=2024'` broke the temp-table DDL and the check died as
# query_failed.


def test_an_apostrophe_in_an_enum_value_cannot_inject_a_property():
    """The demonstrated attack: a value of `eu','projection.enabled'='false` rendered as
    'projection.region.values'='eu','projection.enabled'='false' — switching partition
    projection OFF via a property nobody wrote."""
    keys = [{"name": "region", "type": "string", "values": ["eu','projection.enabled'='false"]}]
    ddl = build_create_table_ddl(
        "alice", "sales", [{"name": "amount", "type": "string"}], keys, "csv", LOC
    )

    props = ddl[ddl.index("TBLPROPERTIES (") :]
    # `projection.enabled` appears exactly ONCE — the legitimate one this builder emits.
    assert props.count("'projection.enabled'=") == 1
    assert "'projection.enabled'='true'" in props
    assert "'projection.enabled'='false'" not in props


# ── A column that names a partition key ──────────────────────────────────────
#
# Athena compares the two ignoring case and refuses the pair as "Column repeated in
# partitioning columns", so the match is on the fold. What happens to the column depends on the
# SerDe: Athena reads Parquet and JSON by name, so there it is left out, while OpenCSVSerde takes
# fields in order and only skips the header — so a CSV drop moves every later column onto the
# wrong field. Measured on a built table: a header of `year,id,region` over `2025,1,south` read
# `id` as `2025`. A CSV keeps the column instead, under a new name, in its place.

_YEAR_KEY = [{"name": "year", "type": "string", "values": ["2025"]}]


def _names(columns, keys, fmt="csv"):
    """The names ``body_columns`` declares for bare column names, all typed string.

    Args:
      columns: The data column names, in order.
      keys: The partition key names.
      fmt: The source format.

    Returns:
      The declared names, in order.

    Raises:
      None.
    """
    return [
        c["name"]
        for c in ddl_module.body_columns(
            [{"name": n, "type": "string"} for n in columns], [{"name": k} for k in keys], fmt
        )
    ]


def test_a_csv_column_naming_a_partition_key_is_rendered_in_its_place_under_a_new_name():
    """The shape pandas and Excel exports produce: the key first, the rest after it. Every field
    stays where the file put it, and the partition keeps its own name. Folded on BOTH sides —
    data-quality's keys come from folder names, so `Month=01/` is the user's capital letter."""
    columns = [{"name": "Year", "type": "string"}, {"name": "id", "type": "string"},
               {"name": "month", "type": "string"}]
    keys = [{"name": "year", "type": "string", "values": ["2025"]},
            {"name": "Month", "type": "string", "values": ["01"]}]

    ddl = build_create_table_ddl("alice", "sales", columns, keys, "csv", LOC)

    assert (
        "(`year_in_file` string, `id` string, `month_in_file` string) "
        "PARTITIONED BY (`year` string, `Month` string)"
    ) in ddl


@pytest.mark.parametrize(
    ("columns", "keys", "expected"),
    [
        pytest.param(["id", "region", "year"], ["year"], ["id", "region", "year_in_file"],
                     id="trailing-is-renamed-too"),
        pytest.param(["year", "Year_In_File", "id"], ["year"], ["year_in_file_2", "Year_In_File", "id"],
                     id="a-kept-column-already-holding-the-name-pushes-it-on"),
        pytest.param(["year", "id"], ["year", "year_in_file"], ["year_in_file_2", "id"],
                     id="a-partition-key-already-holding-the-name-pushes-it-on"),
        pytest.param(["year_in_file", "year", "id"], ["year", "year_in_file"],
                     ["year_in_file_in_file", "year_in_file_2", "id"],
                     id="a-column-naming-a-key-that-is-itself-a-new-name"),
        pytest.param(["Year", "year", "id"], ["year"], ["year_in_file", "year_in_file_2", "id"],
                     id="two-spellings-of-one-key-get-two-names"),
    ],
)
def test_a_new_name_never_folds_to_a_name_the_table_already_has(columns, keys, expected):
    """The candidates run `_in_file`, `_in_file_2`, … and the first whose fold is free wins —
    free of every kept column, every partition key and every name assigned earlier in the pass,
    or Athena refuses the statement as a repeated column."""
    assert _names(columns, keys) == expected


def test_a_new_name_is_cut_to_fit_glues_ceiling_in_bytes_not_characters():
    """A refresh skips the name rule, so a header can carry a 255-character name of two-byte
    characters; Glue's ceiling is in bytes. The cut keeps whole characters and the whole suffix."""
    long_ascii = "y" * 255
    long_accented = "é" * 200

    [ascii_name] = _names([long_ascii], [long_ascii])
    [accented_name] = _names([long_accented], [long_accented])

    assert len(ascii_name.encode("utf-8")) == 255 and ascii_name.endswith("y_in_file")
    assert len(accented_name.encode("utf-8")) <= 255 and accented_name.endswith("é_in_file")


def test_every_default_storage_read_by_position_is_declared_positional():
    """`POSITIONAL_FORMATS` is a claim about SerDes that nothing else ties to the clauses, and a
    format added without listing it reopens the shift silently — the symptom being a table that
    looks right. Derived from the storage clauses rather than restated, so this fails on the
    addition rather than agreeing with whatever the constant says."""
    by_position = ("OpenCSVSerde", "LazySimpleSerDe")

    from_clauses = {
        fmt
        for fmt, storage in ddl_module._DEFAULT_STORAGE.items()
        if any(serde in storage.clause for serde in by_position)
    }

    assert from_clauses == ddl_module.POSITIONAL_FORMATS


@pytest.mark.parametrize("fmt", ["parquet", "json"])
def test_the_same_column_is_left_out_of_a_body_athena_reads_by_name(fmt):
    """A renamed column in a name-matched format would read NULL, since no field carries the
    new name, and leaving it out moves nothing: the columns after it keep their own values."""
    columns = [{"name": "Year", "type": "string"}, {"name": "id", "type": "bigint"}]

    ddl = build_create_table_ddl("alice", "sales", columns, _YEAR_KEY, fmt, LOC)

    assert "(`id` bigint) PARTITIONED BY (`year` string)" in ddl
    assert [pair.declared for pair in ddl_module.declare_columns(columns, _YEAR_KEY, fmt)] == [
        None,
        columns[1],
    ]


def test_an_apostrophe_in_a_location_is_escaped_into_one_literal():
    """A folder named o'brien is an ordinary thing for a user to create."""
    ddl = build_create_table_ddl(
        "alice", "sales", [{"name": "amount", "type": "string"}], [], "csv",
        "s3://bkt/alice/o'brien/",
    )

    assert "LOCATION 's3://bkt/alice/o\\'brien/'" in ddl
    # And the statement does not end early: TBLPROPERTIES still follows the LOCATION.
    assert ddl.index("LOCATION") < ddl.index("TBLPROPERTIES")
