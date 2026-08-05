"""Golden-string tests for the pure DDL generator (SPEC-069, moved to cpcommon in SPEC-111).

No AWS / polars — asserts the exact generated CREATE EXTERNAL TABLE for flat
Parquet, partitioned CSV (integer projection + OpenCSVSerde all-string), partitioned
JSON, and a string enum partition key. Runnable under pytest or directly.

The first five tests came UNCHANGED from table-builder's ``test_ddl.py``, deliberately:
they are what proved the module move did not alter that arc's shipped output. Their
golden strings gained ``portal.managed`` in SPEC-143 — the one intended change to that
output since. The tests below them cover the ``storage`` override SPEC-111 added for the
data-quality arc's divergent SerDes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon.ddl import (
    Storage,
    build_create_table_ddl,
    default_storage,
    quote,
    quote_dml,
)

LOC = "s3://dat-prod-user-space/alice/sales/2026/"
_HERE = os.path.dirname(os.path.abspath(__file__))


def test_flat_parquet_no_partitions():
    ddl = build_create_table_ddl(
        "alice", "sales_2026",
        [{"name": "order_id", "type": "bigint"}, {"name": "amount", "type": "double"}],
        [], "parquet", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026` "
        "(`order_id` bigint, `amount` double) "
        "STORED AS PARQUET LOCATION 's3://dat-prod-user-space/alice/sales/2026/' "
        "TBLPROPERTIES ('portal.managed'='true')"
    )


def test_partitioned_csv_integer_projection_all_string():
    keys = [
        {"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4},
        {"name": "month", "type": "integer", "range": [1, 12], "digits": 2},
    ]
    ddl = build_create_table_ddl(
        "alice", "sales_2026",
        [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}, {"name": "ts", "type": "string"}],
        keys, "csv", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026` "
        "(`order_id` string, `amount` string, `ts` string) "
        "PARTITIONED BY (`year` int, `month` int) "
        "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
        "WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') "
        "STORED AS TEXTFILE "
        "LOCATION 's3://dat-prod-user-space/alice/sales/2026/' "
        "TBLPROPERTIES ('portal.managed'='true', 'skip.header.line.count'='1', "
        "'projection.enabled'='true', "
        "'projection.year.type'='integer', 'projection.year.range'='2000,2100', 'projection.year.digits'='4', "
        "'projection.month.type'='integer', 'projection.month.range'='1,12', 'projection.month.digits'='2')"
    )


def test_partitioned_json_date_projection():
    keys = [{"name": "dt", "type": "date", "range": ["2020-01-01", "2025-12-31"], "format": "yyyy-MM-dd"}]
    ddl = build_create_table_ddl(
        "alice", "events",
        [{"name": "id", "type": "bigint"}, {"name": "payload", "type": "struct<a:string>"}],
        keys, "json", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`events` "
        "(`id` bigint, `payload` struct<a:string>) "
        "PARTITIONED BY (`dt` date) "
        "ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe' STORED AS TEXTFILE "
        "LOCATION 's3://dat-prod-user-space/alice/sales/2026/' "
        "TBLPROPERTIES ('portal.managed'='true', 'projection.enabled'='true', "
        "'projection.dt.type'='date', "
        "'projection.dt.range'='2020-01-01,2025-12-31', 'projection.dt.format'='yyyy-MM-dd')"
    )


def test_string_enum_partition_key():
    keys = [{"name": "region", "type": "string", "values": ["us-east-1", "eu-west-1"]}]
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "id", "type": "bigint"}], keys, "parquet", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`t` (`id` bigint) "
        "PARTITIONED BY (`region` string) "
        "STORED AS PARQUET LOCATION 's3://dat-prod-user-space/alice/sales/2026/' "
        "TBLPROPERTIES ('portal.managed'='true', 'projection.enabled'='true', "
        "'projection.region.type'='enum', "
        "'projection.region.values'='us-east-1,eu-west-1')"
    )


def test_a_column_comment_is_rendered_and_escaped():
    """SPEC-144: a rebuild carries the comment forward, so the builder has to emit one.

    The create path never sets a comment — inference has nothing to say about what a column
    MEANS — so every golden string above is unaffected, which is the point.
    """
    ddl = build_create_table_ddl(
        "alice", "t",
        [{"name": "id", "type": "bigint", "comment": "the shop's own id"},
         {"name": "plain", "type": "string"}],
        [], "parquet", LOC,
    )

    assert "`id` bigint COMMENT 'the shop\\'s own id'" in ddl
    assert "`plain` string," in ddl or "`plain` string)" in ddl


def test_data_column_colliding_with_partition_key_is_dropped():
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100]}]
    ddl = build_create_table_ddl(
        "alice", "t",
        [{"name": "year", "type": "bigint"}, {"name": "id", "type": "bigint"}],
        keys, "parquet", LOC,
    )
    # `year` appears only in PARTITIONED BY, not the body.
    assert "(`id` bigint)" in ddl
    assert "`year` bigint" not in ddl
    assert "PARTITIONED BY (`year` int)" in ddl


# ── The storage override (SPEC-111) ──────────────────────────────────────────


def test_storage_override_replaces_the_clause_and_its_properties():
    """An injected Storage wins over the format default, properties included."""
    hive_json = Storage("ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe'")
    ddl = build_create_table_ddl(
        "alice", "dq_tmp_abc", [{"name": "id", "type": "string"}], [], "json", LOC,
        storage=hive_json,
    )
    assert "org.apache.hive.hcatalog.data.JsonSerDe" in ddl
    # The default OpenX serde must be GONE, not merely accompanied — data-quality's
    # whole JSON story depends on the Hive serde being the one that reads the file.
    assert "openx" not in ddl.lower()


def test_storage_override_can_drop_the_csv_header_skip():
    """A CSV-shaped storage with no properties emits no TBLPROPERTIES at all.

    This is the raw-line table's requirement (SPEC-111 FR-002): it must read EVERY
    physical line including the header, so inheriting the format default's
    skip.header.line.count=1 would silently drop a row from the ragged-row count.
    """
    raw = Storage(
        "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe' "
        "WITH SERDEPROPERTIES ('field.delim'='\\001') STORED AS TEXTFILE"
    )
    ddl = build_create_table_ddl(
        "alice", "dq_tmp_raw_abc", [{"name": "line", "type": "string"}], [], "csv", LOC,
        storage=raw, mark=False,
    )
    assert "skip.header.line.count" not in ddl
    assert "TBLPROPERTIES" not in ddl
    assert ddl.endswith("LOCATION 's3://dat-prod-user-space/alice/sales/2026/'")


def test_storage_override_still_gets_projection_properties():
    """An override replaces the FORMAT props, not the partition-projection props."""
    raw = Storage("STORED AS TEXTFILE")
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "line", "type": "string"}],
        [{"name": "region", "type": "string", "values": ["eu", "us"]}],
        "csv", LOC, storage=raw,
    )
    assert "'projection.enabled'='true'" in ddl
    assert "'projection.region.values'='eu,us'" in ddl
    assert "skip.header.line.count" not in ddl


# ── The creation marker (SPEC-143 FR-007) ────────────────────────────────────


def test_every_table_builder_format_is_marked_exactly_once():
    """Once, not twice: the marker leads the property list and the projection props are
    appended after it, so a second copy would mean the two paths both added one."""
    for fmt in ("parquet", "csv", "json"):
        ddl = build_create_table_ddl(
            "alice", "t", [{"name": "id", "type": "bigint"}],
            [{"name": "region", "type": "string", "values": ["eu", "us"]}], fmt, LOC,
        )

        assert ddl.count("'portal.managed'='true'") == 1, fmt


def test_the_marker_does_not_disturb_the_properties_that_change_behaviour():
    """It is a record, not a setting — the CSV header skip and the projection props must
    read exactly as they did before it existed."""
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "id", "type": "string"}],
        [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}], "csv", LOC,
    )

    assert "'skip.header.line.count'='1'" in ddl
    assert "'projection.enabled'='true'" in ddl
    assert "'projection.year.range'='2000,2100'" in ddl
    assert "'projection.year.digits'='4'" in ddl


def test_opting_out_is_what_leaves_a_table_unmarked_not_supplying_a_storage():
    """THE DISTINCTION THIS ARGUMENT EXISTS FOR, and it is not hypothetical.

    Inferring "unmarked" from `storage is not None` reads correctly against today's two
    callers — table-builder omits it, data-quality supplies one — and is wrong for the
    next: SPEC-144's `apply-refresh` supplies a Storage rebuilt from the live table. Under
    the inferred rule, every table a refresh touched would come back UNMARKED, silently
    erasing the record FR-007 exists to create, on exactly the tables most likely to be
    asked about.

    So the two are asserted apart: a supplied storage is still marked, and only an
    explicit opt-out is not.
    """
    hive_json = Storage("ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe'")
    args = ("alice", "t", [{"name": "id", "type": "string"}], [], "json", LOC)

    assert "'portal.managed'='true'" in build_create_table_ddl(*args, storage=hive_json)
    assert "portal.managed" not in build_create_table_ddl(*args, storage=hive_json, mark=False)
    assert "portal.managed" not in build_create_table_ddl(*args, mark=False)


def test_mark_managed_asserts_the_marker_without_disturbing_anything_else():
    """SPEC-149's door onto the marker for a caller that writes Glue ``Parameters`` rather
    than DDL (``apply-refresh``). It lives here so the marker keeps exactly two homes — a
    verb that can NAME it is a verb that can branch on it, which SPEC-143 FR-007 forbids.

    A COPY, asserted: the caller's dict is usually the LIVE table's parameters, and mutating
    it would edit the definition the verb is still reading from.
    """
    from cpcommon.ddl import mark_managed

    live = {"EXTERNAL": "TRUE", "skip.header.line.count": "1"}
    marked = mark_managed(live)

    assert marked["portal.managed"] == "true"
    assert marked["EXTERNAL"] == "TRUE"
    assert marked["skip.header.line.count"] == "1"
    assert "portal.managed" not in live

    # An existing (or user-tampered) value is overwritten, not merged around.
    assert mark_managed({"portal.managed": "false"})["portal.managed"] == "true"


def test_data_quality_opts_its_temp_tables_out():
    """Read from the caller, not restated here: a temp table dropped at the end of the same
    run must not carry a durable "the portal manages this" claim."""
    import ast

    # Read from disk rather than imported: the data-quality layer root is only on sys.path
    # under `pytest lambdas/`, and this file is also meant to run standalone.
    path = os.path.join(
        os.path.dirname(_HERE), "data-quality-common", "dqcommon", "sql.py"
    )
    with open(path) as handle:
        tree = ast.parse(handle.read())

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func).endswith("build_create_table_ddl")
    ]

    assert calls, "no build_create_table_ddl calls found — the scan went stale"
    for call in calls:
        opts_out = [k for k in call.keywords if k.arg == "mark" and k.value.value is False]
        assert opts_out, f"a data-quality temp table is marked portal.managed (line {call.lineno})"


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










def test_default_storage_rejects_an_unknown_format():
    """A typo must not yield a table with no storage clause."""
    try:
        default_storage("avro")
    except ValueError as exc:
        assert "avro" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown format")


def test_unknown_format_still_raises_when_no_storage_is_supplied():
    """The pre-move behaviour: build_create_table_ddl surfaces the bad format."""
    try:
        build_create_table_ddl("alice", "t", [{"name": "id", "type": "bigint"}], [], "avro", LOC)
    except ValueError as exc:
        assert "avro" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown format")


def test_quote_backticks_an_identifier():
    assert quote("dq_tmp_7f3a") == "`dq_tmp_7f3a`"


def test_quote_dml_double_quotes_an_identifier():
    """Athena's two dialects: DDL is Hive (backticks), DML is Trino (double quotes).

    Using the wrong one fails AT QUERY TIME, not at build time — after the temp tables
    exist and the scan has been paid for.
    """
    assert quote_dml("dq_tmp_7f3a") == '"dq_tmp_7f3a"'
    assert "`" not in quote_dml("dq_tmp_7f3a")


def test_quote_dml_escapes_an_embedded_double_quote():
    """A CSV header can contain anything. Unescaped, this ends the identifier early and
    the rest of the name is parsed as SQL."""
    assert quote_dml('he said "hi"') == '"he said ""hi"""'


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


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


