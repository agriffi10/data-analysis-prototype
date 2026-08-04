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
    CSV_OPEN_SERDE,
    Storage,
    build_create_table_ddl,
    default_storage,
    quote,
    quote_dml,
    storage_from_definition,
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


def test_a_captured_definition_round_trips_to_the_create_paths_own_storage():
    """FR-004 AC2 — asserted by round trip, not by inspection, because two traps make a
    verbatim re-render silently wrong.

    `CSV_OPEN_SERDE` writes `'escapeChar'='\\\\'` in DDL source; Hive unescapes it, so Glue
    reads the property back as ONE backslash and re-rendering yields `'escapeChar'='\\'` —
    a different statement for the same table. And Parquet's shipped clause is the short
    `STORED AS PARQUET`, while the captured input/output formats render as the long
    `STORED AS INPUTFORMAT … OUTPUTFORMAT …` form: equivalent to Athena, textually
    different. Returning the create path's own Storage sidesteps both.
    """
    for fmt, captured in _CAPTURED.items():
        assert storage_from_definition(captured) == default_storage(fmt), fmt


def test_a_rebuild_reproduces_the_create_paths_statement_for_every_format():
    """The property that matters downstream: one statement, not two that behave alike."""
    columns = [{"name": "id", "type": "bigint"}]
    for fmt, captured in _CAPTURED.items():
        created = build_create_table_ddl("alice", "t", columns, [], fmt, LOC)
        rebuilt = build_create_table_ddl(
            "alice", "t", columns, [], fmt, LOC, storage=storage_from_definition(captured)
        )

        assert rebuilt == created, fmt


def test_a_capture_whose_parameters_diverge_does_not_get_the_shortcut():
    """WHAT MAKES THE ROUND TRIP ABOVE MEAN ANYTHING.

    Matching on the SerDe library alone would rebuild a TAB-separated table with
    `separatorChar=','` — silently redefining how every row of the user's data parses —
    and would rebuild a Hive-JSON table with the OpenX SerDe this module documents as
    potentially non-deterministic around nulls. Both are captures a real refresh can meet:
    the hand-created tables FR-004 explicitly keeps in scope.
    """
    tsv = {**_CAPTURED["csv"], "parameters": {**_CAPTURED["csv"]["parameters"], "separatorChar": "\t"}}
    hive_json = {**_CAPTURED["json"], "serializationLibrary": "org.apache.hive.hcatalog.data.JsonSerDe"}

    assert storage_from_definition(tsv) != default_storage("csv")
    assert "'separatorChar'='\t'" in storage_from_definition(tsv).clause
    assert storage_from_definition(hive_json) != default_storage("json")
    assert "hcatalog" in storage_from_definition(hive_json).clause
    assert "openx" not in storage_from_definition(hive_json).clause.lower()


def test_the_captured_csv_fixture_really_is_what_the_create_path_writes():
    """Guards the fixture itself, which the round trip otherwise takes on trust.

    The escapeChar is the trap: DDL source writes `'escapeChar'='\\\\'`, Hive unescapes
    it, and Glue hands back ONE backslash — so a fixture carrying two would quietly stop
    modelling reality and the round trip would keep passing.
    """
    assert _CAPTURED["csv"]["parameters"]["escapeChar"] == "\\"
    for key, value in _CAPTURED["csv"]["parameters"].items():
        escaped = value.replace("\\", "\\\\")
        assert f"'{key}'='{value}'" in CSV_OPEN_SERDE or f"'{key}'='{escaped}'" in CSV_OPEN_SERDE, key


def test_an_unrecognised_serde_falls_back_to_the_long_rendered_form():
    """A hand-created table can be shape-compatible without using a SerDe this repo
    writes. Rendering it is the only way to reproduce it at all."""
    storage = storage_from_definition(
        {
            "serializationLibrary": "com.example.CustomSerDe",
            "parameters": {"b": "2", "a": "1"},
            "inputFormat": "com.example.In",
            "outputFormat": "com.example.Out",
        }
    )

    assert storage.clause == (
        "ROW FORMAT SERDE 'com.example.CustomSerDe' WITH SERDEPROPERTIES ('a'='1', 'b'='2') "
        "STORED AS INPUTFORMAT 'com.example.In' OUTPUTFORMAT 'com.example.Out'"
    )
    assert storage.tblproperties == ()


def test_if_not_exists_is_present_on_a_create_and_absent_on_a_rebuild():
    columns = [{"name": "id", "type": "bigint"}]

    assert "IF NOT EXISTS" in build_create_table_ddl("alice", "t", columns, [], "parquet", LOC)
    assert "IF NOT EXISTS" not in build_create_table_ddl(
        "alice", "t", columns, [], "parquet", LOC, if_not_exists=False
    )


def test_carried_properties_are_merged_and_never_duplicated():
    """A capture always carries the format's own required property back — CSV's
    skip.header.line.count is both captured AND regenerated — so the merge must collapse
    them rather than emit the key twice inside one TBLPROPERTIES."""
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "id", "type": "string"}], [], "csv", LOC,
        table_properties={"skip.header.line.count": "1", "comment": "kept"},
    )

    assert ddl.count("'skip.header.line.count'=") == 1
    assert "'comment'='kept'" in ddl


def test_a_carried_property_wins_over_the_formats_default():
    """A REBUILD reproduces the table it is replacing, so the capture wins.

    The format default is a guess about a table that does not exist yet; the capture is a
    fact about one that does. A headerless CSV table whose owner set
    skip.header.line.count=0 would otherwise be silently rebuilt with 1 — dropping the
    first row of every file from every query, permanently and invisibly.
    """
    ddl = build_create_table_ddl(
        "alice", "t", [{"name": "id", "type": "string"}], [], "csv", LOC,
        table_properties={"skip.header.line.count": "0"},
    )

    assert "'skip.header.line.count'='0'" in ddl
    assert "'skip.header.line.count'='1'" not in ddl


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
