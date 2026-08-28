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

import json

import load_table_definition as m
import pytest
from cpcommon import clients, config, glue
from cpcommon.ddl import build_create_table_ddl
from cpcommon.errors import TerminalError, TransientError
from tbcommon import config as tb_config

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


def test_the_location_comes_from_the_table_not_from_the_request():
    """FR-004 AC7. The producer only BELIEVES where the table points; the catalog knows.

    This is the whole reason the branch needed an entry verb: inspect-source lists
    space.bucket + space.prefix, so rewriting them here is what lets it run unchanged.
    """
    _install(_table(location=f"s3://{BUCKET}/alice/actually/over/here/"))

    out = m.handler(_event(prefix="alice/sales/"), None)

    assert out["space"]["prefix"] == "alice/actually/over/here/"
    assert out["space"]["bucket"] == BUCKET
    assert out["location"] == f"s3://{BUCKET}/alice/actually/over/here/"
    # Still inside the authorized root — the rewrite does not bypass the check.
    assert out["space"]["prefix"].startswith("alice/")
    # Untouched fields survive the rewrite.
    assert out["space"]["kind"] == "personal"
    assert out["space"]["database"] == "alice"


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


def test_the_mapping_covers_every_code_clone_definition_can_raise():
    """THE GUARD THAT REPLACES A LOUDER ONE, and the reason it is worth writing.

    Before SPEC-143, raising `source_is_view` outside table-share was impossible —
    TerminalError validates its reason at the raise site and only tscommon registered it.
    cpcommon.glue now registers its own codes, which is what makes the refresh path able
    to speak at all. The cost: an UNMAPPED code no longer explodes. It would sail through
    as a valid terminal, miss this verb's vocabulary, and resolve to the generic
    unexpected_error — the user told "something went wrong" about a view.
    """
    assert set(m._SHAPE_REASONS) == set(glue._SHAPE_REASONS)


def test_a_table_in_the_right_bucket_but_another_users_prefix_is_refused():
    """FR-004 AC6. clone_definition validates the BUCKET; only this validates the PREFIX.

    The catalog is not the authorization boundary: Lake Formation could grant a user
    GetTable on a table whose files live under someone else's prefix, and refreshing it
    would then list and re-derive a schema from data they cannot otherwise read.
    """
    _install(_table(location=f"s3://{BUCKET}/bob/secrets/"))

    _expect_reason(_event(), "table_outside_space")


def test_a_personal_space_table_living_in_the_shared_bucket_is_refused():
    """Both halves are checked: prefix alone would accept this, since 'alice/' matches."""
    _install(_table(location=f"s3://{SHARED_BUCKET}/alice/sales/"))

    _expect_reason(_event(), "table_outside_space")


def test_an_oversized_definition_is_refused_before_anything_lists_s3():
    wide = _table()
    wide["StorageDescriptor"]["Columns"] = [
        {"Name": f"column_number_{i:04d}", "Type": "string", "Comment": "c" * 255}
        for i in range(400)
    ]
    _install(wide)

    _expect_reason(_event(), "definition_too_large")


def _state_at_cap(column_share):
    """The whole post-infer-schema state for a definition sized to exactly the cap.

    ``column_share`` splits that cap between columns and table properties. The split is a
    PARAMETER because it is what decides the answer: COLUMNS RIDE THE STATE THREE TIMES
    (existingColumns, infer-schema's own columns, and again inside the generated DDL) while
    table properties ride once, so the same cap spent entirely on columns produces a far
    bigger state than a mixed definition. Modelling the mix and calling it the worst case
    is how table-share once certified a bound that did not exist
    (test_state_machines_cpcommon.py).
    """
    cap = tb_config.REFRESH_MAX_DEFINITION_BYTES
    columns, properties = [], {}

    def _size():
        return len(json.dumps({"c": columns, "p": properties}, separators=(",", ":")).encode())

    while _size() < cap * column_share:
        columns.append({"name": f"column_number_{len(columns):04d}", "type": "string"})
    while _size() < cap:
        properties[f"some.table.property.{len(properties):04d}"] = "v" * 64

    state = {
        **_event(),
        "existingColumns": columns,
        "tableProperties": properties,
        "storage": {"serializationLibrary": "x" * 64, "parameters": {"separatorChar": ","}},
        # What infer-schema then ADDS to this same state.
        "columns": columns,
        "ddl": build_create_table_ddl("alice", "sales_2026", columns, [], "csv", "s3://b/p/"),
    }
    return len(json.dumps(state).encode()), len(columns)


