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

import json
import pathlib

import apply_refresh as m
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

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


def test_the_verb_issues_no_delete_of_any_kind():
    """FR-005 AC1. The replacement window is gone because nothing is ever removed.

    The fake's `delete_table` / `batch_delete_table` RAISE rather than being absent — an
    assertion that a fake lacks an attribute can never fail, which makes it read like evidence
    while providing none. Here the catalog can delete and the verb simply never asks it to.
    """
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert glue.update_calls and not any("Delete" in call for call in glue.update_calls)
    # And the tripwire is real: calling it is what fails, not its absence.
    with pytest.raises(AssertionError, match="delete_table"):
        glue.delete_table(DatabaseName="alice", Name="sales_2026")


def test_no_ddl_statement_appears_anywhere_in_the_verb():
    """FR-001. A grep, because the failure this guards against is someone reintroducing the
    old rebuild alongside the new one rather than instead of it."""
    source = pathlib.Path(m.__file__).read_text()

    for statement in ("DROP TABLE", "CREATE EXTERNAL TABLE", "StartQueryExecution"):
        assert statement not in source, statement


def test_nothing_in_the_table_builder_tree_calls_glue_delete_table():
    """FR-006. The IAM grant is only safe to remove if no verb needs it, so the code half of
    that claim is checked here rather than inferred from the one verb this spec rewrote.

    Scoped to the table-builder plane's own modules: shared-space's teardown legitimately
    calls ``batch_delete_table`` and keeps its grant.
    """
    offenders = []
    for path in sorted(LAMBDAS.glob("table-builder-*/*.py")) + sorted(LAMBDAS.glob("table-builder-common/tbcommon/*.py")):
        if path.name.startswith("test_"):
            continue
        if "delete_table" in path.read_text():
            offenders.append(path.name)

    assert not offenders, f"table-builder modules still calling a Glue delete: {offenders}"


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


def test_the_table_input_really_changed_the_columns():
    """Asserted on the SAME fixture as the preservation test, deliberately: a TableInput that
    changed nothing at all would pass a preservation-only test perfectly."""
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]] == ["order_id", "amount"]


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


def test_the_allowlist_matches_what_the_glue_api_actually_accepts():
    """FR-002's "verify the exact set against the API" — pinned on every run rather than
    checked once during a build.

    An ALLOWLIST is what makes this checkable: the denylist alternative would pass this test
    while silently going stale the next time AWS adds a member to ``Table``.
    """
    botocore = pytest.importorskip("botocore.session")

    shape = (
        botocore.get_session()
        .get_service_model("glue")
        .operation_model("UpdateTable")
        .input_shape.members["TableInput"]
    )

    assert set(shape.members) == set(m._TABLE_INPUT_FIELDS)


def test_external_and_table_type_survive_the_round_trip():
    """A refresh that turned an external table into a managed one would make a future drop
    destroy the user's data."""
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert glue.table_input["TableType"] == "EXTERNAL_TABLE"
    assert glue.table_input["Parameters"]["EXTERNAL"] == "TRUE"


def test_the_refreshed_table_is_still_marked_as_portal_built():
    """SPEC-143 FR-007's marker is re-asserted rather than merely inherited, so a table that
    predates it gains it on its first refresh.

    Asserted through ``mark_managed`` rather than by naming the property, for the same reason
    the verb writes it that way: naming it here would trip the tree-wide test that keeps a
    user-writable TBLPROPERTY from becoming something a verb can branch on.
    """
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert m.ddl.mark_managed({}).items() <= glue.table_input["Parameters"].items()


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


def test_a_column_comment_and_its_parameters_survive_the_refresh():
    """The metadata only the old table holds. Inference returns names and types and has
    nothing to say about what a column MEANS, so a rebuild is exactly where these vanish."""
    live = _live_table()
    live["StorageDescriptor"]["Columns"] = [
        {"Name": "order_id", "Type": "string", "Comment": "the shop's own id", "Parameters": {"pii": "false"}},
        {"Name": "gone", "Type": "string", "Comment": "dropped upstream"},
    ]
    glue, _sqs = _install(table=live)

    m.handler(_event(), None)
    written = {c["Name"]: c for c in glue.table_input["StorageDescriptor"]["Columns"]}

    assert written["order_id"]["Comment"] == "the shop's own id"
    assert written["order_id"]["Parameters"] == {"pii": "false"}
    # A column no longer in the data carries nothing forward; a new one has no metadata.
    assert "gone" not in written
    assert "Comment" not in written["amount"]


