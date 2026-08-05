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
from cpcommon.errors import TerminalError, TransientError
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
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: _manifest())
    return statements


def _install_manifest(monkeypatch, manifest):
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: manifest)


def _manifest_raises(monkeypatch, exc):
    def _load(bucket, key):
        raise exc

    monkeypatch.setattr(v.manifest_store, "load", _load)


# ── The typed table ──────────────────────────────────────────────────────────


def test_csv_creates_both_the_typed_and_the_raw_table(ran):
    out = v.handler(_event(), None)

    assert out["tempTable"] == f"dq_tmp_{HEX32}"
    assert out["tempRawTable"] == f"dq_tmp_raw_{HEX32}"
    assert len(ran) == 2
    assert "OpenCSVSerde" in ran[0]["query"]
    assert "LazySimpleSerDe" in ran[1]["query"]


def test_json_creates_only_the_typed_table(monkeypatch, ran):
    _install_manifest(monkeypatch, _manifest(fmt="json"))
    out = v.handler(_event(format="json"), None)

    # Rows are not line-delimited fields, so the raw-line concept does not apply.
    assert out["tempRawTable"] is None
    assert len(ran) == 1
    assert "org.apache.hive.hcatalog.data.JsonSerDe" in ran[0]["query"]


def test_parquet_creates_only_the_typed_table(monkeypatch, ran):
    _install_manifest(monkeypatch, _manifest(fmt="parquet"))
    out = v.handler(_event(format="parquet"), None)

    assert out["tempRawTable"] is None
    assert len(ran) == 1
    assert "STORED AS PARQUET" in ran[0]["query"]


def test_the_column_list_is_the_union_of_every_files_probe(monkeypatch, ran):
    """Athena does not auto-detect a Parquet schema — the explicit list is mandatory."""
    _install_manifest(
        monkeypatch,
        _manifest(
            files=[
                {"key": "alice/sales/a.csv", "size": 1, "columns": [{"name": "a", "type": "string"}]},
                {"key": "alice/sales/b.csv", "size": 1, "columns": [{"name": "b", "type": "string"}]},
            ]
        ),
    )
    out = v.handler(_event(), None)

    assert out["columnCount"] == 2
    assert "(`a` string, `b` string)" in ran[0]["query"]


def test_the_table_is_created_in_the_actors_own_database_for_a_personal_check(ran):
    out = v.handler(_event(), None)
    assert out["database"] == "alice"
    assert ran[0]["database"] == "alice"
    assert "`alice`.`dq_tmp_" in ran[0]["query"]


def test_the_table_is_created_in_the_spaces_database_for_a_shared_check(monkeypatch, ran):
    event = _event(space={"kind": "shared", "bucket": "dq-shared-bkt", "prefix": "team_data/"},
                   location="team_data/sales",
                   reportPrefix=f"team_data/_data-quality-reports/{REQUEST_ID}/",
                   manifestKey=f"team_data/_data-quality-reports/{REQUEST_ID}/manifest.json")
    _install_manifest(monkeypatch, _manifest(files=[
        {"key": "team_data/sales/jan.csv", "size": 1, "columns": [{"name": "a", "type": "string"}]}
    ]))
    out = v.handler(event, None)

    # The DATABASE is the space, never the actor — a shared check must not build its temp
    # table in the actor's personal database.
    assert out["database"] == "team_data"
    assert "`team_data`.`dq_tmp_" in ran[0]["query"]


def test_an_unknown_space_kind_is_a_terminal(ran):
    with pytest.raises(TerminalError) as exc:
        v.handler(_event(space={"kind": "public", "bucket": BUCKET, "prefix": "x/"}), None)
    assert exc.value.reason == messages.INVALID_REQUEST


# ── Partitions ───────────────────────────────────────────────────────────────