def test_the_refresh_cap_leaves_room_for_what_infer_schema_adds_to_the_same_state():
    """The cap bounds the WHOLE state, not the definition alone, and it is measured at the
    composition that maximises it — a flat table that is all columns and no properties,
    which is an ordinary Parquet table rather than a contrived one.

    Breaching 256 KB raises States.DataLimitExceeded, which is thrown OUTSIDE every Catch:
    no recorded outcome, no notification, on a request that already did all its work.
    """
    limit = 256 * 1024
    worst, columns = _state_at_cap(column_share=1.0)

    assert worst < limit // 2, (
        f"a {tb_config.REFRESH_MAX_DEFINITION_BYTES:,}-byte definition of {columns:,} bare "
        f"columns reaches {worst:,} bytes ({worst / limit:.0%}) once infer-schema adds its "
        f"columns and DDL — too close to the {limit:,}-byte state-payload limit"
    )
    # A mixed definition is strictly smaller at the same cap — stated so the choice of
    # worst case is visible rather than asserted.
    mixed, _ = _state_at_cap(column_share=0.5)
    assert mixed < worst


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


def test_the_parser_is_a_left_inverse_of_the_renderer_on_the_renderers_own_output():
    """FR-005 AC5 — EXACT equality, which is the point of writing it this way.

    Any property the reconstruction drops, and any it would rewrite, fails here. It is
    also the only check that can catch the two shapes prose gets wrong: a `string` key
    written as `enum`, and a `date` key's four properties.

    RENAMED BY SPEC-153 FR-006 to say what it proves and no more. The fixture's Parameters
    come from ``ddl.projection_properties`` — the very renderer the reconstruction
    re-renders through — so this is render → parse → render compared against render. That
    establishes the parser is a left inverse of the renderer ON THE RENDERER'S OWN IMAGE,
    which is worth having and is not the same claim as "reads tables this pipeline did not
    write". The old name implied the second. ``test_a_table_this_pipeline_did_not_write_is
    _reconstructed`` below is the one that reaches outside the image.
    """
    _install(_partitioned_table())

    out = m.handler(_event(), None)

    assert _projection_parameters(out["partitionKeys"]) == _projection_parameters()


def test_a_reconstructed_key_is_accepted_by_the_ddl_builder_that_will_receive_it():
    """FR-005 AC7. infer-schema hands these straight to build_create_table_ddl, which
    raises a bare ValueError — not a TerminalError — on a Glue-shaped key. That would
    surface as the generic unexpected_error, so the shape is asserted end to end."""
    _install(_partitioned_table())

    keys = m.handler(_event(), None)["partitionKeys"]

    statement = build_create_table_ddl(
        "alice", "sales_2026", [{"name": "amount", "type": "double"}], keys, "csv", "s3://b/p/"
    )

    assert "PARTITIONED BY (`year` int, `day` date, `region` string)" in statement


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


def test_the_reconstruction_ignores_properties_our_renderer_never_writes():
    """Part of what the self-referential round-trip above cannot reach — not all of it.

    Five TBLPROPERTIES here are ones this pipeline never emits, and the reconstruction must
    walk past them rather than choke or fold them in. Declaration order is dt, country, id —
    deliberately neither alphabetical nor the order our own fixtures use — so the walk is
    shown to follow the TABLE's partition-key order rather than the property dict's.

    See the block comment above for what this does NOT establish.
    """
    _install(_table(
        partition_keys=[("dt", "date"), ("country", "string"), ("id", "int")],
        parameters=_FOREIGN_PARAMETERS,
    ))

    keys = m.handler(_event(), None)["partitionKeys"]

    assert [k["name"] for k in keys] == ["dt", "country", "id"]
    assert [k["type"] for k in keys] == ["date", "string", "integer"]
    assert keys[0]["range"] == ["2020-01-01", "NOW"]
    assert keys[0]["format"] == "yyyy-MM-dd"
    assert keys[1]["values"] == ["US", "CA", "MX"]
    assert keys[2]["range"] == [1, 1000]
    # An integer key with no projection.id.digits must not acquire one.
    assert keys[2].get("digits") is None


