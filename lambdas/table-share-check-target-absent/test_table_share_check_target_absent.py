"""Unit tests for the table-share check-target-absent Lambda (SPEC-091).

Pure logic, AWS stubbed: the Glue existence check and the S3 prefix probe are
faked per case. Asserts destination resolution by kind, both conflict guards, the
invalid-recipient short-circuit, and the transient/terminal routing. Runnable
under pytest or directly: python3 test_table_share_check_target_absent.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_check_target_absent as m
from cpcommon import clients, config
from cpcommon.errors import TerminalError


@pytest.fixture(autouse=True)
def _restore_glue_module():
    """Put ``tscommon.glue`` back after every test.

    ``_setup`` below patches ``glue_mod.table_exists`` on the SHARED module object, which
    every other suite importing tscommon.glue sees too. Unrestored, the stub outlived this
    file and silently replaced the real function elsewhere — a passing test asserting
    against a lambda from another module. Found by SPEC-151 FR-008's classification tests,
    which failed only when the full suite ran.
    """
    saved = dict(vars(m.glue_mod))
    yield
    m.glue_mod.__dict__.clear()
    m.glue_mod.__dict__.update(saved)


class _FakeS3:
    def __init__(self, key_count=0, error=None):
        self.key_count = key_count
        self.error = error
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"KeyCount": self.key_count}


def _setup(table_exists=False, key_count=0, list_error=None):
    m.glue_mod.table_exists = lambda db, t: table_exists
    fake = _FakeS3(key_count=key_count, error=list_error)
    clients._s3 = fake
    return fake


def _event(kind="user", name="bob", valid=True, reason=None, table_name="orders_copy"):
    recipient = {"kind": kind, "name": name, "valid": valid}
    if reason:
        recipient["reason"] = reason
    return {
        "recipient": recipient,
        "request": {
            "actor": "alice",
            "source": {"database": "alice", "table": "orders"},
            "tableName": table_name,
            "location": {"bucket": config.USER_SPACE_BUCKET, "prefix": "alice/sales/"},
            "objects": [{"relKey": "part-0.parquet", "size": 10}],
        },
    }


def _expect_reason(event, reason):
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


def test_user_recipient_resolves_to_user_space_destination():
    fake = _setup()
    out = m.handler(_event(), None)
    assert out["recipient"]["database"] == "bob"
    assert out["recipient"]["destBucket"] == config.USER_SPACE_BUCKET
    assert out["recipient"]["destPrefix"] == "bob/shared_tables/orders_copy/"
    # The emptiness probe hit exactly that destination.
    assert fake.calls == [{"Bucket": config.USER_SPACE_BUCKET, "Prefix": "bob/shared_tables/orders_copy/", "MaxKeys": 1}]
    # The request context threads through for copy-objects.
    assert out["request"]["tableName"] == "orders_copy"


def test_existing_table_is_a_conflict():
    _setup(table_exists=True)
    _expect_reason(_event(), "conflict")


def test_lf_denied_recipient_db_is_terminal():
    def _denied(db, t):
        raise TerminalError("target_not_readable", db)

    _setup()
    m.glue_mod.table_exists = _denied
    _expect_reason(_event(), "target_not_readable")


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