def test_a_comment_is_matched_case_insensitively_like_every_other_comparison():
    """The live name and the freshly inferred one can differ only by case, so the carry has to
    fold to find its match — even though what it writes is the folded name."""
    live = _live_table()
    live["StorageDescriptor"]["Columns"] = [{"Name": "Order_ID", "Type": "string", "Comment": "kept"}]
    glue, _sqs = _install(table=live)

    m.handler(_event(columns=[{"name": "order_id", "type": "string"}]), None)

    assert glue.table_input["StorageDescriptor"]["Columns"][0]["Comment"] == "kept"


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


def test_projection_properties_are_replaced_rather_than_merged():
    """FR-002. Every ``projection.*`` key is dropped and regenerated from the reconstructed
    keys through the create path's OWN renderer, so a stale key from a previous scheme cannot
    survive a refresh — and each live key is emitted exactly once."""
    glue, _sqs = _install(table=_partitioned_live())

    m.handler(_event(partitionKeys=_KEYS), None)
    parameters = glue.table_input["Parameters"]

    assert parameters["projection.enabled"] == "true"
    assert parameters["projection.year.range"] == "2000,2100"
    assert parameters["projection.year.digits"] == "4"
    assert not [key for key in parameters if key.startswith("projection.region.")]
    # Non-projection parameters are untouched by the replacement.
    assert parameters["skip.header.line.count"] == "1"


def test_the_projection_keys_are_not_folded_like_the_column_names():
    """They embed the PARTITION key's name, and this verb writes the live PartitionKeys back
    unchanged — so folding them would name a partition key that does not exist."""
    live = _partitioned_live()
    live["PartitionKeys"] = [{"Name": "Year", "Type": "int"}]
    glue, _sqs = _install(table=live)

    m.handler(_event(partitionKeys=[{**_KEYS[0], "name": "Year"}]), None)

    assert "projection.Year.type" in glue.table_input["Parameters"]
    assert glue.table_input["PartitionKeys"] == [{"Name": "Year", "Type": "int"}]


def test_a_column_colliding_with_a_partition_key_is_not_written_twice():
    """Glue keeps partition keys in their own field, and one name declared in both is not a
    valid table. infer-schema emits the FULL inferred list, so the collision is routine."""
    columns = [
        {"name": "order_id", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "year", "type": "string"},
    ]
    glue, _sqs = _install(table=_partitioned_live())

    out = m.handler(_event(partitionKeys=_KEYS, columns=columns), None)

    assert [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]] == ["order_id", "amount"]
    assert out["appliedColumnCount"] == 2


# ── FR-004: the previous definition is retained ──────────────────────────────


def test_the_update_does_not_skip_archiving():
    """The retained table version is the manual rollback path for a refresh that landed but
    was not wanted. Passed explicitly, so a future SDK default cannot quietly take it away."""
    glue, _sqs = _install()

    m.handler(_event(), None)

    assert glue.update_calls[0]["SkipArchive"] is False


# ── FR-003: the post-condition ───────────────────────────────────────────────


def test_a_definition_that_did_not_land_is_caught():
    """SPEC-135's lesson, unchanged by the mechanism: an accepted call is not evidence that
    the catalog agrees. This plane's canonical failure was a verb that COMPLETED while the
    table was not created (PRs #243-246)."""
    exc = _expect_reason(_event(), "update_failed", drift=("order_id", "wrong_name"))

    assert "missing ['amount']" in exc.detail
    assert "unexpected ['wrong_name']" in exc.detail


def test_a_post_condition_read_that_fails_is_TERMINAL_not_retryable():
    """Deliberately not transient, even on a throttle. The update is committed, so a Retry
    would re-read a table that has already changed and write it again — a verification
    failing is not evidence that repeating the work it was verifying will help."""
    _expect_reason(_event(), "update_failed", post_error=_ClientError("ThrottlingException"))