def test_the_fixture_carries_properties_our_renderer_never_writes():
    """Guards the guard: the extra TBLPROPERTIES are what the test above actually exercises,
    so if they were ever dropped it would silently become the round-trip test again.

    It also pins the honest half of the claim: the projection subset MUST equal our renderer's
    output, because the reconstruction demands exact equality and a fixture that disagreed on
    value format would be asserting a refusal, not a rebuild. That is the boundary of what a
    hand-authored fixture can reach, and why the real GetTable capture is still owed.
    """
    from cpcommon import ddl

    ours = {"projection.enabled": "true"}
    for key in (
        {"name": "dt", "type": "date", "range": ["2020-01-01", "NOW"], "format": "yyyy-MM-dd",
         "interval": 1, "interval.unit": "DAYS"},
        {"name": "country", "type": "string", "values": ["US", "CA", "MX"]},
        {"name": "id", "type": "integer", "range": [1, 1000]},
    ):
        ours.update(ddl.projection_properties(key))

    extra = set(_FOREIGN_PARAMETERS) - set(ours)
    assert extra >= {"EXTERNAL", "classification", "transient_lastDdlTime"}, (
        f"the fixture lost the properties our renderer never writes — only {sorted(extra)} "
        f"remain, so the test above no longer exercises anything the round-trip does not"
    )
    # The projection subset must MATCH ours: the reconstruction re-renders and demands exact
    # equality, so a disagreeing value format would test a refusal rather than a rebuild.
    assert set(ours).issubset(_FOREIGN_PARAMETERS)
    assert all(_FOREIGN_PARAMETERS[k] == v for k, v in ours.items())


def test_an_unpartitioned_table_is_not_subject_to_any_of_it():
    _install(_table())

    assert m.handler(_event(), None)["partitionKeys"] == []


def test_a_key_with_no_projection_type_is_refused():
    _install(_partitioned_table(parameters={"projection.enabled": "true"}))

    exc = _expect_reason(_event(), "projection_not_reconstructable")

    assert "year" in exc.detail


def test_an_unrecognised_projection_type_is_refused():
    properties = {**_projection_parameters(), "projection.year.type": "injected"}
    _install(_partitioned_table(parameters=properties))

    _expect_reason(_event(), "projection_not_reconstructable")


def test_every_missing_required_companion_property_is_refused():
    """The companions build_create_table_ddl ALWAYS writes, dropped one at a time."""
    for missing in (
        "projection.year.range",
        "projection.day.range",
        "projection.day.format",
        "projection.region.values",
    ):
        properties = _projection_parameters()
        del properties[missing]
        _install(_partitioned_table(parameters=properties))

        exc = _expect_reason(_event(), "projection_not_reconstructable")
        assert missing.split(".")[1] in exc.detail, f"{missing} should name its key"


def test_a_projection_over_a_wider_column_type_is_refused_not_silently_retyped():
    """THE CASE THE ROUND-TRIP CANNOT SEE, and the most realistic wrong rebuild.

    Athena allows a projection on a wider set of column types than this builder writes: an
    `integer` projection is legal on a `string` column, which is exactly how you declare a
    zero-padded partition, and a `date` projection is legal on `string` too. Both
    reconstruct perfectly from their projection properties and round-trip clean — and
    would then be rebuilt as `int` and `date`, changing the column's type while reporting
    success. The live column type is the only thing that catches it.
    """
    for name, hive, keys in (
        ("year", "string", [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]),
        ("day", "string", [{"name": "day", "type": "date", "range": ["2020-01-01", "NOW"],
                            "format": "yyyy-MM-dd"}]),
        ("year", "bigint", [{"name": "year", "type": "integer", "range": [2000, 2100]}]),
    ):
        table = _table(
            partition_keys=[(name, hive)], parameters=_projection_parameters(keys)
        )
        _install(table)

        exc = _expect_reason(_event(), "projection_not_reconstructable")
        assert hive in exc.detail, f"the refusal should name the live column type {hive!r}"


def test_a_matching_column_type_is_still_accepted():
    """The guard above must not refuse the tables this pipeline itself creates."""
    _install(_partitioned_table())

    assert len(m.handler(_event(), None)["partitionKeys"]) == 3


def test_a_storage_location_template_is_refused():
    """Table-level, so it sits OUTSIDE the projection.{name}.* namespace the per-key
    round-trip compares — invisible to it, and it redirects where partitions read from
    entirely. Nothing in the declared shape can express it, so a rebuild would drop it."""
    properties = {**_projection_parameters(), "storage.location.template": "s3://b/p/${year}/"}
    _install(_partitioned_table(parameters=properties))

    _expect_reason(_event(), "projection_not_reconstructable")