def test_a_partition_segment_with_an_apostrophe_renders_rather_than_breaking_the_ddl():
    """Data-quality's path: partition values come from S3 key segments, so this is the
    case that turned a whole check into query_failed."""
    keys = [{"name": "year", "type": "string", "values": ["2024'"]}]
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "amount", "type": "string"}], keys, "csv", LOC
    )

    assert "'projection.year.values'='2024\\''" in ddl


def test_a_non_string_enum_value_raises_a_validation_error_not_a_typeerror():
    """",".join over a non-string raises a bare TypeError from inside the renderer, which
    the user is told about as "something went wrong"."""
    keys = [{"name": "region", "type": "string", "values": ["eu", 7]}]

    with pytest.raises(ValueError, match="must be a string"):
        build_create_table_ddl(
            "alice", "t", [{"name": "amount", "type": "string"}], keys, "csv", LOC
        )


def test_both_interval_unit_spellings_render_the_projection_property():
    """The browser's type declares `intervalUnit`; this renderer has always read
    `interval.unit`. The browser's declared field was being silently dropped — latent
    only because no UI path populates it yet (SPEC-151 FR-007)."""
    base = {
        "name": "sale_date",
        "type": "date",
        "range": ["2020-01-01", "2030-01-01"],
        "format": "yyyy-MM-dd",
        "interval": 1,
    }
    cols = [{"name": "amount", "type": "string"}]

    catalog_spelling = build_create_table_ddl(
        "alice", "t", cols, [{**base, "interval.unit": "DAYS"}], "csv", LOC
    )
    browser_spelling = build_create_table_ddl(
        "alice", "t", cols, [{**base, "intervalUnit": "DAYS"}], "csv", LOC
    )

    for ddl in (catalog_spelling, browser_spelling):
        assert "'projection.sale_date.interval'='1'" in ddl
        assert "'projection.sale_date.interval.unit'='DAYS'" in ddl
