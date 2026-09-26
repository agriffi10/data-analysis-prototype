"""Unit tests for the table-builder apply-refresh Lambda (SPEC-149).

Glue is stubbed by a fake that ACTUALLY APPLIES the update, so the post-condition read sees
what the verb wrote rather than a scripted echo — a fake that answered `get_table` from a
canned list would pass a verification the real catalog could fail.

What this file is really about is FR-002: ``UpdateTable`` replaces the WHOLE definition, so
every field the input omits is CLEARED. Preservation and mutation are therefore asserted
TOGETHER — an input that changed nothing would sail through a preservation-only test.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
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


def test_names_are_lowercased_like_the_create_path_and_every_check_uses_that_fold():
    """Writes names the way Athena lowercases them, and carries, drops and verifies on that fold.

    AWS documents that Athena "automatically lowers any upper case names in DDL queries when it
    creates databases, tables, or columns", so the create path folds for free and this one,
    which bypasses Athena entirely, has to do it in code. Lowercasing is not case folding:
    against a live ``straße`` and the partition key ``weiss``, ``STRASSE`` and ``Weiß`` are the
    new columns ``strasse`` and ``weiß``, and ``Weiss`` and ``WEISS`` are the partition key,
    dropped rather than refused as a collision, in Parquet, where a partition's namesake is left
    out. Keyed on ``casefold()`` instead, ``strasse`` took
    the live column's comment, ``Weiß`` was dropped as if it were the partition key, and the
    read-back counted ``straße`` and ``strasse`` as one column. The live name is not ASCII so
    that a carry keyed on one fold and looked up on the other loses the comment either way
    round.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    storage = {
        **_live_table()["StorageDescriptor"],
        "Columns": [{"Name": "straße", "Type": "string", "Comment": "the street"}],
    }
    live = _live_table(StorageDescriptor=storage, PartitionKeys=[{"Name": "weiss", "Type": "string"}])
    glue, _sqs = _install(table=live)
    columns = [
        {"name": "Straße", "type": "string"},
        {"name": "STRASSE", "type": "string"},
        {"name": "Weiß", "type": "string"},
        {"name": "Weiss", "type": "string"},
        {"name": "WEISS", "type": "string"},
        {"name": "notes", "type": "string"},
    ]
    keys = [{"name": "weiss", "type": "string", "values": ["a", "b"]}]

    out = m.handler(_event(columns=columns, partitionKeys=keys, format="parquet"), None)

    written = glue.table_input["StorageDescriptor"]["Columns"]
    assert [c["Name"] for c in written] == ["straße", "strasse", "weiß", "notes"]
    assert [c.get("Comment") for c in written] == ["the street", None, None, None]
    assert out["appliedColumnCount"] == 4