def test_a_projection_option_this_portal_cannot_express_is_refused_not_dropped():
    """A hand-created table can carry projection options SPEC-069's declared shape has no
    room for. Rebuilding it would silently DROP them and change the table's partitioning
    while reporting success, so the round-trip refuses instead."""
    properties = {**_projection_parameters(), "projection.year.interval": "10"}
    _install(_partitioned_table(parameters=properties))

    _expect_reason(_event(), "projection_not_reconstructable")


def test_a_range_that_would_not_re_render_identically_is_refused():
    """A zero-padded integer bound is the realistic case: Athena accepts it, and the
    declared shape stores an int, so a rebuild would quietly rewrite the property."""
    properties = {**_projection_parameters(), "projection.year.range": "02000,2100"}
    _install(_partitioned_table(parameters=properties))

    _expect_reason(_event(), "projection_not_reconstructable")


def test_an_unreadable_range_is_refused_rather_than_raising_valueerror():
    for bad in ("2000", "not,numbers", "2000,2100,2200"):
        properties = {**_projection_parameters(), "projection.year.range": bad}
        _install(_partitioned_table(parameters=properties))

        _expect_reason(_event(), "projection_not_reconstructable")


def test_an_enum_value_containing_a_comma_is_split_the_way_athena_splits_it():
    """A RECORDED LIMIT, not a guarantee — and worth stating because the obvious guard is
    vacuous. `",".join(s.split(","))` reproduces `s` for every `s`, so a round-trip can
    never detect a comma inside a value; the information is simply not in the property.

    Athena splits the same property the same way, so the reconstruction is faithful to
    what the table ACTUALLY does today. A value with a comma was already two partitions to
    the engine before any refresh ran.
    """
    keys = [{"name": "region", "type": "string", "values": ["us-east-1,eu-west-1"]}]
    _install(_partitioned_table(keys=keys))

    out = m.handler(_event(), None)

    assert out["partitionKeys"][0]["values"] == ["us-east-1", "eu-west-1"]


# ── Observability + notification ─────────────────────────────────────────────


def test_the_verb_narrates_the_load_without_naming_any_data():
    _install(_partitioned_table())
    events = []
    m.observability.info = lambda message, **fields: events.append((message, fields))
    m.handler(_event(), None)

    message, fields = events[0]
    assert message == "loaded table definition"
    assert fields["database"] == "alice"
    assert fields["table"] == "sales_2026"
    assert fields["column_count"] == 2
    assert fields["partition_key_count"] == 3
    assert fields["mode"] == "refresh"
    # Column and partition NAMES are schema and are permitted; a VALUE never is. The enum's
    # declared values are user data from the table definition, so they stay out of fields.
    assert "us-east-1" not in json.dumps(fields)


def test_traced_is_outermost_above_notifies_on_failure():
    """The ordering rule: notifies_on_failure catches on its way out, so if it were
    outermost the span would close status="ok" on an invocation that failed and notified."""
    import inspect

    source = inspect.getsource(m)
    traced = source.index('@observability.traced("load-table-definition")')
    notifies = source.index('@notify.notifies_on_failure("load")')

    assert traced < notifies


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-157 FR-005: capture the stamp apply-refresh compares against ────────


def test_the_live_tables_update_time_is_captured_onto_the_state():
    """apply-refresh compares this against its own pre-write read. Captured HERE rather than
    re-read there because the point is to span the whole run: a stamp read next to the write
    would only ever equal itself."""
    _install(_table(UpdateTime="2026-02-01T00:00:00Z"))

    out = m.handler(_event(), None)

    assert out["observedUpdateTime"] == "2026-02-01T00:00:00Z"


def test_a_datetime_stamp_is_rendered_as_a_string():
    """It is threaded through Step Functions state, which is JSON — a datetime would not survive
    the round trip, and boto3 returns one for real."""
    import datetime

    _install(_table(UpdateTime=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)))

    out = m.handler(_event(), None)

    assert out["observedUpdateTime"] == "2026-02-01T00:00:00+00:00"
    assert isinstance(out["observedUpdateTime"], str)


def test_a_table_reporting_no_update_time_captures_none_rather_than_failing():
    """Absent is a legitimate answer — apply-refresh treats it as no evidence of a concurrent
    writer rather than inventing a refusal."""
    _install(_table())

    out = m.handler(_event(), None)

    assert out["observedUpdateTime"] is None
