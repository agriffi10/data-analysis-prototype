"""Unit tests for the table-builder apply-refresh Lambda (SPEC-149).

Glue is stubbed by a fake that ACTUALLY APPLIES the update, so the post-condition read sees
what the verb wrote rather than a scripted echo — a fake that answered `get_table` from a
canned list would pass a verification the real catalog could fail.

What this file is really about is FR-002: ``UpdateTable`` replaces the WHOLE definition, so
every field the input omits is CLEARED. Preservation and mutation are therefore asserted
TOGETHER — an input that changed nothing would sail through a preservation-only test.

Runnable under pytest OR directly: ``python3 test_apply_refresh.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "dat-prod-user-space")
os.environ.setdefault("SHARED_SPACE_BUCKET", "dat-prod-shared-space")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import datetime
import pathlib

import apply_refresh as m
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError

BUCKET = "dat-prod-user-space"
LAMBDAS = pathlib.Path(__file__).resolve().parent.parent


class _ClientError(Exception):
    """A botocore-shaped fault: the verb classifies on ``response['Error']['Code']``."""

    def __init__(self, code, message="boom"):
        super().__init__(f"An error occurred ({code}) when calling the UpdateTable operation: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


class _NoAthena:
    """A tripwire. This verb runs no statements, so ANY attribute access is a failure."""

    def __getattr__(self, name):
        raise AssertionError(f"apply-refresh touched the Athena client (.{name})")


def _live_table(**over):
    """A live Glue table as ``GetTable`` reports it — read-only fields and all.

    Deliberately carries the four things FR-002 exists to protect: a ``Description``, an
    ``Owner``, a table ``Parameters`` entry no verb knows about (``classification``), and a
    non-default SerDe parameter (``custom.serde.knob``).
    """
    table = {
        "Name": "sales_2026",
        # ── read-only: Glue reports these but TableInput does not accept them ──
        "DatabaseName": "alice",
        "CreateTime": "2026-01-01T00:00:00Z",
        "UpdateTime": "2026-02-01T00:00:00Z",
        "CreatedBy": "arn:aws:sts::696000197480:assumed-role/table-builder/exec",
        "IsRegisteredWithLakeFormation": True,
        "CatalogId": "696000197480",
        "VersionId": "3",
        # ── the definition proper ──
        "Description": "the shop's quarterly sales",
        "Owner": "alice",
        "TableType": "EXTERNAL_TABLE",
        "Retention": 0,
        "PartitionKeys": [],
        "Parameters": {
            "EXTERNAL": "TRUE",
            "skip.header.line.count": "1",
            "classification": "csv",
            "transient_lastDdlTime": "1770000000",
        },
        "StorageDescriptor": {
            "Location": f"s3://{BUCKET}/alice/sales/",
            "Columns": [{"Name": "order_id", "Type": "string", "Comment": "the shop's own id"}],
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
                "Parameters": {
                    "separatorChar": ",",
                    "quoteChar": '"',
                    "escapeChar": "\\",
                    "custom.serde.knob": "keep-me",
                },
            },
            "Compressed": False,
            "NumberOfBuckets": -1,
            "StoredAsSubDirectories": False,
        },
    }
    table.update(over)
    return table


class _FakeGlue:
    """A catalog that applies what it is told, so the post-condition read is meaningful.

    ``drift`` is how a landed-wrong update is simulated: the read AFTER the update reports
    those column names instead of the ones written.
    """

    def __init__(self, table=None, get_error=None, update_error=None, post_error=None, drift=None):
        self.table = _live_table() if table is None else table
        self.get_error = get_error
        self.update_error = update_error
        self.post_error = post_error
        self.drift = drift
        self.get_calls = []
        self.update_calls = []

    def get_table(self, **kwargs):
        self.get_calls.append(kwargs)
        if self.update_calls and self.post_error is not None:
            raise self.post_error
        if not self.update_calls and self.get_error is not None:
            raise self.get_error
        table = self.table
        if self.update_calls and self.drift is not None:
            storage = {**table["StorageDescriptor"], "Columns": [{"Name": n, "Type": "string"} for n in self.drift]}
            table = {**table, "StorageDescriptor": storage}
        return {"Table": table}

    def update_table(self, **kwargs):
        self.update_calls.append(kwargs)
        if self.update_error is not None:
            raise self.update_error
        self.table = {**self.table, **kwargs["TableInput"]}

    # Tripwires, not stubs. The catalog CAN delete — the point of FR-005/FR-006 is that this
    # verb never asks it to, so calling either is the failure rather than a missing attribute.
    def delete_table(self, **kwargs):
        raise AssertionError(f"apply-refresh called glue.delete_table({kwargs})")

    def batch_delete_table(self, **kwargs):
        raise AssertionError(f"apply-refresh called glue.batch_delete_table({kwargs})")

    @property
    def table_input(self):
        assert self.update_calls, "no update_table call was made"
        return self.update_calls[0]["TableInput"]


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _install(**glue_kwargs):
    glue = _FakeGlue(**glue_kwargs)
    sqs = _FakeSqs()
    clients._glue = glue
    clients._sqs = sqs
    clients._athena = _NoAthena()
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"
    return glue, sqs


def _event(**over):
    event = {
        "mode": "refresh",
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/sales/", "database": "alice"},
        "tableName": "sales_2026",
        "requestId": "r1",
        "format": "csv",
        "location": f"s3://{BUCKET}/alice/sales/",
        "partitionKeys": [],
        "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        "diff": {"changed": True, "added": [{"name": "amount", "type": "string"}], "removed": [], "retyped": [], "unchanged": 1},
    }
    event.update(over)
    return event


def _expect_reason(event, reason, **install):
    _install(**install)
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── One Glue call, no Athena, no delete (FR-001, FR-005) ─────────────────────


def test_the_verb_issues_one_update_and_never_touches_athena():
    """FR-001. The whole mechanism change in one assertion: one Glue write, no statements."""
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert len(glue.update_calls) == 1
    assert glue.update_calls[0]["DatabaseName"] == "alice"
    # Two reads: the modify-write's own read, then the post-condition.
    assert len(glue.get_calls) == 2


# ── FR-002: the read-modify-write ────────────────────────────────────────────


def test_the_table_input_preserves_every_field_a_refresh_does_not_own():
    """THE TEST THAT WOULD HAVE CAUGHT BUILDING FROM SPEC-143's CAPTURE.

    UpdateTable replaces the WHOLE definition, so a field this input omits is CLEARED — and
    the capture carries neither Description nor Owner. All four survive here, or the verb is
    deleting the metadata this spec exists to preserve.
    """
    glue, _sqs = _install()

    m.handler(_event(), None)
    sent = glue.table_input

    assert sent["Description"] == "the shop's quarterly sales"
    assert sent["Owner"] == "alice"
    assert sent["Parameters"]["classification"] == "csv"
    assert sent["StorageDescriptor"]["SerdeInfo"]["Parameters"]["custom.serde.knob"] == "keep-me"
    # Storage fields the refresh has no opinion about ride along untouched.
    assert sent["StorageDescriptor"]["Location"] == f"s3://{BUCKET}/alice/sales/"
    assert sent["StorageDescriptor"]["InputFormat"] == "org.apache.hadoop.mapred.TextInputFormat"


def test_the_read_only_fields_glue_rejects_are_not_sent():
    """A rejected field fails the call; an unstripped one Glue silently accepts is worse."""
    glue, _sqs = _install()

    m.handler(_event(), None)

    for field in (
        "DatabaseName",
        "CreateTime",
        "UpdateTime",
        "CreatedBy",
        "IsRegisteredWithLakeFormation",
        "CatalogId",
        "VersionId",
    ):
        assert field not in glue.table_input, field


# ── Column names, comments and casing ────────────────────────────────────────


def test_column_names_are_lowercased_like_the_create_path():
    """AWS documents that Athena "automatically lowers any upper case names in DDL queries
    when it creates databases, tables, or columns" — so the create path folds for free and
    this one, which bypasses Athena entirely, has to do it in code. Without the fold a
    refresh would leave a mixed-case catalog entry the create path could never produce.
    """
    glue, _sqs = _install()
    columns = [{"name": "Order_ID", "type": "string"}, {"name": "Amount", "type": "string"}]

    m.handler(_event(columns=columns), None)

    assert [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]] == ["order_id", "amount"]


def test_a_retyped_column_takes_the_fresh_type_and_keeps_its_comment():
    """Retyping is a legitimate refresh outcome: the TYPE is the verb's to change, the
    comment is not."""
    glue, _sqs = _install()

    m.handler(_event(columns=[{"name": "order_id", "type": "bigint"}]), None)
    written = glue.table_input["StorageDescriptor"]["Columns"][0]

    assert written["Type"] == "bigint"
    assert written["Comment"] == "the shop's own id"


# ── Partitioned tables ───────────────────────────────────────────────────────


def _partitioned_live():
    live = _live_table()
    live["PartitionKeys"] = [{"Name": "year", "Type": "int"}]
    live["Parameters"].update({
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": "2000,2100",
        "projection.year.digits": "4",
        # A stale key from a PREVIOUS partition scheme: replaced means removed, not merged.
        "projection.region.type": "enum",
        "projection.region.values": "eu,us",
    })
    return live


_KEYS = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]


# ── FR-004: the previous definition is retained ──────────────────────────────


# ── FR-003: the post-condition ───────────────────────────────────────────────


# ── Failure modes ────────────────────────────────────────────────────────────


# ── Outcome ──────────────────────────────────────────────────────────────────


# ── SPEC-153 FR-006: the Athena case-fold premise, pinned ────────────────────


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-157 FR-005: the residual window, narrowed ───────────────────────────


# ── SPEC-157: the shapes boto3 ACTUALLY returns ──────────────────────────────

_AWARE = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