def test_a_csv_column_naming_a_partition_key_is_written_under_the_creates_name_in_the_tables_place():
    """A CSV is read by position, so the write KEEPS the file's ``Year`` rather than leaving it
    out, under the name the create gave it and carrying that column's comment; leaving it out
    would move every later column onto its neighbour's field.

    Where it lands is the TABLE's business, not the file's: the live table already declares
    ``year_in_file`` first, so that is where it goes. The fixture's live order and the file's
    agree, which is the ordinary case; the row below covers the one where the table does not
    declare the namesake at all.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    storage = {
        **_live_table()["StorageDescriptor"],
        "Columns": [
            {"Name": "year_in_file", "Type": "string", "Comment": "the export's year"},
            {"Name": "id", "Type": "string"},
        ],
    }
    live = _live_table(StorageDescriptor=storage, PartitionKeys=[{"Name": "year", "Type": "string"}])
    glue, _sqs = _install(table=live)
    columns = [
        {"name": "Year", "type": "string"},
        {"name": "id", "type": "string"},
        {"name": "region", "type": "string"},
    ]
    keys = [{"name": "year", "type": "string", "values": ["2025"]}]

    m.handler(_event(columns=columns, partitionKeys=keys), None)

    written = glue.table_input["StorageDescriptor"]["Columns"]
    assert [(c["Name"], c.get("Comment")) for c in written] == [
        ("year_in_file", "the export's year"), ("id", None), ("region", None)
    ]


def _live_with(names, comments=None):
    """A live table carrying the named columns, in that order, optionally with comments.

    Args:
      names: The live column names, in the order the table declares them.
      comments: Optional name-to-comment mapping.

    Returns:
      A live Glue table dict.

    Raises:
      None.
    """
    comments = comments or {}
    columns = []
    for name in names:
        column = {"Name": name, "Type": "string"}
        if name in comments:
            column["Comment"] = comments[name]
        columns.append(column)
    storage = {**_live_table()["StorageDescriptor"], "Columns": columns}
    return _live_table(StorageDescriptor=storage)


@pytest.mark.parametrize(
    ("first_file", "expected"),
    [
        (["a", "new", "b", "c"], ["a", "b", "c", "new"]),
        (["c", "a", "b", "d"], ["a", "b", "c", "d"]),
        (["y", "a", "x", "b", "c"], ["a", "b", "c", "y", "x"]),
        (["a", "c"], ["a", "c"]),
    ],
)
def test_a_csv_refresh_keeps_the_tables_order_and_appends_what_is_new(first_file, expected):
    """A CSV is read by position, so the table's order is a contract with every file already in
    the folder: the write keeps it and adds new columns at the end.

    Taking the first file's order instead shifted every older file by one and said nothing —
    every CSV column is a string, so no value fails to fit the column it lands in, and the
    refresh notification reported success. The four headers are the shapes that produced it: a
    column inserted mid-header, the same columns in another order, two new columns around the
    old ones, and a removal diff-schema has already let through, which leaves the survivors in
    their places rather than closing up around the first file's order.

    Args:
      first_file: The header the refresh inferred, in the first file's order.
      expected: The column names the update must carry, in order.

    Returns:
      None.

    Raises:
      None.
    """
    glue, _sqs = _install(table=_live_with(["a", "b", "c"]))
    columns = [{"name": name, "type": "string"} for name in first_file]

    m.handler(_event(columns=columns), None)

    written = [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]]
    assert written == expected


def test_a_reordered_csv_header_keeps_the_live_order_and_the_comment_on_a_moved_column():
    """The carry is keyed on the folded name, not on a position, so a column the first file moved
    still arrives with the metadata the table holds for it.

    The header also re-cases two of the names, because the reorder and the fold have to agree:
    sorted on the file's own casing, ``Region`` would rank as a name the live table does not
    hold and go last.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    live = _live_with(["amount", "region"], {"region": "the sales region"})
    glue, _sqs = _install(table=live)
    columns = [
        {"name": "Region", "type": "string"},
        {"name": "Amount", "type": "string"},
        {"name": "Notes", "type": "string"},
    ]

    m.handler(_event(columns=columns), None)

    written = glue.table_input["StorageDescriptor"]["Columns"]
    assert [(c["Name"], c.get("Comment")) for c in written] == [
        ("amount", None), ("region", "the sales region"), ("notes", None)
    ]


@pytest.mark.parametrize("fmt", ["parquet", "json"])
def test_a_name_matched_format_still_writes_the_first_files_order(fmt):
    """Parquet and JSON are read by name, so the order decides only how ``SELECT *`` lays the
    columns out and the reorder must not reach them.

    The format is set explicitly: the event factory defaults it to ``csv``, so a test that left
    it alone would exercise the branch this one exists to stay out of.

    Args:
      fmt: The name-matched source format under test.

    Returns:
      None.

    Raises:
      None.
    """
    glue, _sqs = _install(table=_live_with(["a", "b", "c"]))
    columns = [{"name": name, "type": "string"} for name in ("a", "new", "b", "c")]

    m.handler(_event(columns=columns, format=fmt), None)

    written = [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]]
    assert written == ["a", "new", "b", "c"]


