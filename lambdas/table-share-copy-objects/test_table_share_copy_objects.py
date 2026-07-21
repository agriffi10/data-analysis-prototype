"""Unit tests for the table-share copy-objects Lambda + tscommon.copy (SPEC-091).

Pure logic, AWS stubbed with a recording fake S3. Asserts layout-preserving
destination keys, single-vs-multipart routing at the 5 GiB threshold, part-range
math, abort-on-failure, and the transient/terminal error mapping. Runnable under
pytest or directly: python3 test_table_share_copy_objects.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import table_share_copy_objects as m  # noqa: E402
from cpcommon import clients  # noqa: E402
from tscommon import copy as copy_mod  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402

GIB = 1024**3


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, copy_error=None, part_error=None):
        self.copies = []
        self.multipart = []
        self.aborted = []
        self.copy_error = copy_error
        self.part_error = part_error
        self._uploads = 0

    def copy_object(self, **kwargs):
        if self.copy_error:
            raise self.copy_error
        self.copies.append(kwargs)

    def create_multipart_upload(self, **kwargs):
        self._uploads += 1
        return {"UploadId": f"u{self._uploads}"}

    def upload_part_copy(self, **kwargs):
        if self.part_error:
            raise self.part_error
        self.multipart.append(kwargs)
        return {"CopyPartResult": {"ETag": f"etag-{kwargs['PartNumber']}"}}

    def complete_multipart_upload(self, **kwargs):
        self.multipart.append({"complete": kwargs})

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs)


def _setup(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _event(objects):
    # The plan travels by POINTER now (tscommon.copy_plan): inline, the object list pushed
    # the Map's state to 95% of Step Functions' 256 KB payload limit. The verb loads it, so
    # the fixture stubs the load rather than putting the list on the state.
    m.copy_plan.load = lambda key: objects
    return {
        "recipient": {
            "kind": "user",
            "name": "bob",
            "valid": True,
            "database": "bob",
            "destBucket": "user-bkt",
            "destPrefix": "bob/shared_tables/orders_copy/",
        },
        "request": {
            "tableName": "orders_copy",
            "location": {"bucket": "user-bkt", "prefix": "alice/sales/"},
            "copyPlanKey": "table-share/h/copy-plan.json",
        },
    }


def test_copies_every_object_layout_preserved():
    fake = _setup()
    out = m.handler(
        _event([
            {"relKey": "part-0.parquet", "size": 100},
            {"relKey": "year=2025/part-1.parquet", "size": 50},
        ]),
        None,
    )
    assert out["copiedObjects"] == 2
    assert sorted((c["CopySource"]["Key"], c["Key"]) for c in fake.copies) == [
        ("alice/sales/part-0.parquet", "bob/shared_tables/orders_copy/part-0.parquet"),
        ("alice/sales/year=2025/part-1.parquet", "bob/shared_tables/orders_copy/year=2025/part-1.parquet"),
    ]
    assert fake.multipart == []  # small objects: single CopyObject only


def test_large_object_uses_multipart_ranges():
    fake = _setup()
    size = 5 * GIB + 512  # just over the single-copy limit
    m.handler(_event([{"relKey": "big.parquet", "size": size}]), None)
    assert fake.copies == []
    parts = [c for c in fake.multipart if "PartNumber" in c]
    complete = [c for c in fake.multipart if "complete" in c]
    assert len(parts) == 6  # 5 full GiB parts + the 512-byte tail
    assert parts[0]["CopySourceRange"] == f"bytes=0-{GIB - 1}"
    assert parts[-1]["CopySourceRange"] == f"bytes={5 * GIB}-{size - 1}"
    assert len(complete) == 1
    assert [p["PartNumber"] for p in complete[0]["complete"]["MultipartUpload"]["Parts"]] == [1, 2, 3, 4, 5, 6]


def test_failed_multipart_aborts_the_upload():
    fake = _setup(part_error=_S3Error("AccessDenied"))
    try:
        m.handler(_event([{"relKey": "big.parquet", "size": 6 * GIB}]), None)
    except TerminalError as exc:
        assert exc.reason == "copy_failed"
        assert len(fake.aborted) == 1
        return
    raise AssertionError("expected TerminalError(copy_failed)")


def test_throttle_is_transient():
    _setup(copy_error=_S3Error("SlowDown"))
    try:
        m.handler(_event([{"relKey": "a.parquet", "size": 1}]), None)
    except TransientError:
        return
    raise AssertionError("expected TransientError")


def test_deterministic_failure_is_copy_failed():
    _setup(copy_error=_S3Error("AccessDenied"))
    try:
        m.handler(_event([{"relKey": "a.parquet", "size": 1}]), None)
    except TerminalError as exc:
        assert exc.reason == "copy_failed"
        return
    raise AssertionError("expected TerminalError(copy_failed)")


def test_copy_prefix_bounds_concurrency():
    # Sanity: the pool accepts a custom bound and still copies everything.
    fake = _setup()
    n = copy_mod.copy_prefix(
        "user-bkt",
        "alice/sales/",
        [{"relKey": f"p{i}.parquet", "size": 1} for i in range(20)],
        "user-bkt",
        "bob/shared_tables/orders_copy/",
        concurrency=2,
    )
    assert n == 20 and len(fake.copies) == 20


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
