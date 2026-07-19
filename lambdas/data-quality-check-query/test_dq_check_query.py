"""Unit tests for the data-quality check-query Lambda (SPEC-111 FR-004).

The verb the Step Function's Wait -> CheckQuery -> Choice loop calls. What matters here is
the DIVERGENCE: a failed profile query ends the request, a failed ragged or duplicates
query degrades one figure and the request still succeeds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import messages  # noqa: E402

import dq_check_query as v  # noqa: E402


def _block(qid, status="QUEUED"):
    return {"queryExecutionId": qid, "status": status, "resultLocation": f"s3://b/{qid}/", "reason": None}


def _event(profile="QUEUED", ragged="QUEUED", duplicates="QUEUED", no_ragged=False):
    return {
        "requestId": "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02",
        "actor": "alice",
        "profile": _block("qid-p", profile),
        "ragged": None if no_ragged else _block("qid-r", ragged),
        "duplicates": _block("qid-d", duplicates),
    }


@pytest.fixture
def athena_says(monkeypatch):
    """Install a per-execution-id state map; returns the dict so a test can mutate it."""
    states = {}

    def _describe(qid, *, fail_reason):
        return states.get(qid, {"state": "SUCCEEDED", "reason": None})

    monkeypatch.setattr(v.athena, "describe_query", _describe)
    return states


# ── The loop ─────────────────────────────────────────────────────────────────


def test_still_running_while_any_query_is_pending(athena_says):
    athena_says["qid-p"] = {"state": "RUNNING", "reason": None}
    athena_says["qid-r"] = {"state": "SUCCEEDED", "reason": None}
    athena_says["qid-d"] = {"state": "SUCCEEDED", "reason": None}

    out = v.handler(_event(), None)
    assert out["queryStatus"] == "RUNNING"


def test_a_queued_query_also_keeps_the_loop_going(athena_says):
    athena_says["qid-p"] = {"state": "SUCCEEDED", "reason": None}
    athena_says["qid-r"] = {"state": "QUEUED", "reason": None}
    athena_says["qid-d"] = {"state": "SUCCEEDED", "reason": None}

    out = v.handler(_event(), None)
    assert out["queryStatus"] == "RUNNING"


def test_settled_only_when_every_query_is_done(athena_says):
    out = v.handler(_event(), None)  # all default to SUCCEEDED
    assert out["queryStatus"] == "SUCCEEDED"
    assert out["profile"]["status"] == "SUCCEEDED"
    assert out["duplicates"]["status"] == "SUCCEEDED"


def test_a_null_ragged_block_does_not_break_the_aggregate(athena_says):
    """The JSON/Parquet case. A Choice rule reading $.ragged.status here would raise
    States.Runtime — uncatchable, so the user would get no notification at all. The
    aggregation happens in Python precisely so a null is just a null."""
    out = v.handler(_event(no_ragged=True), None)
    assert out["ragged"] is None
    assert out["queryStatus"] == "SUCCEEDED"


def test_a_settled_query_is_not_re_described(monkeypatch):
    """One API call per poll per PENDING query — a SUCCEEDED block is already final."""
    calls = []

    def _describe(qid, *, fail_reason):
        calls.append(qid)
        return {"state": "SUCCEEDED", "reason": None}

    monkeypatch.setattr(v.athena, "describe_query", _describe)
    v.handler(_event(profile="SUCCEEDED", ragged="QUEUED", duplicates="SUCCEEDED"), None)
    assert calls == ["qid-r"]


# ── The profile query is terminal (FR-004) ───────────────────────────────────


def test_a_failed_profile_query_is_a_terminal_query_failed(athena_says):
    athena_says["qid-p"] = {"state": "FAILED", "reason": "COLUMN_NOT_FOUND: line 1:8"}

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.QUERY_FAILED


def test_a_cancelled_profile_query_is_also_terminal(athena_says):
    athena_says["qid-p"] = {"state": "CANCELLED", "reason": "cancelled by user"}

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.QUERY_FAILED


def test_a_timed_out_profile_query_is_a_terminal_query_timeout(athena_says):
    """Distinct from query_failed on purpose: the user's action differs. A timeout means
    "use a smaller folder"; the quota is account-level, so retrying is pointless."""
    athena_says["qid-p"] = {"state": "FAILED", "reason": "Query timeout: the query exceeded the limit"}

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.QUERY_TIMEOUT


def test_the_user_facing_message_carries_no_raw_athena_text(athena_says):
    """SPEC-106 FR-008: the StateChangeReason stays in CloudWatch and the SFN history."""
    raw = "SYNTAX_ERROR: line 1:8: SerDe org.apache.hadoop.hive.serde2.OpenCSVSerde blew up"
    athena_says["qid-p"] = {"state": "FAILED", "reason": raw}

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    user_message = messages.failure_message(exc.value.reason, "alice/sales")
    assert "SerDe" not in user_message
    assert "SYNTAX_ERROR" not in user_message
    assert "Administrator" in user_message


# ── ragged / duplicates degrade instead (FR-004) ─────────────────────────────


def test_a_failed_ragged_query_degrades_and_the_run_continues(athena_says):
    """A ragged-row count is not worth losing the null ratios, the type consistency and
    the row counts over."""
    athena_says["qid-r"] = {"state": "FAILED", "reason": "line too long (200MB limit)"}

    out = v.handler(_event(), None)  # must NOT raise

    assert out["ragged"]["status"] == "not_computed"
    assert "200MB" in out["ragged"]["reason"]
    assert out["queryStatus"] == "SUCCEEDED"
    assert out["profile"]["status"] == "SUCCEEDED"


def test_a_failed_duplicates_query_degrades_and_the_run_continues(athena_says):
    athena_says["qid-d"] = {"state": "FAILED", "reason": "Query exhausted resources at this scale factor"}

    out = v.handler(_event(), None)  # must NOT raise

    assert out["duplicates"]["status"] == "not_computed"
    assert "exhausted resources" in out["duplicates"]["reason"]
    assert out["queryStatus"] == "SUCCEEDED"


def test_both_degradable_queries_can_fail_at_once(athena_says):
    athena_says["qid-r"] = {"state": "FAILED", "reason": "boom"}
    athena_says["qid-d"] = {"state": "CANCELLED", "reason": "bang"}

    out = v.handler(_event(), None)

    assert out["ragged"]["status"] == "not_computed"
    assert out["duplicates"]["status"] == "not_computed"
    # Everything else still lands — that is the entire point of the three-query split.
    assert out["profile"]["status"] == "SUCCEEDED"
    assert out["queryStatus"] == "SUCCEEDED"


def test_the_handling_of_profile_and_degradable_failures_genuinely_differs(athena_says):
    """The assertion the spec asks for: same Athena outcome, opposite consequences."""
    same_failure = {"state": "FAILED", "reason": "identical failure"}

    athena_says.clear()
    athena_says["qid-d"] = dict(same_failure)
    degraded = v.handler(_event(), None)
    assert degraded["duplicates"]["status"] == "not_computed"

    athena_says.clear()
    athena_says["qid-p"] = dict(same_failure)
    with pytest.raises(TerminalError):
        v.handler(_event(), None)


def test_a_degraded_figure_is_not_re_decided_on_a_later_poll(athena_says):
    """not_computed is final: re-describing could flip it back and produce a report whose
    figures disagree with the reason recorded beside them."""
    event = _event()
    event["duplicates"]["status"] = "not_computed"
    event["duplicates"]["reason"] = "exhausted resources"
    athena_says["qid-d"] = {"state": "SUCCEEDED", "reason": None}

    out = v.handler(event, None)
    assert out["duplicates"]["status"] == "not_computed"


# ── It does not wait ─────────────────────────────────────────────────────────


def test_the_verb_never_sleeps(monkeypatch, athena_says):
    """The poll is the state machine's job — a sleep here would reintroduce the 900 s
    ceiling this whole design exists to escape."""
    import time

    monkeypatch.setattr(time, "sleep", _boom)
    v.handler(_event(), None)


def _boom(*_a, **_k):
    raise AssertionError("check-query must not sleep")


def test_the_request_object_is_threaded_not_replaced(athena_says):
    out = v.handler(_event(), None)
    assert out["requestId"] == "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
    assert out["actor"] == "alice"


def test_a_non_dict_event_does_not_crash(athena_says):
    out = v.handler(None, None)
    assert out["queryStatus"] == "SUCCEEDED"