def test_a_csv_namesake_the_table_does_not_yet_declare_is_new_and_lands_last():
    """A partition namesake the live table has never declared is a NEW column, so the reorder puts
    it last like any other — it does not take the file's position.

    This is the one case where a partitioned CSV table's write differs from what it was before the
    order was kept, and it is the accepted cost rather than a defect: a table built under the old
    drop rule gains `year_in_file` at the end, so it stays shifted and repairing it is a rebuild.
    Asserted here because four documents state it and nothing else runs it.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    storage = {
        **_live_table()["StorageDescriptor"],
        "Columns": [{"Name": "id", "Type": "string"}, {"Name": "region", "Type": "string"}],
    }
    live = _live_table(StorageDescriptor=storage, PartitionKeys=[{"Name": "year", "Type": "string"}])
    glue, _sqs = _install(table=live)
    columns = [
        {"name": "Year", "type": "string"},
        {"name": "id", "type": "string"},
        {"name": "region", "type": "string"},
    ]
    keys = [{"name": "year", "type": "string", "values": ["2025"]}]

    m.handler(_event(columns=columns, partitionKeys=keys), None)

    written = [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]]
    assert written == ["id", "region", "year_in_file"]


def test_a_removed_csv_column_comes_back_at_the_end_rather_than_in_its_old_place():
    """A column the table dropped is NEW when it returns, so it lands last and the table does not
    go back to the order it had. Pinned because it is the cost this rule accepts, not an accident.

    An opted-in removal is what shifts a CSV table — `a,b,c` minus `b` reads a file headed `a,b,c`
    with `b`'s values under `c` — and restoring `b` to the first file cannot undo that here: the
    live table no longer records where `b` sat. Writing the first file's order did repair this one
    sequence, and that repair is what taking the table's order gives up; taking the file's order is
    the far commoner harm this rule exists to stop. Repairing a drifted table is out of the spec's
    scope and a refusal was rejected, so the table is rebuilt instead, and the Refresh guide says
    so. If this starts failing, the rule changed — revisit the decision, do not delete the test.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    glue, _sqs = _install(table=_live_with(["a", "c"]))
    columns = [{"name": name, "type": "string"} for name in ("a", "b", "c")]

    m.handler(_event(columns=columns), None)

    written = [c["Name"] for c in glue.table_input["StorageDescriptor"]["Columns"]]
    assert written == ["a", "c", "b"]


def test_an_event_without_a_format_is_malformed_and_writes_nothing():
    """The format decides what a partition's namesake is written as, so guessing it could write
    a list diff-schema never compared.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    glue, _sqs = _install(table=_live_table())
    event = _event()
    del event["format"]

    with pytest.raises(TerminalError) as raised:
        m.handler(event, None)

    assert raised.value.reason == "malformed_event"
    assert "format" in raised.value.detail
    assert glue.update_calls == []


def test_columns_differing_only_by_case_are_refused_before_the_update():
    """Refuses a header whose names fold together, before Glue is asked to write anything.

    The fold turns ``Amount`` and ``amount`` into one column name. An update does not reject
    duplicate names the way Athena's ``CREATE`` does, and the read-back compares name sets, so
    both spellings collapse on each side and a missing refusal would report success while the
    table silently lost a column. Diff-schema refuses this header before the verb runs, so this
    is the backstop, pinned because nothing after the fold would notice it gone. The header also
    adds ``notes`` so that the definition differs from the live one for more than the collision.
    The verb's other ``update_failed`` refusals come from the update call or the read-back
    after it, so an untouched ``update_table`` and a detail naming the column are what pin this
    one.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    storage = {
        **_live_table()["StorageDescriptor"],
        "Columns": [
            {"Name": "amount", "Type": "string"},
            {"Name": "region", "Type": "string"},
        ],
    }
    glue, _sqs = _install(table=_live_table(StorageDescriptor=storage))
    columns = [
        {"name": "Amount", "type": "string"},
        {"name": "region", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "notes", "type": "string"},
    ]
    diff = {
        "changed": True,
        "added": [{"name": "notes", "type": "string"}],
        "removed": [],
        "retyped": [],
        "unchanged": 2,
    }

    with pytest.raises(TerminalError) as raised:
        m.handler(_event(columns=columns, diff=diff), None)

    assert raised.value.reason == "update_failed"
    assert "amount" in raised.value.detail, raised.value.detail
    assert glue.update_calls == [], "the colliding definition was sent to Glue"