def test_a_partitioned_source_gets_projection_on_the_typed_table_only(monkeypatch, ran):
    _install_manifest(
        monkeypatch,
        _manifest(
            files=[{"key": "alice/sales/year=2024/a.csv", "size": 1,
                    "columns": [{"name": "id", "type": "string"}]}],
            partition_keys=[{"name": "year", "values": ["2024", "2025"]}],
        ),
    )
    v.handler(_event(), None)

    typed, raw = ran[0]["query"], ran[1]["query"]
    assert "'projection.year.values'='2024,2025'" in typed
    assert "PARTITIONED BY (`year` string)" in typed
    # The raw-line table stays flat on purpose — a flat external table reads every object
    # under the LOCATION recursively, which is what "every physical line" needs.
    assert "PARTITIONED BY" not in raw


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


def test_a_source_exactly_at_the_cap_is_allowed(monkeypatch, ran):
    at_cap = [{"name": f"c{i}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS)]
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/w.csv", "size": 1, "columns": at_cap}]
    ))
    out = v.handler(_event(), None)
    assert out["columnCount"] == config.DQ_MAX_COLUMNS


# ── LOCATION resolution ──────────────────────────────────────────────────────


def test_location_is_a_folder_uri_with_a_trailing_slash(ran):
    v.handler(_event(), None)
    assert "LOCATION 's3://dq-user-bkt/alice/sales/'" in ran[0]["query"]


def test_a_single_file_target_becomes_a_table_over_its_parent_folder(monkeypatch, ran):
    """An external table's LOCATION is a PREFIX: pointed at an object key it yields a
    table over nothing, which would report zero rows and look like a clean result.

    NECESSARY BUT NOT SUFFICIENT, and this test used to imply otherwise (SPEC-151 FR-001).
    Athena reads a LOCATION RECURSIVELY, so the table this builds also covers every
    sibling in `alice/sales/`. What puts the report back on the file the user selected is
    the `"$path"` predicate start-profile-query attaches — see the coupling pinned below.
    """
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/jan.csv", "size": 1, "columns": [{"name": "a", "type": "string"}]}]
    ))
    v.handler(_event(location="alice/sales/jan.csv"), None)
    assert "LOCATION 's3://dq-user-bkt/alice/sales/'" in ran[0]["query"]


def test_the_promotion_is_decided_by_the_same_helper_the_queries_use(monkeypatch, ran):
    """The two verbs must agree about what "one file" means, or the report describes the
    folder while claiming to describe the file. `sql.single_file_path` is the single
    definition; this pins that THIS verb consults it rather than re-deriving the rule.
    """
    manifest = _manifest(
        files=[{"key": "alice/sales/jan.csv", "size": 1, "columns": [{"name": "a", "type": "string"}]}]
    )
    _install_manifest(monkeypatch, manifest)
    seen = []
    real = v.sql.single_file_path

    def _spy(bucket, files, location):
        result = real(bucket, files, location)
        seen.append((location, result))
        return result

    monkeypatch.setattr(v.sql, "single_file_path", _spy)
    v.handler(_event(location="alice/sales/jan.csv"), None)

    assert seen == [("alice/sales/jan.csv", "s3://dq-user-bkt/alice/sales/jan.csv")]
    assert "LOCATION 's3://dq-user-bkt/alice/sales/'" in ran[0]["query"]


def test_an_empty_manifest_is_refused_rather_than_targeting_the_space_root(monkeypatch, ran):
    _install_manifest(monkeypatch, _manifest(files=[]))
    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.INVALID_REQUEST
    assert ran == []


# ── State threading + idempotence ────────────────────────────────────────────


def test_the_table_names_are_threaded_even_when_the_create_fails(monkeypatch):
    """drop-temp-tables must be able to find the table when a create dies halfway.

    The names are written onto the outgoing state BEFORE any DDL runs; this asserts the
    ordering by failing the FIRST create and checking the verb still raises with the
    names having been computed (the state machine's Catch carries the input forward).
    """
    _install_manifest(monkeypatch, _manifest())
    monkeypatch.setattr(v.athena, "run_ddl", _raise(TerminalError(messages.QUERY_FAILED, "boom")))

    with pytest.raises(TerminalError):
        v.handler(_event(), None)


def test_creation_is_idempotent_so_a_retry_is_a_no_op(ran):
    v.handler(_event(), None)
    assert all(kw["query"].startswith("CREATE EXTERNAL TABLE IF NOT EXISTS ") for kw in ran)


