"""Unit tests for the table-builder execute-ddl Lambda (SPEC-070).

Athena is stubbed via ``clients._athena`` (a fake client with a scripted state
sequence); the poll clock is driven by fake ``_now`` / ``_sleep`` seams so the timeout
path is deterministic with no real sleeping. Runnable under pytest OR directly:
``python3 test_execute_ddl.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import json  # noqa: E402
import athena_run  # noqa: E402
import execute_ddl as e  # noqa: E402
from cpcommon import clients, config  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402

BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


# ── Fakes ────────────────────────────────────────────────────────────────────

class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeAthena:
    """Scripts ``start_query_execution`` + a sequence of ``get_query_execution``
    states. ``start_error`` / ``poll_error`` inject exceptions instead."""

    def __init__(self, states, *, start_error=None, poll_error=None):
        self._states = list(states)
        self._start_error = start_error
        self._poll_error = poll_error
        self.start_calls = []

    def start_query_execution(self, **kwargs):
        if self._start_error is not None:
            raise self._start_error
        self.start_calls.append(kwargs)
        return {"QueryExecutionId": "q-123"}

    def get_query_execution(self, QueryExecutionId):  # noqa: N803 - boto3 kwarg name
        if self._poll_error is not None:
            raise self._poll_error
        # RUNNING forever once the scripted states are exhausted (timeout path).
        state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        entry = state if isinstance(state, dict) else {"State": state}
        return {"QueryExecution": {"Status": entry}}


def _install(athena, *, max_polls=5):
    """Point execute-ddl at the fake Athena + a fake, fast poll clock."""
    clients._athena = athena
    clock = {"t": 0.0}
    athena_run._now = lambda: clock["t"]
    athena_run._sleep = lambda s: clock.__setitem__("t", clock["t"] + s)
    athena_run.MAX_POLL_DURATION_SECONDS = max_polls * athena_run.POLL_INTERVAL_SECONDS
    config.ATHENA_WORKGROUP = "dat-prod-portal-wg"
    return athena


def _event(*, partitioned=False, kind="personal", bucket=BUCKET, database="alice"):
    keys = [{"name": "year", "type": "integer", "range": [2020, 2030]}] if partitioned else []
    return {
        "actor": "alice",
        "space": {"kind": kind, "bucket": bucket, "prefix": f"{database}/sales/", "database": database},
        "tableName": "sales_2026",
        "partitionKeys": keys,
        "location": f"s3://{bucket}/{database}/sales/",
        "requestId": "r1",
        "format": "parquet",
        "columns": [{"name": "amount", "type": "double"}],
        "ddl": "CREATE EXTERNAL TABLE IF NOT EXISTS alice.sales_2026 (amount double) ...",
    }


def _expect_reason(event, reason):
    try:
        e.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── Success ──────────────────────────────────────────────────────────────────

def test_flat_source_succeeds_with_one_query():
    athena = _install(_FakeAthena(["QUEUED", "RUNNING", "SUCCEEDED"]))
    out = e.handler(_event(), None)
    assert out["status"] == "created"
    # Exactly ONE query is run (no MSCK REPAIR / no second statement).
    assert len(athena.start_calls) == 1
    # The request threads through unchanged for the RecordSuccess projection.
    assert out["tableName"] == "sales_2026"
    assert out["actor"] == "alice"


def test_partitioned_source_succeeds_with_the_same_single_create():
    # A partitioned source uses projection — NO second MSCK REPAIR StartQueryExecution.
    athena = _install(_FakeAthena(["SUCCEEDED"]))
    out = e.handler(_event(partitioned=True), None)
    assert out["status"] == "created"
    assert len(athena.start_calls) == 1


def test_replay_of_existing_table_is_noop_success():
    # IF NOT EXISTS ⇒ a re-run against an already-created table SUCCEEDs trivially;
    # execute-ddl treats it as a no-op created (not a table_exists error — that guard
    # is the pre-create SPEC-068 check).
    athena = _install(_FakeAthena(["SUCCEEDED"]))
    out = e.handler(_event(), None)
    assert out["status"] == "created"
    assert len(athena.start_calls) == 1


# ── Results location routing ─────────────────────────────────────────────────

def test_personal_results_location():
    athena = _install(_FakeAthena(["SUCCEEDED"]))
    e.handler(_event(), None)
    assert athena.start_calls[0]["ResultConfiguration"]["OutputLocation"] == (
        f"s3://{BUCKET}/alice/athenaresults/alice/"
    )
    assert athena.start_calls[0]["QueryExecutionContext"]["Database"] == "alice"
    assert athena.start_calls[0]["WorkGroup"] == "dat-prod-portal-wg"


def test_shared_results_location_is_under_the_space():
    athena = _install(_FakeAthena(["SUCCEEDED"]))
    e.handler(_event(kind="shared", bucket=SHARED_BUCKET, database="salesteam"), None)
    assert athena.start_calls[0]["ResultConfiguration"]["OutputLocation"] == (
        f"s3://{SHARED_BUCKET}/salesteam/athenaresults/alice/"
    )


# ── Failures ─────────────────────────────────────────────────────────────────

def test_athena_failed_is_ddl_execution_failed_with_reason():
    _install(_FakeAthena([{"State": "FAILED", "StateChangeReason": "SYNTAX_ERROR: line 1"}]))
    try:
        e.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == "ddl_execution_failed"
        assert "SYNTAX_ERROR" in exc.detail
        return
    raise AssertionError("expected ddl_execution_failed")


def test_athena_cancelled_is_ddl_execution_failed():
    _install(_FakeAthena([{"State": "CANCELLED"}]))
    _expect_reason(_event(), "ddl_execution_failed")


def test_bad_statement_at_start_is_ddl_execution_failed():
    _install(_FakeAthena([], start_error=_FakeClientError("InvalidRequestException")))
    _expect_reason(_event(), "ddl_execution_failed")


def test_transient_start_error_is_raised_for_retry():
    _install(_FakeAthena([], start_error=_FakeClientError("ThrottlingException")))
    try:
        e.handler(_event(), None)
        raise AssertionError("expected TransientError")
    except TransientError:
        pass


def test_transient_poll_error_is_raised_for_retry():
    _install(_FakeAthena(["QUEUED"], poll_error=_FakeClientError("TooManyRequestsException")))
    try:
        e.handler(_event(), None)
        raise AssertionError("expected TransientError")
    except TransientError:
        pass


def test_timeout_is_ddl_timeout():
    # get_query_execution never leaves RUNNING → the wall-clock cap trips ddl_timeout.
    _install(_FakeAthena(["RUNNING"]), max_polls=3)
    _expect_reason(_event(), "ddl_timeout")


# ── SPEC-072 notifications ────────────────────────────────────────────────────

def test_notifies_actor_on_success_ready_message():
    _install(_FakeAthena(["SUCCEEDED"]))
    q = _arm_notifications()
    e.handler(_event(), None)
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:created"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body == {
        "action": "create",
        "username": "alice",
        "message": 'Table "sales_2026" is ready to query in "alice".',
    }


def test_notifies_actor_on_ddl_failure_without_leaking_athena_reason():
    _install(_FakeAthena([{"State": "FAILED", "StateChangeReason": "SYNTAX_ERROR: line 1"}]))
    q = _arm_notifications()
    try:
        e.handler(_event(), None)
    except TerminalError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageDeduplicationId"] == "r1:execute"
    body = json.loads(q.calls[0]["MessageBody"])
    # SPEC-106 FR-008: friendly text only — the raw Athena reason never reaches the inbox.
    assert body["message"] == (
        'Couldn\'t create table "sales_2026": creating the table failed. '
        "Please try again or contact the Administrator."
    )
    assert "SYNTAX_ERROR" not in body["message"]


def test_no_notification_on_transient_error():
    _install(_FakeAthena([], start_error=_FakeClientError("ThrottlingException")))
    q = _arm_notifications()
    try:
        e.handler(_event(), None)
    except TransientError:
        pass
    assert q.calls == []


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
