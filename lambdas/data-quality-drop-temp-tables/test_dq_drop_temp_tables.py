"""Unit tests for the data-quality drop-temp-tables Lambda (SPEC-111 FR-005).

AWS stubbed: ``athena.run_ddl`` is replaced on the verb module. The properties under test
are the ones that make this verb safe to invoke from EVERY path — idempotence, tolerance
of having nothing to do, and never raising.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402
from dqcommon import messages  # noqa: E402

import dq_drop_temp_tables as v  # noqa: E402

BUCKET = "dq-user-bkt"
REQUEST_ID = "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
HEX32 = "7f3ac19d2b4e4c8a9f016d5e3a7b8c02"


def _event(**overrides):
    event = {
        "requestId": REQUEST_ID,
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
        "database": "alice",
        "tempTable": f"dq_tmp_{HEX32}",
        "tempRawTable": f"dq_tmp_raw_{HEX32}",
    }
    event.update(overrides)
    return event


@pytest.fixture
def ran(monkeypatch):
    statements = []
    monkeypatch.setattr(v.athena, "run_ddl", lambda **kw: statements.append(kw) or "qid-1")
    return statements


def _fail_with(monkeypatch, exc):
    def _raise(**_kw):
        raise exc

    monkeypatch.setattr(v.athena, "run_ddl", _raise)


# ── The happy path ───────────────────────────────────────────────────────────


def test_it_drops_both_tables(ran):
    out = v.handler(_event(), None)

    assert [kw["query"] for kw in ran] == [
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_{HEX32}`",
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_raw_{HEX32}`",
    ]
    assert out["cleanup"]["dropped"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]
    assert out["cleanup"]["failed"] == []


def test_it_drops_only_the_typed_table_when_there_is_no_raw_table(ran):
    """JSON/Parquet never got a raw-line table."""
    out = v.handler(_event(tempRawTable=None), None)

    assert len(ran) == 1
    assert out["cleanup"]["dropped"] == [f"dq_tmp_{HEX32}"]


def test_the_drop_is_idempotent(ran):
    """IF EXISTS is the whole of the idempotence — dropping a gone table is a success."""
    v.handler(_event(), None)
    assert all(kw["query"].startswith("DROP TABLE IF EXISTS ") for kw in ran)


def test_it_drops_in_the_shared_spaces_database_for_a_shared_check(ran):
    out = v.handler(
        _event(database="team_data", space={"kind": "shared", "bucket": "dq-shared-bkt", "prefix": "team_data/"}),
        None,
    )
    assert "`team_data`.`dq_tmp_" in ran[0]["query"]
    assert out["cleanup"]["failed"] == []


# ── Reached before anything was created (FR-005) ─────────────────────────────


def test_nothing_to_drop_is_a_success_not_an_error(ran):
    """The overwhelmingly common failure case: a validator or inspection failure, where
    create-temp-tables never ran and the state carries no table names at all."""
    out = v.handler({"requestId": REQUEST_ID, "actor": "alice"}, None)

    assert ran == []
    assert out["cleanup"] == {"dropped": [], "failed": [], "skipped": True}


def test_a_database_with_no_table_names_is_also_a_no_op(ran):
    out = v.handler(_event(tempTable=None, tempRawTable=None), None)
    assert ran == []
    assert out["cleanup"]["skipped"] is True


def test_table_names_without_a_database_is_a_no_op(ran):
    """Half-populated state must not produce a DROP against an empty database name."""
    out = v.handler(_event(database=None), None)
    assert ran == []
    assert out["cleanup"]["skipped"] is True


def test_a_non_dict_event_does_not_crash(ran):
    out = v.handler(None, None)
    assert out["cleanup"]["skipped"] is True


# ── Never raising (FR-005) ───────────────────────────────────────────────────


def test_a_drop_failure_is_swallowed_so_it_cannot_mask_the_original_reason(monkeypatch, ran):
    """On the failure path, raising here would replace the reason the user is notified
    about with a cleanup error. On the success path it would tell the user their check
    failed while their report sits finished in S3. Neither is acceptable."""
    _fail_with(monkeypatch, TerminalError(messages.QUERY_FAILED, "glue exploded"))

    out = v.handler(_event(), None)  # must not raise

    assert out["cleanup"]["dropped"] == []
    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]


def test_a_transient_drop_failure_is_also_swallowed(monkeypatch, ran):
    """Even a retryable fault: an SFN Retry on the SUCCESS path would eventually exhaust
    and fail a request whose report is already written."""
    _fail_with(monkeypatch, TransientError("throttled"))

    out = v.handler(_event(), None)  # must not raise

    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]


def test_a_failure_on_the_first_table_still_attempts_the_second(monkeypatch):
    """One stuck table must not strand the other — that would leak the one we could drop."""
    calls = []

    def _flaky(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise TerminalError(messages.QUERY_FAILED, "first one failed")
        return "qid-2"

    monkeypatch.setattr(v.athena, "run_ddl", _flaky)
    out = v.handler(_event(), None)

    assert len(calls) == 2
    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}"]
    assert out["cleanup"]["dropped"] == [f"dq_tmp_raw_{HEX32}"]


def test_a_leaked_table_is_logged_loudly(monkeypatch, caplog):
    """The leak is recoverable only if an operator can find it."""
    _fail_with(monkeypatch, TerminalError(messages.QUERY_FAILED, "boom"))

    with caplog.at_level("ERROR"):
        v.handler(_event(), None)

    assert "LEAKED TEMP TABLE" in caplog.text
    assert f"dq_tmp_{HEX32}" in caplog.text


# ── The failure-path invocation shape ────────────────────────────────────────


@pytest.mark.parametrize(
    "cause",
    [
        '{"errorMessage": "query_failed: boom", "errorType": "TerminalError"}',
        "The cause could not be determined.",  # a plain-sentence Cause
        None,                                   # no Cause key at all
    ],
)
def test_it_handles_the_failure_paths_event_shape(ran, cause):
    """DropTempTablesOnFailure passes the whole state through, including $.error.

    RecordFailure reads $.error AFTER this verb returns, so a cleanup verb that dropped or
    reshaped it would leave the user with no reason for the failure. Parametrized over the
    Cause shapes that used to matter: the ASL decode that once sat between here and
    RecordFailure died on the last two, so this verb must carry ALL of them intact and let
    cpcommon.errors.failure_reason sort them out later.
    """
    event = _event()
    event["error"] = {"Error": "TerminalError"}
    if cause is not None:
        event["error"]["Cause"] = cause

    out = v.handler(event, None)

    assert len(ran) == 2
    assert out["error"] == event["error"]


def test_the_request_object_is_threaded_not_replaced(ran):
    out = v.handler(_event(), None)
    assert out["requestId"] == REQUEST_ID
    assert out["actor"] == "alice"


def test_a_mid_query_failure_leaves_no_temp_table_behind(monkeypatch):
    """FR-005's cleanup assertion, exercised across the two verbs rather than asserted
    about one.

    Runs the real create-temp-tables to produce the state the state machine would carry,
    fails start-profile-query the way a bad query does, then feeds THAT state to this verb
    exactly as DropTempTablesOnFailure would — and checks both tables are dropped.

    What this does NOT prove is the ASL wiring itself (that every Catch reaches
    DropTempTablesOnFailure); that is Step Functions' behaviour, shipped in SPEC-108 and
    confirmed by the live smoke run. What it does prove is the handoff: the names
    create-temp-tables writes are the names this verb drops, on the failure path's event
    shape.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-create-temp-tables"))
    import dq_create_temp_tables as creator

    # ONE recorder for both verbs, deliberately. `creator.athena` and `v.athena` are the
    # SAME module object (both import cpcommon.athena), so patching run_ddl twice would
    # silently leave only the second patch in force — which is what a first attempt at
    # this test did, making it assert against an empty list while the drops really ran.
    statements = []
    monkeypatch.setattr(v.athena, "run_ddl", lambda **kw: statements.append(kw) or "qid")
    monkeypatch.setattr(
        creator.manifest_store,
        "load",
        lambda bucket, key: {
            "partitionKeys": [],
            "files": [{"key": "alice/sales/jan.csv", "size": 1,
                       "columns": [{"name": "id", "type": "string"}]}],
        },
    )

    state = creator.handler(
        {
            "requestId": REQUEST_ID,
            "actor": "alice",
            "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
            "location": "alice/sales",
            "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
            "manifestKey": f"alice/_data-quality-reports/{REQUEST_ID}/manifest.json",
            "format": "csv",
        },
        None,
    )
    assert len(statements) == 2  # both tables really were created
    assert all(kw["query"].startswith("CREATE ") for kw in statements)

    # start-profile-query blows up; the SFN Catch parks the error and routes here.
    state["error"] = {"Error": "TerminalError", "Cause": '{"errorMessage": "query_failed: boom"}'}

    out = v.handler(state, None)

    dropped = {kw["query"] for kw in statements if kw["query"].startswith("DROP ")}
    assert dropped == {
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_{HEX32}`",
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_raw_{HEX32}`",
    }
    assert out["cleanup"]["failed"] == []
    # $.error survives cleanup — RecordFailure reads it after this verb returns.
    assert out["error"]["Cause"] == '{"errorMessage": "query_failed: boom"}'
