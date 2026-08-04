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
