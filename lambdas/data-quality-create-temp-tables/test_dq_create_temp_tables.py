"""Unit tests for the data-quality create-temp-tables Lambda (SPEC-111 FR-001/FR-002).

AWS stubbed: the S3 client (the manifest read) and ``athena.run_ddl`` are replaced on the
verb module, so no bucket and no catalog is touched. The assertions are mostly about the
DDL that WOULD have been run, because that is the whole output of this verb.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_create_temp_tables as v
import pytest
from cpcommon.errors import TerminalError
from dqcommon import config, messages

BUCKET = "dq-user-bkt"
REQUEST_ID = "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
HEX32 = "7f3ac19d2b4e4c8a9f016d5e3a7b8c02"


def _event(**overrides):
    event = {
        "requestId": REQUEST_ID,
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "location": "alice/sales",
        "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
        "manifestKey": f"alice/_data-quality-reports/{REQUEST_ID}/manifest.json",
        "format": "csv",
        "pathFilter": None,
    }
    event.update(overrides)
    return event


_DEFAULT_FILES = [
    {
        "key": "alice/sales/jan.csv",
        "size": 10,
        "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
    }
]


def _manifest(files=None, partition_keys=None, fmt="csv"):
    # `is not None`, NOT `or`: an EMPTY file list is a case under test (the guard against
    # building a table over the space root), and `or` would silently swap it for the
    # default — making that test assert nothing.
    resolved = _DEFAULT_FILES if files is None else files
    return {
        "requestId": REQUEST_ID,
        "format": fmt,
        "fileCount": len(resolved),
        "partitionKeys": partition_keys or [],
        "files": resolved,
    }


@pytest.fixture
def ran(monkeypatch):
    """Capture every DDL statement the verb would run, with a default manifest stubbed."""
    statements = []
    monkeypatch.setattr(v.athena, "run_ddl", lambda **kw: statements.append(kw) or "qid-1")
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key, location: _manifest())
    return statements


def _install_manifest(monkeypatch, manifest):
    """Installs the manifest and returns the locations each load was contained to."""
    loaded = []

    def _load(bucket, key, location):
        loaded.append(location)
        return manifest

    monkeypatch.setattr(v.manifest_store, "load", _load)
    return loaded


# ── The typed table ──────────────────────────────────────────────────────────


def test_csv_creates_both_the_typed_and_the_raw_table(ran):
    out = v.handler(_event(), None)

    assert out["tempTable"] == f"dq_tmp_{HEX32}"
    assert out["tempRawTable"] == f"dq_tmp_raw_{HEX32}"
    assert len(ran) == 2
    assert "OpenCSVSerde" in ran[0]["query"]
    assert "LazySimpleSerDe" in ran[1]["query"]


def test_a_csv_column_naming_a_partition_before_a_kept_one_is_a_terminal_that_names_it(
    monkeypatch, ran
):
    """The typed table leaves out a column naming a partition, and a CSV is read by position, so
    profiling this file would report `id` and `month` against their neighbours' values. A report
    the user acts on is worse than none, so the check refuses it the way the build does."""
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/year=2025/Month=01/jan.csv", "size": 1, "columns": [
            {"name": "Year", "type": "string"},
            {"name": "id", "type": "string"},
            {"name": "month", "type": "string"},
        ]}],
        partition_keys=[{"name": "year", "values": ["2025"]}, {"name": "Month", "values": ["01"]}],
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.PARTITION_COLUMN_NOT_LAST
    assert exc.value.tokens["columns"] == '"Year"'
    # Nothing was created: the refusal fires BEFORE any DDL runs.
    assert ran == []


# ── The table's LOCATION ─────────────────────────────────────────────────────


def test_a_file_at_the_space_root_builds_its_table_over_the_root(monkeypatch, ran):
    """The carve-out the space-root refusal deliberately leaves open, made explicit.

    A one-file target promotes to its parent folder, and for a file sitting at the top of a
    space that parent IS the space root — the very location a FOLDER target is now refused
    for. What makes the two consistent is not the location but the `"$path"` predicate the
    queries carry, so this test exists to state the premise out loud: the table really is
    over the root, and the predicate is the only thing narrowing it.
    """
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/report.csv", "size": 10, "columns": [{"name": "a", "type": "string"}]}]
    ))

    v.handler(_event(location="alice/report.csv", pathFilter=f"s3://{BUCKET}/alice/report.csv"), None)

    assert f"LOCATION 's3://{BUCKET}/alice/'" in ran[0]["query"]


@pytest.mark.parametrize(
    ("path_filter", "listed", "expected"),
    [
        (f"s3://{BUCKET}/alice/sales/jan.csv", ["alice/sales/jan.csv", "alice/sales/feb.csv"], "alice/sales/"),
        (None, ["alice/sales/jan.csv"], "alice/sales/jan.csv/"),
    ],
    ids=["single-file-state-two-file-manifest", "folder-state-one-file-manifest"],
)
def test_the_promotion_follows_the_carried_decision_not_the_manifest(
    monkeypatch, ran, path_filter, listed, expected
):
    """The table and the queries are narrowed on ONE value, so the manifest cannot split them.

    The manifest is re-read on every attempt of this verb and again by the query verb, and a
    caller could once overwrite it in between. Each row hands this verb a manifest that disagrees
    with the carried decision — the swap a retry or the query verb would have seen — and the
    LOCATION must still be the one the state's decision implies.
    """
    loaded = _install_manifest(monkeypatch, _manifest(
        files=[{"key": key, "size": 1, "columns": [{"name": "a", "type": "string"}]} for key in listed]
    ))

    v.handler(_event(location="alice/sales/jan.csv", pathFilter=path_filter), None)

    assert f"LOCATION 's3://{BUCKET}/{expected}'" in ran[0]["query"]
    assert loaded == ["alice/sales/jan.csv"], "the manifest must be contained to the checked location"


def test_a_state_without_the_carried_decision_is_refused_before_any_ddl(ran):
    """Absent is not "a folder": defaulting it would build a promoted table nobody narrows."""
    event = _event()
    del event["pathFilter"]

    with pytest.raises(TerminalError) as exc:
        v.handler(event, None)

    assert exc.value.reason == messages.INVALID_REQUEST
    assert "pathFilter" in exc.value.detail
    assert ran == []


def test_a_location_that_escapes_the_space_is_refused_before_any_ddl(monkeypatch, ran):
    """The last containment check between an authorized LOCATION and what Athena is handed.

    `_location` rstrips, splits on the last slash and reassembles, and nothing downstream
    re-checks the result against the space the actor was authorized for. A single-file check
    whose file sits outside the space would otherwise promote the table out of it.
    """
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "bob/secrets.csv", "size": 10, "columns": [{"name": "a", "type": "string"}]}]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(location="bob/secrets.csv", pathFilter=f"s3://{BUCKET}/bob/secrets.csv"), None)

    assert exc.value.reason == messages.INVALID_REQUEST
    assert "escapes the space" in exc.value.detail
    assert ran == []


# ── Which database the temp tables land in ───────────────────────────────────
#
# The resolver moved to `dqcommon.sql` so cleanup could reach the same answer without this
# verb's output. These pin it from the caller that still has a terminal to raise. None of
# them is reachable past the validate verb, which pins a personal prefix to the actor and
# loads a shared space from the registry — they exist because the refusal is what keeps a
# malformed state from quietly becoming a database NAME, and a resolver with two callers
# earns the check the single-caller version got for free from `events.require`.


@pytest.mark.parametrize(
    "space,actor",
    [
        ({"kind": "wat", "bucket": BUCKET, "prefix": "alice/"}, "alice"),
        ({"kind": "personal", "bucket": BUCKET, "prefix": "alice/"}, "   "),
        ({"kind": "shared", "bucket": BUCKET, "prefix": "   "}, "alice"),
        ({"kind": "shared", "bucket": BUCKET, "prefix": "/"}, "alice"),
    ],
    ids=["unknown-kind", "blank-actor", "blank-shared-prefix", "slash-only-shared-prefix"],
)
def test_a_state_with_no_resolvable_database_is_a_terminal_not_a_default(space, actor, ran):
    """Each of these used to have a way of NOT refusing.

    An unknown kind reaching a fallback would create the tables in the actor's own database.
    A blank actor or prefix would become the database NAME itself, and a slash-only shared
    prefix an EMPTY one. All four answer None from the resolver, and the refusal is raised
    here rather than there, because cleanup shares the resolver and may never raise.
    """
    with pytest.raises(TerminalError) as exc:
        v.handler(_event(space=space, actor=actor), None)

    assert exc.value.reason == messages.INVALID_REQUEST
    assert "no database for space kind" in exc.value.detail
    assert ran == []


# ── The width cap ────────────────────────────────────────────────────────────


def test_a_source_wider_than_the_cap_is_a_terminal_too_many_columns(monkeypatch, ran):
    wide = [{"name": f"c{i}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS + 1)]
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/w.csv", "size": 1, "columns": wide}]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.TOO_MANY_COLUMNS
    # And nothing was created — the cap fires BEFORE any DDL runs, so a too-wide source
    # cannot leak a table.
    assert ran == []


# ── Column names ─────────────────────────────────────────────────────────────
#
# The reported bug: a data-quality check said nothing about column names, so a folder whose
# headers Athena cannot use passed the check and then produced an unbuildable — or worse, a
# built-but-unreadable — table. The check cannot report on data it cannot read, so the answer
# is a refusal naming the columns rather than a report that never gets built.


def test_a_header_athena_cannot_use_is_a_terminal_that_names_the_columns(monkeypatch, ran):
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/jan.csv", "size": 1, "columns": [
            {"name": "order_id", "type": "string"},
            {"name": "Order ID", "type": "string"},
        ]}]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.INVALID_COLUMN_NAMES
    assert exc.value.tokens["columns"] == '"Order ID"'
    # Nothing was created: the check fires BEFORE any DDL runs, so a refused source cannot
    # leak a temp table into the user's own database.
    assert ran == []


def test_headers_differing_only_by_case_across_files_are_declared_once(monkeypatch, ran):
    """No single file clashes, so the folder is one table: each column declared once, under the
    first file's spelling and type, where the exact-name union declared both and refused the
    collision."""
    _install_manifest(monkeypatch, _manifest(
        files=[
            {"key": "alice/sales/jan.parquet", "size": 1, "columns": [
                {"name": "CustomerID", "type": "bigint"},
                {"name": "Region", "type": "string"},
            ]},
            {"key": "alice/sales/feb.parquet", "size": 1, "columns": [
                {"name": "customerid", "type": "string"},
                {"name": "REGION", "type": "string"},
            ]},
        ],
        fmt="parquet",
    ))

    out = v.handler(_event(format="parquet"), None)

    assert out["columnCount"] == 2
    assert "(`CustomerID` bigint, `Region` string)" in ran[0]["query"]


def test_a_case_collision_inside_one_file_is_still_refused_with_every_files_offenders(monkeypatch, ran):
    """Merged, ``Total,TOTAL`` would be declared as one column and a CSV read by position would
    take every later column from its neighbour. The refusal names every file's offenders at once,
    so fixing the first file never reveals the second's."""
    _install_manifest(monkeypatch, _manifest(
        files=[
            {"key": "alice/sales/jan.csv", "size": 1, "columns": [
                {"name": "Total", "type": "string"},
                {"name": "TOTAL", "type": "string"},
                {"name": "region", "type": "string"},
            ]},
            {"key": "alice/sales/feb.csv", "size": 1, "columns": [
                {"name": "total", "type": "string"},
                {"name": "Order ID", "type": "string"},
            ]},
            {"key": "alice/sales/mar.csv", "size": 1, "columns": [
                {"name": "total", "type": "string"},
                {"name": "Order ID", "type": "string"},
            ]},
        ]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.INVALID_COLUMN_NAMES
    assert exc.value.tokens["columns"] == '"Total", "TOTAL", "Order ID"'
    assert ran == []


# ── Shape validation ─────────────────────────────────────────────────────────


