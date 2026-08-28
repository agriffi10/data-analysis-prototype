"""Unit tests for the table-builder execute-ddl Lambda (SPEC-070).

Athena is stubbed via ``clients._athena`` (a fake client with a scripted state
sequence); the poll clock is driven by fake ``_now`` / ``_sleep`` seams so the timeout
path is deterministic with no real sleeping. Runnable under pytest OR directly:
``python3 test_execute_ddl.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import json

import execute_ddl as e
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError

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

    def get_query_execution(self, QueryExecutionId):  # boto3 kwarg name
        if self._poll_error is not None:
            raise self._poll_error
        # RUNNING forever once the scripted states are exhausted (timeout path).
        state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
        entry = state if isinstance(state, dict) else {"State": state}
        return {"QueryExecution": {"Status": entry}}


@pytest.fixture(autouse=True)
def _restore_the_runner_seams():
    """Puts the runner's clock seams and poll cap back after every test.

    `_install` mutates them on the instance the verb holds. conftest's shared-layer snapshot
    restores module namespaces and cannot reach an instance attribute, so without this the
    fake clock outlives its test — latent while this is the only file importing `execute_ddl`,
    which is exactly the condition that hid the same leak in table-share's suite.
    """
    saved = (e.athena_run._now, e.athena_run._sleep, e.athena_run.MAX_POLL_DURATION_SECONDS)
    yield
    e.athena_run._now, e.athena_run._sleep, e.athena_run.MAX_POLL_DURATION_SECONDS = saved


def _install(athena, *, max_polls=5):
    """Point execute-ddl at the fake Athena + a fake, fast poll clock."""
    clients._athena = athena
    clock = {"t": 0.0}
    # The seams moved from a module (`athena_run.py`, deleted) onto the runner instance the
    # verb holds (SPEC-156 FR-005). Still read at call time, so patching still takes effect.
    e.athena_run._now = lambda: clock["t"]
    e.athena_run._sleep = lambda s: clock.__setitem__("t", clock["t"] + s)
    e.athena_run.MAX_POLL_DURATION_SECONDS = max_polls * e.athena_run.POLL_INTERVAL_SECONDS
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


# ── Results location routing ─────────────────────────────────────────────────


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


# ── SPEC-072 notifications ────────────────────────────────────────────────────


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


# -- SPEC-135 FR-004: the in-Lambda poll narrates transitions, not iterations ------------
