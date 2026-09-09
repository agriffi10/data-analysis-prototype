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


def test_an_apostrophe_in_a_location_is_escaped_into_one_literal():
    """A folder named o'brien is an ordinary thing for a user to create."""
    ddl = build_create_table_ddl(
        "alice", "sales", [{"name": "amount", "type": "string"}], [], "csv",
        "s3://bkt/alice/o'brien/",
    )

    assert "LOCATION 's3://bkt/alice/o\\'brien/'" in ddl
    # And the statement does not end early: TBLPROPERTIES still follows the LOCATION.
    assert ddl.index("LOCATION") < ddl.index("TBLPROPERTIES")