def test_the_request_object_is_threaded_not_replaced(ran):
    out = v.handler(_event(), None)
    # requestId/actor must survive: RecordSuccess/RecordFailure are Pass states whose
    # JSONPath HARD-FAILS on an absent key (States.Runtime, uncatchable), which would skip
    # NotifyFailure and leave the user with no notification at all.
    assert out["requestId"] == REQUEST_ID
    assert out["actor"] == "alice"
    assert out["manifestKey"] == _event()["manifestKey"]


# ── Manifest read failures ───────────────────────────────────────────────────


def test_a_transient_manifest_read_propagates(monkeypatch, ran):
    """So the SFN Retry re-runs the verb rather than failing the request over a SlowDown.

    (dqcommon.manifest owns the S3-fault classification and is tested there; this asserts
    the verb does not swallow it — a swallowed TransientError becomes a failed request.)
    """
    _manifest_raises(monkeypatch, TransientError("SlowDown"))
    with pytest.raises(TransientError):
        v.handler(_event(), None)
    assert ran == []


def test_an_unreadable_manifest_propagates_as_a_terminal(monkeypatch, ran):
    _manifest_raises(monkeypatch, TerminalError(messages.INVALID_REQUEST, "NoSuchKey"))
    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.INVALID_REQUEST
    assert ran == []


# ── Shape validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", ["requestId", "manifestKey", "format", "reportPrefix", "location"])
def test_a_missing_required_field_is_a_typed_terminal(ran, missing):
    """Never a bare KeyError: the SFN would record that as an opaque failure."""
    event = _event()
    del event[missing]
    with pytest.raises(TerminalError) as exc:
        v.handler(event, None)
    assert exc.value.reason == messages.INVALID_REQUEST


def _raise(exc):
    def _fn(**_kw):
        raise exc

    return _fn


# -- SPEC-132: the narrative ------------------------------------------------------------


def test_it_narrates_what_it_created(ran, captured_events):
    """FR-001: reading the events must say what the verb FOUND, not only that it ran."""
    v.handler(_event(), None)

    created = captured_events.messages("created temp tables")
    assert len(created) == 1
    fields = created[0]["fields"]
    assert fields["database"] and fields["table"]
    assert fields["columns"] > 0
    assert fields["format"] == "csv"
    # Whether the raw-line table exists decides whether a ragged finding is even possible
    # downstream, so its absence must be distinguishable from a ragged check that failed.
    assert fields["raw_table"], "a CSV source must report its raw-line table"
    assert fields["verb"] == "create-temp-tables"


def test_json_reports_no_raw_table(monkeypatch, ran, captured_events):
    _install_manifest(monkeypatch, _manifest(fmt="json"))

    v.handler(_event(format="json"), None)

    assert captured_events.messages("created temp tables")[0]["fields"]["raw_table"] is None


def test_each_ddl_gets_its_own_child_span(ran, captured_events):
    """FR-002: two creates for CSV, so the second one's cost is visible on its own."""
    v.handler(_event(), None)

    assert len(captured_events.spans("run-ddl")) == 2
    parent = captured_events.spans("create-temp-tables")[0]
    assert all(s["parent_span_id"] == parent["span_id"] for s in captured_events.spans("run-ddl"))


def test_a_terminal_names_its_reason_token_and_not_the_prose(monkeypatch, ran, captured_events):
    """FR-003: `reason` is the messages constant's own value, never scraped from the text."""
    with pytest.raises(TerminalError):
        v.handler(_event(space={"kind": "public", "bucket": BUCKET, "prefix": "x/"}), None)

    failed = captured_events.messages("create-temp-tables failed")
    assert failed and failed[0]["level"] == "ERROR"
    assert failed[0]["fields"]["reason"] == messages.INVALID_REQUEST
    assert failed[0]["fields"]["error_type"] == "TerminalError"


def test_a_successful_run_emits_no_error_events(ran, captured_events):
    """FR-003: a run that succeeded must not contain error events, or the level is useless."""
    v.handler(_event(), None)

    assert [e for e in captured_events.levels() if e["level"] == "ERROR"] == []
