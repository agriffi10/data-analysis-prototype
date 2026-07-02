"""Unit tests for the table-builder inspect-source Lambda.

The classification logic is tested by stubbing s3_listing.list_data_objects with a
canned object list (no S3). The shared ignore rules + paginated lister are tested
directly against a fake S3 paginator. Runnable under pytest or directly:
python3 test_inspect_source.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import json  # noqa: E402
import inspect_source as i  # noqa: E402
from tbcommon import clients, config, s3_listing  # noqa: E402
from tbcommon.errors import TerminalError  # noqa: E402


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


BUCKET = "dat-prod-user-space"
PREFIX = "alice/sales/2026/"

# The real lister, captured before any test stubs the module attribute.
_REAL_LIST = s3_listing.list_data_objects


def _stub_objects(objects):
    """Stub the lister with (key, size) tuples (size defaults to 10 when just a key)."""
    normed = [(o, 10) if isinstance(o, str) else o for o in objects]
    s3_listing.list_data_objects = lambda bucket, prefix: iter(normed)


def _event(partition_keys=None, prefix=PREFIX):
    ev = {
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": prefix, "database": "alice"},
        "tableName": "sales_2026",
        "partitionKeys": partition_keys or [],
        "location": f"s3://{BUCKET}/{prefix}",
        "requestId": "r1",
    }
    return ev


def _keys(*names):
    return [{"name": n, "type": "integer", "range": [0, 9], "digits": 2} for n in names]


def _expect_reason(event, reason):
    try:
        i.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


def test_flat_parquet_folder_passes():
    _stub_objects([PREFIX + "part-0.parquet", PREFIX + "part-1.parquet"])
    out = i.handler(_event(), None)
    assert out["format"] == "parquet"
    assert out["partitioned"] is False
    assert out["fileCount"] == 2
    assert out["sampleObjectKey"] == PREFIX + "part-0.parquet"
    assert out["location"] == f"s3://{BUCKET}/{PREFIX}"
    # request carried through unchanged
    assert out["partitionKeys"] == []
    assert out["tableName"] == "sales_2026"


def test_partitioned_csv_matching_declared_keys_passes():
    _stub_objects([
        PREFIX + "year=2026/month=01/part-0.csv",
        PREFIX + "year=2026/month=02/part-0.csv",
    ])
    out = i.handler(_event(partition_keys=_keys("year", "month")), None)
    assert out["format"] == "csv"
    assert out["partitioned"] is True
    assert out["fileCount"] == 2
    assert out["sampleObjectKey"].endswith("year=2026/month=01/part-0.csv")
    assert [k["name"] for k in out["partitionKeys"]] == ["year", "month"]


def test_json_variants_are_one_format():
    _stub_objects([PREFIX + "a.json", PREFIX + "b.ndjson", PREFIX + "c.jsonl"])
    out = i.handler(_event(), None)
    assert out["format"] == "json"
    assert out["fileCount"] == 3


def test_marker_results_and_hidden_files_are_ignored_by_helper():
    # Exercise the real ignore rules through a fake paginator (below), not the stub.
    pages = [{"Contents": [
        {"Key": PREFIX + "DO_NOT_DELETE.txt", "Size": 0},
        {"Key": PREFIX + "athenaresults/query.csv", "Size": 100},
        {"Key": PREFIX + "_SUCCESS", "Size": 0},
        {"Key": PREFIX + ".hidden.parquet", "Size": 100},
        {"Key": PREFIX + "placeholder/", "Size": 0},
        {"Key": PREFIX + "empty.parquet", "Size": 0},
        {"Key": PREFIX + "real.parquet", "Size": 100},
    ]}]
    s3_listing.list_data_objects = _REAL_LIST  # undo any prior stub
    clients._s3 = _FakePaginatedS3(pages)
    got = list(s3_listing.list_data_objects(BUCKET, PREFIX))
    assert got == [(PREFIX + "real.parquet", 100)]


def test_mixed_formats_is_terminal():
    _stub_objects([PREFIX + "a.parquet", PREFIX + "b.csv"])
    _expect_reason(_event(), "mixed_formats")


def test_no_data_files_is_terminal():
    _stub_objects([])
    _expect_reason(_event(), "no_data_files")


def test_only_unsupported_is_terminal_unsupported_format():
    _stub_objects([PREFIX + "a.orc", PREFIX + "b.avro"])
    _expect_reason(_event(), "unsupported_format")


def test_flat_request_but_nested_data_is_unexpected_partitioning():
    _stub_objects([PREFIX + "year=2026/part-0.parquet"])
    _expect_reason(_event(), "unexpected_partitioning")


def test_declared_key_missing_from_path_is_mismatch():
    _stub_objects([PREFIX + "year=2026/part-0.csv"])
    _expect_reason(_event(partition_keys=_keys("year", "month")), "partition_layout_mismatch")


def test_declared_keys_out_of_order_is_mismatch():
    _stub_objects([PREFIX + "month=01/year=2026/part-0.csv"])
    _expect_reason(_event(partition_keys=_keys("year", "month")), "partition_layout_mismatch")


def test_extra_undeclared_segment_is_mismatch():
    _stub_objects([PREFIX + "year=2026/month=01/day=05/part-0.csv"])
    _expect_reason(_event(partition_keys=_keys("year", "month")), "partition_layout_mismatch")


def test_notifies_actor_on_a_terminal_reason():
    _stub_objects([PREFIX + "a.parquet", PREFIX + "b.csv"])  # mixed_formats
    q = _arm_notifications()
    try:
        i.handler(_event(), None)
    except TerminalError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:inspect"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body["username"] == "alice"
    assert body["message"] == 'Couldn\'t create table "sales_2026": the folder mixes file formats - use a single format.'


def test_no_notification_on_success():
    _stub_objects([PREFIX + "part-0.parquet"])
    q = _arm_notifications()
    i.handler(_event(), None)
    assert q.calls == []


# Fake S3 paginator backing the ignore-rules test above.
class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 kwarg names
        return iter(self._pages)


class _FakePaginatedS3:
    def __init__(self, pages):
        self._pages = pages

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _FakePaginator(self._pages)


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
