"""Unit tests for table-share's bound DDL runner (SPEC-092) — the start+poll loop.

Fake Athena client + fake clock (the runner's _now/_sleep seams): asserts the
submit parameters, success/failed/cancelled/timeout outcome mapping, and the
transient-vs-terminal error classification.

The runner was `tscommon.athena`, a per-plane wrapper byte-identical to the table-builder's
bar two reason codes; SPEC-156 FR-005 replaced both with `cpcommon.athena.bound_runner`. What
is under test is unchanged — this plane's reason codes and this plane's poll bounds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from table_share_create_table import athena_mod


class _FakeAthena:
    """States are consumed one per poll; the last repeats if polling continues."""

    def __init__(self, states=("SUCCEEDED",), reason=None, start_error=None, poll_error=None):
        self.states = list(states)
        self.reason = reason
        self.start_error = start_error
        self.poll_error = poll_error
        self.start_calls = []
        self.poll_count = 0

    def start_query_execution(self, **kwargs):
        self.start_calls.append(kwargs)
        if self.start_error:
            raise self.start_error
        return {"QueryExecutionId": "qid-1"}

    def get_query_execution(self, **kwargs):
        self.poll_count += 1
        if self.poll_error:
            raise self.poll_error
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        status = {"State": state}
        if self.reason:
            status["StateChangeReason"] = self.reason
        return {"QueryExecution": {"Status": status}}


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


@pytest.fixture(autouse=True)
def _restore_the_runner_seams():
    """Puts the runner's clock seams back after every test.

    `_setup` mutates them on the BoundRunner instance the verb module holds, and conftest's
    shared-layer snapshot restores module namespaces — it cannot reach an instance attribute.
    Without this a later-sorting file inherits a spent `_FakeClock` whose `now()` returns a
    frozen scripted value, so a real poll-loop test would pass or hang for a reason unrelated
    to what it asserts. The sibling suites in this directory carry the same fixture.
    """
    saved = (athena_mod._now, athena_mod._sleep)
    yield
    athena_mod._now, athena_mod._sleep = saved


def _setup(fake):
    clients._athena = fake
    clock = _FakeClock()
    athena_mod._now = clock.now
    athena_mod._sleep = clock.sleep
    return clock


def _run():
    return athena_mod.run_ddl(
        query="CREATE EXTERNAL TABLE …",
        database="bob",
        workgroup="test-workgroup",
        output_location="s3://user-bkt/bob/athenaresults/alice/",
    )


def _expect(reason, exc_type=TerminalError):
    try:
        _run()
    except exc_type as exc:
        if exc_type is TerminalError:
            assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def test_succeeded_returns_the_execution_id_with_the_right_submit_params():
    fake = _FakeAthena(states=("RUNNING", "SUCCEEDED"))
    _setup(fake)
    assert _run() == "qid-1"
    call = fake.start_calls[0]
    assert call["QueryExecutionContext"] == {"Database": "bob"}
    assert call["WorkGroup"] == "test-workgroup"
    assert call["ResultConfiguration"] == {"OutputLocation": "s3://user-bkt/bob/athenaresults/alice/"}


def test_failed_state_is_terminal_with_athenas_reason():
    _setup(_FakeAthena(states=("RUNNING", "FAILED"), reason="SYNTAX_ERROR: line 1"))
    try:
        _run()
    except TerminalError as exc:
        assert exc.reason == "create_failed"
        assert "SYNTAX_ERROR" in exc.detail
        return
    raise AssertionError("expected TerminalError")


def test_poll_cap_exceeded_is_create_timeout():
    clock = _setup(_FakeAthena(states=("RUNNING",)))
    _expect("create_timeout")
    assert clock.t >= athena_mod.MAX_POLL_DURATION_SECONDS