def test_a_retyped_column_takes_the_fresh_type_and_keeps_its_comment():
    """Retyping is a legitimate refresh outcome: the TYPE is the verb's to change, the
    comment is not."""
    glue, _sqs = _install()

    m.handler(_event(columns=[{"name": "order_id", "type": "bigint"}]), None)
    written = glue.table_input["StorageDescriptor"]["Columns"][0]

    assert written["Type"] == "bigint"
    assert written["Comment"] == "the shop's own id"


# ── Partitioned tables ───────────────────────────────────────────────────────


_KEYS = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]


def _partitioned_live(year_range, **over):
    """A partitioned live table whose projection range the test chooses."""
    live = _live_table(PartitionKeys=[{"Name": "year", "Type": "int"}], **over)
    live["Parameters"] = {
        **live["Parameters"],
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": year_range,
        "projection.year.digits": "4",
    }
    return live


def test_a_retype_over_a_table_another_writer_changed_is_abandoned_rather_than_written_over():
    """The run loaded the table with years to 2100; while it inferred, the user widened the
    projection to 2200. A retype keeps the column NAMES, so a check on names alone read the moved
    stamp as this run's own landed update and wrote 2100 back — every partition past it gone from
    every query. The live table must carry exactly what this run writes for that reading to hold."""
    glue, _sqs = _install(table=_partitioned_live("2000,2200", UpdateTime="2026-03-01T00:00:00Z"))
    event = _event(
        observedUpdateTime="2026-02-01T00:00:00Z",
        partitionKeys=_KEYS,
        columns=[{"name": "order_id", "type": "bigint"}],
    )

    with pytest.raises(TerminalError) as err:
        m.handler(event, None)

    assert err.value.reason == "table_changed_during_refresh"
    assert glue.update_calls == []


def test_a_retry_after_this_runs_own_update_landed_rewrites_it_rather_than_refusing():
    """The other half of the same check, and why it exists: a Lambda retry can re-run the verb
    after its update committed, and the stamp it moved itself must not read as another writer."""
    glue, _sqs = _install(table=_partitioned_live("2000,2100"))
    event = _event(partitionKeys=_KEYS, columns=[{"name": "order_id", "type": "bigint"}])
    m.handler(event, None)
    glue.table = {**glue.table, "UpdateTime": "2026-03-01T00:00:00Z"}
    glue.update_calls.clear()

    result = m.handler({**event, "observedUpdateTime": "2026-02-01T00:00:00Z"}, None)

    assert result["status"] == "refreshed"
    assert len(glue.update_calls) == 1


# ── SPEC-153 FR-006: the Athena case-fold premise, pinned ────────────────────


# ── SPEC-157: the shapes boto3 ACTUALLY returns ──────────────────────────────

_AWARE = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)


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
    recorded as owed. Note the comment survives the re-casing — the carry is keyed on the same
    fold as the write — so this is a rename, not a column swap.

    If this starts failing, the fold changed: revisit the decision (docs/decisions/analytics.md, "Removing a
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


def test_the_three_glue_round_trips_are_three_child_spans(captured_events):
    """THREE spans, because this verb makes three Glue calls with no principal one among them.

    Three and not four: `_abandon_if_changed`, which sits between the read and the update, makes
    no round trip — it compares a stamp on the response already in hand. An arbitrary pick of one
    of the three would leave an operator unable to tell a slow read from a slow write.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _install()

    out = m.handler(_event(), None)

    assert out["status"] == "refreshed", "the spans are asserted on a SUCCESSFUL run"
    root = captured_events.spans("apply-refresh")
    assert len(root) == 1, f"expected one apply-refresh root span, got {len(root)}"
    for name in ("glue-get-table", "glue-update-table", "glue-read-back-table"):
        children = captured_events.child_spans("apply-refresh", name=name)
        assert len(children) == 1, (
            f"apply-refresh emitted {len(children)} {name!r} child spans, expected exactly one"
        )
        assert children[0]["parent_span_id"] == root[0]["span_id"]
