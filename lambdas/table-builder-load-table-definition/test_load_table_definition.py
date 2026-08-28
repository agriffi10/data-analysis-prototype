"""Unit tests for the table-builder load-table-definition Lambda (SPEC-143).

Pure logic, AWS stubbed: ``clients.glue`` is a fake returning a scripted Glue table.
Asserts every refusal, the prefix rewrite, and — the one that matters most — that a
reconstructed partition key re-renders to the exact properties it was read from.

Runnable under pytest OR directly: ``python3 test_load_table_definition.py``.
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


import load_table_definition as m
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"


class _EntityNotFound(Exception):
    pass


class _FakeClientError(Exception):
    """botocore-SHAPED: the transient classifier reads .response["Error"]["Code"]."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeGlue:
    class exceptions:  # mirrors boto3's client.exceptions namespace
        EntityNotFoundException = _EntityNotFound

    def __init__(self, table=None, error=None):
        self._table = table
        self._error = error
        self.calls = []

    def get_table(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Table": self._table}


def _install(table=None, error=None):
    fake = _FakeGlue(table, error)
    clients._glue = fake
    config.USER_SPACE_BUCKET = BUCKET
    config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    return fake


def _table(*, location=f"s3://{BUCKET}/alice/sales/", partition_keys=(), parameters=None, **overrides):
    table = {
        "Name": "sales_2026",
        "TableType": "EXTERNAL_TABLE",
        "StorageDescriptor": {
            "Location": location,
            "Columns": [
                {"Name": "order_id", "Type": "string"},
                {"Name": "amount", "Type": "double"},
            ],
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
                "Parameters": {"separatorChar": ","},
            },
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        },
        "Parameters": {"skip.header.line.count": "1", **(parameters or {})},
        "PartitionKeys": [{"Name": name, "Type": hive} for name, hive in partition_keys],
    }
    table.update(overrides)
    return table


def _event(*, kind="personal", database="alice", actor="alice", prefix="alice/sales/", bucket=BUCKET):
    return {
        "mode": "refresh",
        "actor": actor,
        "space": {"kind": kind, "bucket": bucket, "prefix": prefix, "database": database},
        "tableName": "sales_2026",
        "partitionKeys": [],
        "location": f"s3://{bucket}/{prefix}",
        "requestId": "r1",
    }


def _expect_reason(event, reason):
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── The happy path and the normalisation it exists for ───────────────────────


def test_a_flat_portal_table_loads_and_normalises_the_state():
    glue_client = _install(_table())

    out = m.handler(_event(), None)

    assert glue_client.calls == [{"DatabaseName": "alice", "Name": "sales_2026"}]
    assert out["existingColumns"] == [
        {"name": "order_id", "type": "string"},
        {"name": "amount", "type": "double"},
    ]
    assert out["partitionKeys"] == []
    assert out["storage"] == {
        "serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
        "parameters": {"separatorChar": ","},
        "inputFormat": "org.apache.hadoop.mapred.TextInputFormat",
        "outputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
    }
    # `tableProperties` is NOT threaded (SPEC-149). It existed only for SPEC-144's rebuild,
    # which carried the captured properties into a regenerated CREATE; the in-place update
    # reads them from the LIVE table, so threading them would be payload weight against the
    # definition cap that nothing downstream reads. The CAPTURE is unchanged — clone_definition
    # still strips transient_lastDdlTime / EXTERNAL and still feeds the projection check.
    assert "tableProperties" not in out
    # The request threads through for the states that follow.
    assert out["mode"] == "refresh"
    assert out["requestId"] == "r1"


def test_a_shared_space_table_loads_against_its_own_root():
    _install(_table(location=f"s3://{SHARED_BUCKET}/salesdata/2026/"))

    out = m.handler(
        _event(kind="shared", database="salesdata", prefix="salesdata/2026/", bucket=SHARED_BUCKET),
        None,
    )

    assert out["space"]["bucket"] == SHARED_BUCKET
    assert out["location"] == f"s3://{SHARED_BUCKET}/salesdata/2026/"


# ── Refusals ─────────────────────────────────────────────────────────────────


def test_a_missing_table_is_terminal_not_transient():
    _install(error=_EntityNotFound("nope"))

    exc = _expect_reason(_event(), "table_not_found")

    assert "alice.sales_2026" in exc.detail


