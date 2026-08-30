"""Unit tests for tscommon.copy_plan — the object list, passed by pointer.

Runnable under pytest or directly: python3 test_copy_plan_tscommon.py.
"""

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from tscommon import copy_plan

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

    def put_object(self, Bucket, Key, Body, **kw):
        if self.error:
            raise self.error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.store[Key] = Body
        return {}

    def get_object(self, Bucket, Key):
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


@pytest.mark.parametrize(
    "source",
    [
        {"database": "alice", "table": "invoices"},   # same db, different table
        {"database": "salesteam", "table": "orders"},  # DIFFERENT DATABASE
    ],
)
def test_a_different_source_gets_a_different_key(source):
    """The database must be in the digest, and this is the case that matters most.

    Two shares of different DATABASES are in different FIFO message groups, so they run
    genuinely in parallel — and their plans list DIFFERENT prefixes. If the digest ignored
    the database, one execution would copy another table's file list into its recipients,
    under a name matching the wrong source. Every other collision is same-prefix and
    therefore content-equivalent; this one is not.
    """
    assert copy_plan.plan_key({**REQUEST, "source": source}) != copy_plan.plan_key(REQUEST)


def test_the_key_sits_under_the_prefix_the_infra_contracts_name():
    """Asserted against the LITERAL, not against copy_plan.PREFIX — comparing the key to the
    module's own constant is a tautology that passes however the constant is edited.

    Two external contracts hard-code this prefix and neither is visible from here:
    analytics/s3.tf's expire-table-share-copy-plans lifecycle filter (`table-share/`) and the
    CopyPlanReadWrite IAM resource (`.../table-share/*`). Drift means plans are never expired
    AND every write gets AccessDenied at runtime.
    """
    assert copy_plan.plan_key(REQUEST).startswith("table-share/")


def test_the_prefix_matches_what_the_iam_grant_and_lifecycle_rule_use():
    """Read from infra/ so the three cannot drift apart silently."""
    here = os.path.dirname(os.path.abspath(__file__))
    policy = Path(here, "..", "..", "infra", "modules", "table-share",
                  "policies", "execution.json.tftpl").read_text(encoding="utf-8")
    lifecycle = Path(here, "..", "..", "infra", "modules", "analytics", "s3.tf").read_text(
        encoding="utf-8"
    )

    assert f"/{copy_plan.PREFIX}/*" in policy, "IAM grant does not cover the plan prefix"
    assert f'prefix = "{copy_plan.PREFIX}/"' in lifecycle, "lifecycle rule does not expire the plan prefix"


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


# ── the cloned definition, on the same pointer discipline (SPEC-161 FR-002) ──

DEFINITION = {
    "columns": [{"name": "id", "type": "bigint"}],
    "partitionKeys": [],
    "tableType": "EXTERNAL_TABLE",
    "tableProperties": {},
}


def test_the_definition_key_is_a_pure_function_of_the_request():
    """It shares the PLAN's key discipline, not the manifest's, and that is the whole choice.

    The definition is a clone of the source table, and the digest already covers the source
    database and table — so two overlapping executions write byte-identical content. The
    manifest cannot say that, which is why it alone is execution-unique.
    """
    assert copy_plan.definition_key(REQUEST) == copy_plan.definition_key(dict(REQUEST))
    assert copy_plan.definition_key(REQUEST) != copy_plan.plan_key(REQUEST)


def test_the_definition_key_sits_under_the_same_prefix_the_contracts_name():
    """Asserted against the LITERAL — the IAM grant and the lifecycle rule both hard-code it,
    and neither is visible from here. Sharing the prefix is why this spec adds no new rule."""
    assert copy_plan.definition_key(REQUEST).startswith("table-share/")
    assert copy_plan.definition_key(REQUEST).endswith("/definition.json")


def test_definition_write_then_load_round_trips(_fake_s3):
    key = copy_plan.write_definition(REQUEST, DEFINITION)

    assert copy_plan.load_definition(key) == DEFINITION
    assert _fake_s3.puts[0]["Bucket"] == "admin-bkt"  # the ADMIN bucket, not a user space


def test_a_definition_replay_overwrites_the_same_object(_fake_s3):
    first = copy_plan.write_definition(REQUEST, DEFINITION)
    second = copy_plan.write_definition(REQUEST, DEFINITION)

    assert first == second
    assert len({(p["Bucket"], p["Key"]) for p in _fake_s3.puts}) == 1


def test_a_throttled_definition_write_is_transient(_fake_s3):
    _fake_s3.error = _FakeClientError("SlowDown")

    with pytest.raises(TransientError):
        copy_plan.write_definition(REQUEST, DEFINITION)


def test_a_throttled_definition_read_is_transient(_fake_s3):
    _fake_s3.error = _FakeClientError("SlowDown")

    with pytest.raises(TransientError):
        copy_plan.load_definition("table-share/h/definition.json")


def test_a_missing_definition_is_terminal_for_that_recipient(_fake_s3):
    with pytest.raises(TerminalError) as excinfo:
        copy_plan.load_definition("table-share/nope/definition.json")

    assert excinfo.value.reason == "definition_unreadable"


@pytest.mark.parametrize(
    "payload", [b"{not json", b"[]", b"{}", b'{"columns": []}', b'{"columns": null}']
)
def test_an_unusable_definition_is_terminal_not_an_empty_table(_fake_s3, payload):
    """A definition with no columns renders a CREATE Athena ACCEPTS — over the recipient's
    freshly-copied data. That table reads as a success and returns nothing, which is why every
    unusable shape raises here rather than being handed on."""
    _fake_s3.body = payload

    with pytest.raises(TerminalError) as excinfo:
        copy_plan.load_definition("table-share/h/definition.json")

    assert excinfo.value.reason == "definition_unreadable"


def test_the_definition_is_written_compactly(_fake_s3):
    """Read once per recipient, up to SHARE_MAX_RECIPIENTS times, at up to the size cap."""
    copy_plan.write_definition(REQUEST, DEFINITION)

    assert b", " not in _fake_s3.puts[0]["Body"]
    assert json.loads(_fake_s3.puts[0]["Body"]) == DEFINITION


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
