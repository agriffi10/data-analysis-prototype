"""Unit tests for the table-builder notification message map.

Pure functions — no AWS. Runnable under pytest or directly: python3 test_messages.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tbcommon import messages  # noqa: E402


def test_access_denied_reasons_share_one_message_and_hide_the_name():
    for reason in ("unauthorized", "forbidden"):
        msg = messages.failure_message(reason, table_name="orders", database="sales")
        assert msg == "You don't have access to create a table here."
        assert "orders" not in msg


def test_invalid_table_name_names_the_table():
    msg = messages.failure_message("invalid_table_name", table_name="Bad Name")
    assert msg == 'Couldn\'t create table "Bad Name": the name isn\'t a valid table name.'


def test_invalid_partition_keys():
    msg = messages.failure_message("invalid_partition_keys", table_name="orders")
    assert msg.startswith('Couldn\'t create table "orders": the partition keys aren\'t valid')


def test_table_exists_names_the_database():
    msg = messages.failure_message("table_exists", table_name="orders", database="sales")
    assert msg == 'Couldn\'t create table "orders": a table with that name already exists in "sales".'


def test_inspect_reasons():
    cases = {
        "no_data_files": "no supported data files were found in that folder.",
        "mixed_formats": "the folder mixes file formats - use a single format.",
        "unsupported_format": "that file format isn't supported (use Parquet, CSV, or JSON).",
        "unexpected_partitioning": "the folder is partitioned but no partition keys were provided.",
        "partition_layout_mismatch": "the partition keys don't match the folder layout (check names and order).",
    }
    for reason, tail in cases.items():
        assert messages.failure_message(reason, table_name="orders") == f'Couldn\'t create table "orders": {tail}'


def test_schema_reasons_share_the_read_message():
    for reason in ("schema_inference_failed", "unmappable_type"):
        msg = messages.failure_message(reason, table_name="orders")
        assert msg == 'Couldn\'t create table "orders": the data schema couldn\'t be read.'


def test_ddl_failure_folds_in_the_detail():
    with_detail = messages.failure_message("ddl_execution_failed", table_name="orders", detail="SYNTAX_ERROR")
    assert with_detail == 'Couldn\'t create table "orders": creating the table failed (SYNTAX_ERROR).'
    without = messages.failure_message("ddl_timeout", table_name="orders")
    assert without == 'Couldn\'t create table "orders": creating the table failed.'


def test_unknown_reason_falls_back_without_leaking_the_code():
    msg = messages.failure_message("some_new_reason", table_name="orders")
    assert "some_new_reason" not in msg
    assert msg.startswith('Couldn\'t create table "orders":')


def test_missing_table_name_uses_a_placeholder():
    assert 'your table' in messages.failure_message("no_data_files", table_name="")


def test_success_message():
    assert messages.success_message("orders", "sales") == 'Table "orders" is ready to query in "sales".'


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
