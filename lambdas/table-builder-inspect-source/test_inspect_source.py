"""Unit tests for the table-builder inspect-source Lambda.

The classification logic is tested by stubbing s3_listing.list_data_objects with a
canned object list (no S3). The shared ignore rules + paginated lister are tested
directly against a fake S3 paginator.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))


import inspect_source as i
from cpcommon import s3_listing
from cpcommon.errors import TerminalError

BUCKET = "dat-prod-user-space"
PREFIX = "alice/sales/2026/"

# The real lister, captured before any test stubs the module attribute.
_REAL_LIST = s3_listing.list_data_objects


def _stub_objects(objects):
    """Stub the lister with (key, size) tuples (size defaults to 10 when just a key)."""
    normed = [(o, 10) if isinstance(o, str) else o for o in objects]
    s3_listing.list_data_objects = lambda bucket, prefix: iter(normed)


def _event(partition_keys=None, prefix=PREFIX):
    return {
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": prefix, "database": "alice"},
        "tableName": "sales_2026",
        "partitionKeys": partition_keys or [],
        "location": f"s3://{BUCKET}/{prefix}",
        "requestId": "r1",
    }


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


def test_mixed_formats_is_terminal():
    _stub_objects([PREFIX + "a.parquet", PREFIX + "b.csv"])
    _expect_reason(_event(), "mixed_formats")


# Fake S3 paginator backing the ignore-rules test above.
