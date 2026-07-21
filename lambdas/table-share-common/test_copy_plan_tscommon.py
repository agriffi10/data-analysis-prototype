"""Unit tests for tscommon.copy_plan — the object list, passed by pointer.

Runnable under pytest or directly: python3 test_copy_plan_tscommon.py.
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest  # noqa: E402

from cpcommon import clients  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402
from tscommon import copy_plan  # noqa: E402

REQUEST = {
    "actor": "alice",
    "source": {"database": "alice", "table": "orders"},
    "tableName": "orders_copy",
}
OBJECTS = [{"relKey": "part-0.parquet", "size": 100}, {"relKey": "part-1.parquet", "size": 200}]


class _FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeS3:
    def __init__(self, objects=None, error=None, body=None):
        self.store = {}
        self.error = error
        self.body = body
        self.puts = []

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
        if self.error:
            raise self.error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.store[Key] = Body
        return {}

    def get_object(self, Bucket, Key):  # noqa: N803
        if self.error:
            raise self.error
        if self.body is not None:
            return {"Body": io.BytesIO(self.body)}
        if Key not in self.store:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.store[Key])}


@pytest.fixture(autouse=True)
def _fake_s3():
    fake = _FakeS3()
    clients._s3 = fake
    yield fake
    clients._s3 = None


def test_the_key_is_a_pure_function_of_the_request():
    """Replay safety: a Step Functions Retry of inspect-source must rewrite the SAME key
    rather than leave a second plan behind. Table-share has no requestId, so the key is a
    digest of the fields that identify the share."""
    assert copy_plan.plan_key(REQUEST) == copy_plan.plan_key(dict(REQUEST))


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor", "bob"),
        ("tableName", "something_else"),
    ],
)
def test_a_different_request_gets_a_different_key(field, value):
    assert copy_plan.plan_key({**REQUEST, field: value}) != copy_plan.plan_key(REQUEST)


def test_a_different_source_gets_a_different_key():
    other = {**REQUEST, "source": {"database": "alice", "table": "invoices"}}

    assert copy_plan.plan_key(other) != copy_plan.plan_key(REQUEST)


def test_the_key_sits_under_the_prefix_the_lifecycle_rule_expires():
    """analytics/s3.tf's expire-table-share-copy-plans filters on this prefix. A key written
    outside it would never be cleaned up."""
    assert copy_plan.plan_key(REQUEST).startswith(f"{copy_plan.PREFIX}/")


def test_write_then_load_round_trips(_fake_s3):
    key = copy_plan.write(REQUEST, OBJECTS)

    assert copy_plan.load(key) == OBJECTS
    assert _fake_s3.puts[0]["Bucket"] == "admin-bkt"  # the ADMIN bucket, not a user space


def test_a_replay_overwrites_the_same_object(_fake_s3):
    first = copy_plan.write(REQUEST, OBJECTS)
    second = copy_plan.write(REQUEST, OBJECTS)

    assert first == second
    assert len({(p["Bucket"], p["Key"]) for p in _fake_s3.puts}) == 1


def test_a_throttled_write_is_transient_so_the_state_machine_retries(_fake_s3):
    _fake_s3.error = _FakeClientError("SlowDown")

    with pytest.raises(TransientError):
        copy_plan.write(REQUEST, OBJECTS)


def test_a_throttled_read_is_transient(_fake_s3):
    _fake_s3.error = _FakeClientError("SlowDown")

    with pytest.raises(TransientError):
        copy_plan.load("table-share/h/copy-plan.json")


def test_a_missing_plan_is_terminal_not_a_silent_empty_copy(_fake_s3):
    """Copying a PARTIAL (or empty) set would hand the recipient a table pointing at an
    incomplete prefix and report success — worse than failing the recipient."""
    with pytest.raises(TerminalError) as excinfo:
        copy_plan.load("table-share/nope/copy-plan.json")

    assert excinfo.value.reason == "copy_failed"


def test_a_corrupt_plan_is_terminal(_fake_s3):
    _fake_s3.body = b"{not json"

    with pytest.raises(TerminalError) as excinfo:
        copy_plan.load("table-share/h/copy-plan.json")

    assert excinfo.value.reason == "copy_failed"


@pytest.mark.parametrize("payload", [b'{"objects": []}', b'{"objects": "nope"}', b"{}"])
def test_a_plan_with_no_usable_objects_is_terminal(_fake_s3, payload):
    """inspect-source rejects an empty source (source_empty), so an empty plan here means
    the OBJECT is wrong — not that there is nothing to copy."""
    _fake_s3.body = payload

    with pytest.raises(TerminalError) as excinfo:
        copy_plan.load("table-share/h/copy-plan.json")

    assert excinfo.value.reason == "copy_failed"


def test_the_plan_is_written_compactly(_fake_s3):
    """It is read once per recipient; whitespace is pure cost at 1000 objects."""
    copy_plan.write(REQUEST, OBJECTS)

    assert b", " not in _fake_s3.puts[0]["Body"]
    assert json.loads(_fake_s3.puts[0]["Body"])["objects"] == OBJECTS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
