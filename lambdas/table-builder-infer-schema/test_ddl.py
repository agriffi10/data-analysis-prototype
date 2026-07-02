"""Golden-string tests for the pure DDL generator.

No AWS / polars — asserts the exact generated CREATE EXTERNAL TABLE for flat
Parquet, partitioned CSV (integer projection + OpenCSVSerde all-string), partitioned
JSON, and a string enum partition key. Runnable under pytest or directly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ddl import build_create_table_ddl  # noqa: E402

LOC = "s3://dat-prod-user-space/alice/sales/2026/"


def test_flat_parquet_no_partitions():
    ddl = build_create_table_ddl(
        "alice", "sales_2026",
        [{"name": "order_id", "type": "bigint"}, {"name": "amount", "type": "double"}],
        [], "parquet", LOC,
    )
    assert ddl == (
        "CREATE EXTERNAL TABLE IF NOT EXISTS `alice`.`sales_2026` "
        "(`order_id` bigint, `amount` double) "
        "STORED AS PARQUET LOCATION 's3://dat-prod-user-space/alice/sales/2026/'"
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
        "TBLPROPERTIES ('skip.header.line.count'='1', 'projection.enabled'='true', "
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
        "TBLPROPERTIES ('projection.enabled'='true', 'projection.dt.type'='date', "
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
        "TBLPROPERTIES ('projection.enabled'='true', 'projection.region.type'='enum', "
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