# ── Failure modes ────────────────────────────────────────────────────────────


def test_a_table_that_vanished_before_the_read_is_table_not_found():
    _expect_reason(_event(), "table_not_found", get_error=_ClientError("EntityNotFoundException"))


def test_a_table_that_vanished_before_the_write_is_table_not_found():
    """The read-modify-write is not atomic, so the table can go between the two calls."""
    _expect_reason(_event(), "table_not_found", update_error=_ClientError("EntityNotFoundException"))


def test_access_denied_is_update_failed_and_the_raw_text_never_reaches_the_user():
    """SPEC-106 FR-008. The operator gets the AWS text in the detail; the actor gets wording
    that says nothing was changed — which is true, because a failed update changes nothing."""
    _install(update_error=_ClientError("AccessDeniedException", "not authorized to perform glue:UpdateTable"))
    try:
        m.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == "update_failed"
        assert "not authorized" in exc.detail
    else:
        raise AssertionError("expected a TerminalError")

    message = json.loads(clients._sqs.calls[0]["MessageBody"])["message"]
    assert "Nothing was changed" in message
    assert "glue:UpdateTable" not in message
    assert "not authorized" not in message


def test_a_throttle_is_retryable_rather_than_terminal():
    _install(update_error=_ClientError("ThrottlingException"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_a_concurrent_modification_is_retryable():
    """Glue's own guard on two simultaneous modifications — and the recovery a lost race
    wants, because a re-invocation re-reads the live table and writes again. FR-005: this
    REDUCES the overlap's severity, it does not close it. Glue offers no compare-and-set."""
    _install(update_error=_ClientError("ConcurrentModificationException"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


@pytest.mark.parametrize(
    "code",
    ["InternalServiceException", "OperationTimeoutException", "ResourceNotReadyException", "FederationSourceRetryableException"],
)
def test_glues_own_retryable_faults_are_not_reported_as_permanent_failures(code):
    """THE SHARED CLASSIFIER MISSES THESE BY A WORD. `cpcommon.errors._TRANSIENT_CODES` is
    spelled for S3/Athena/generic throttles — it lists `InternalError` and
    `InternalServerException`, but Glue raises `InternalServiceException`, and it has no entry
    at all for `OperationTimeoutException`, Glue's most routine transient.

    Unclassified, each of these falls through to the terminal branch and kills the request with
    "Nothing was changed" — on faults the state machine's Retry would very likely have survived.
    """
    _install(update_error=_ClientError(code))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_the_same_faults_are_retryable_on_the_read_that_precedes_the_write():
    """Nothing has been written yet, so there is even less reason to give up here."""
    _install(get_error=_ClientError("OperationTimeoutException"))

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_an_invalid_input_is_still_terminal():
    """The classifier must not have become a catch-all: a deterministic refusal has to stay
    terminal, or the state machine burns its attempts on something that cannot resolve."""
    _expect_reason(_event(), "update_failed", update_error=_ClientError("InvalidInputException"))


def test_two_columns_differing_only_by_case_are_refused_rather_than_silently_merged():
    """THE GUARD SPEC-144 GOT FOR FREE AND THIS PATH HAS TO STATE.

    Athena rejects a CREATE with duplicate column names; `UpdateTable` performs no such
    validation. Once the write folds case, a header of `Amount,amount` — two distinct fields to
    inference — becomes one Glue column. The post-condition cannot catch it, because it
    compares NAME SETS: both spellings collapse on each side and compare equal, so the verb
    would report success on a table that lost a column and fails at query time.
    """
    glue, _sqs = _install()
    columns = [{"name": "Amount", "type": "string"}, {"name": "amount", "type": "string"}]

    exc = _expect_reason(_event(columns=columns), "update_failed")

    assert "amount" in exc.detail
    # Refused BEFORE the write — the table is untouched, which is what the message promises.
    assert not glue.update_calls


# ── Outcome ──────────────────────────────────────────────────────────────────


def test_success_emits_the_refreshed_status_and_exactly_one_notification():
    """FR-001: the verb's output is unchanged by the mechanism change, dedup id included."""
    _glue, sqs = _install()

    out = m.handler(_event(), None)

    assert out["status"] == "refreshed"
    assert out["appliedColumnCount"] == 2
    assert len(sqs.calls) == 1
    body = json.loads(sqs.calls[0]["MessageBody"])
    assert "1 column added" in body["message"]
    assert sqs.calls[0]["MessageDeduplicationId"] == "r1:refresh"


def test_the_output_no_longer_carries_a_ddl_field():
    """There is no statement to carry. A stale `ddl` would be the state's version of dead
    code, and the next reader would go looking for the DDL that produced it."""
    _install()

    out = m.handler(_event(), None)

    assert "ddl" not in out


def test_a_failure_notifies_the_actor_before_the_state_machine_records_it():
    _install(update_error=_ClientError("AccessDeniedException"))
    try:
        m.handler(_event(), None)
    except TerminalError:
        pass

    body = json.loads(clients._sqs.calls[0]["MessageBody"])
    assert "Nothing was changed" in body["message"]


def test_the_verb_narrates_the_columns_it_declared():
    """The `ddl` field SPEC-144 logged has no successor — there is no statement — so the
    column names are what an operator reads to see what the update actually declared. Schema,
    not file contents: permitted by the field rule."""
    _install()
    events = []
    m.observability.info = lambda message, **fields: events.append((message, fields))
    m.handler(_event(), None)

    applying = next(fields for message, fields in events if message == "applying refresh")
    assert applying["column_names"] == ["order_id", "amount"]

    applied = next(fields for message, fields in events if message == "refresh applied")
    assert applied["post_condition_ok"] is True
    assert applied["previous_version_archived"] is True


# ── SPEC-153 FR-006: the Athena case-fold premise, pinned ────────────────────


def test_ACCEPTED_a_mixed_case_live_table_is_silently_re_cased_on_refresh():
    """The premise SPEC-149 made OURS, written down as behaviour instead of prose.

    AWS documents that Athena lowercases every column name it creates through DDL, so a
    portal-created table's live columns are already lowercase and the fold below is a no-op.
    SPEC-149's in-place ``UpdateTable`` bypasses Athena entirely, which is why this verb does
    the fold itself — and that turned a documented property of Athena into a property of OUR
    code. If the premise is wrong (a pre-149 table, an ``ALTER TABLE`` a user ran, a table
    created outside the pipeline), the first refresh REWRITES the casing of every column
    while ``diff-schema`` — which folds case to compare — reports the columns unchanged. No
    test and no notification would say so.

    Every other fixture in this file supplies already-lowercase live columns, so they assume
    the conclusion. This one does not: the live table carries ``Order_ID`` and the refresh is
    a pure add, yet what lands is ``order_id``.

    ACCEPTED, and CORROBORATED-NOT-DISCHARGED: the AWS documentation is strong evidence and
    is why 149 hard-codes the fold, but documentation is the same class of evidence that had
    SPEC-144 FR-001 reversed mid-build. The check that would discharge it is a live
    ``GetTable`` read-back after refreshing a table carrying a mixed-case column, and it is
    recorded as owed. Note the comment survives the re-casing — the carry is keyed on
    ``casefold()`` — so this is a rename, not a column swap.

    If this starts failing, the fold changed: revisit the decision (decisions.md, "Removing a
    column needs an opt-in" / SPEC-149's apply entry), do not delete the test.
    """
    storage = {
        **_live_table()["StorageDescriptor"],
        "Columns": [{"Name": "Order_ID", "Type": "string", "Comment": "the shop's own id"}],
    }
    glue, _ = _install(table=_live_table(StorageDescriptor=storage))

    m.handler(_event(columns=[
        {"name": "Order_ID", "type": "string"},
        {"name": "amount", "type": "string"},
    ]), None)

    written = glue.table_input["StorageDescriptor"]["Columns"]
    assert [c["Name"] for c in written] == ["order_id", "amount"], (
        "the fold is no longer being applied on write"
    )
    assert written[0]["Comment"] == "the shop's own id", "the carried comment was lost"


def test_traced_is_outermost_above_notifies_on_failure():
    import inspect

    source = inspect.getsource(m)

    assert source.index('@observability.traced("apply-refresh")') < source.index('@notify.notifies_on_failure("apply")')


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