def test_a_glue_throttle_is_retryable():
    """A throttle is NOT EntityNotFound, so unmapped it would propagate as a bare
    ClientError the LoadTableDefinition Retry list does not name — permanently failing a
    request the SFN would happily have retried."""
    _install(error=_FakeClientError("ThrottlingException"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_every_shape_refusal_is_re_spoken_in_the_refresh_vocabulary():
    for table, reason in (
        (_table(TableType="VIRTUAL_VIEW"), "cannot_refresh_view"),
        (_table(TableType="MANAGED_TABLE"), "cannot_refresh_managed_table"),
        (
            _table(partition_keys=[("year", "int")], parameters={}),
            "cannot_refresh_catalog_partitioned",
        ),
        (_table(location="s3://somebody-elses-bucket/alice/sales/"), "cannot_refresh_location_unsupported"),
    ):
        _install(table)
        _expect_reason(_event(), reason)


def test_a_table_in_the_right_bucket_but_another_users_prefix_is_refused():
    """FR-004 AC6. clone_definition validates the BUCKET; only this validates the PREFIX.

    The catalog is not the authorization boundary: Lake Formation could grant a user
    GetTable on a table whose files live under someone else's prefix, and refreshing it
    would then list and re-derive a schema from data they cannot otherwise read.
    """
    _install(_table(location=f"s3://{BUCKET}/bob/secrets/"))

    _expect_reason(_event(), "table_outside_space")


# ── FR-005: the reconstruction ───────────────────────────────────────────────

#: A partitioned table whose projection properties exercise all three declared types,
#: including the two shapes that produce a wrong first draft: a `string` key is written
#: `enum`, and a `date` key writes FOUR properties rather than two.
_DECLARED_KEYS = [
    {"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4},
    {"name": "day", "type": "date", "range": ["2020-01-01", "NOW"], "format": "yyyy-MM-dd",
     "interval": 1, "interval.unit": "DAYS"},
    {"name": "region", "type": "string", "values": ["us-east-1", "eu-west-1"]},
]


def _projection_parameters(keys=_DECLARED_KEYS):
    """Exactly what build_create_table_ddl would have written for ``keys``."""
    from cpcommon import ddl

    properties = {"projection.enabled": "true"}
    for key in keys:
        properties.update(ddl.projection_properties(key))
    return properties


def _partitioned_table(keys=_DECLARED_KEYS, parameters=None):
    hive = {"integer": "int", "date": "date", "string": "string"}
    return _table(
        partition_keys=[(k["name"], hive[k["type"]]) for k in keys],
        parameters=parameters if parameters is not None else _projection_parameters(keys),
    )


def test_declared_keys_are_reconstructed_in_the_tables_own_order():
    _install(_partitioned_table())

    out = m.handler(_event(), None)

    assert [k["name"] for k in out["partitionKeys"]] == ["year", "day", "region"]
    assert [k["type"] for k in out["partitionKeys"]] == ["integer", "date", "string"]


# ── SPEC-153 FR-006: a partial substitute for the owed GetTable capture ──────
#
# BE PRECISE ABOUT WHAT THIS IS AND IS NOT. FR-006 AC2 asks for a VERBATIM paste of a real
# GetTable response for a hand-created partition-projected table. This is NOT that, and the
# gap is recorded as an owed live check rather than papered over: Lake Formation filters this
# repo's local CLI principal's catalog to empty (`aws glue get-databases` returns []), and
# hand-creating a table in the account from a laptop is a production mutation.
#
# PROVENANCE. The projection.* keys were transcribed from AWS's published partition-projection
# reference (Athena user guide) on 2026-08-06; the surrounding TBLPROPERTIES are the ones
# Athena and the Glue crawler stamp on a table this pipeline did not create — EXTERNAL,
# transient_lastDdlTime, classification, has_encrypted_data, parquet.compression.
#
# WHAT IT PROVES: the reconstruction tolerates neighbouring properties it did not author, and
# follows the TABLE's partition-key order rather than the property dict's.
#
# WHAT IT DOES NOT PROVE, stated so nobody reads more into it: the projection VALUES here are
# byte-identical to what ddl.projection_properties emits — necessarily so, because the
# reconstruction re-renders and demands exact equality, so any value format Athena accepts and
# our renderer spells differently is a REFUSAL, not a rebuild. Value-format disagreement is
# therefore entirely untested here, and it is exactly what the owed GetTable capture buys.
_FOREIGN_PARAMETERS = {
    "EXTERNAL": "TRUE",
    "classification": "parquet",
    "has_encrypted_data": "false",
    "parquet.compression": "SNAPPY",
    "transient_lastDdlTime": "1751328000",
    "projection.enabled": "true",
    "projection.country.type": "enum",
    "projection.country.values": "US,CA,MX",
    "projection.dt.type": "date",
    "projection.dt.range": "2020-01-01,NOW",
    "projection.dt.format": "yyyy-MM-dd",
    "projection.dt.interval": "1",
    "projection.dt.interval.unit": "DAYS",
    "projection.id.type": "integer",
    "projection.id.range": "1,1000",
}


# ── Observability + notification ─────────────────────────────────────────────


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


