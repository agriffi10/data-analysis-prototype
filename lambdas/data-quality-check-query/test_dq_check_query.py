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


# -- SPEC-132 FR-005: transitions, not polls ---------------------------------------------


def test_twenty_polls_with_no_change_narrate_nothing(athena_says, captured_events):
    """THE guard for this verb. It is invoked from a 30-second Wait loop for as long as the
    profiling query runs — minutes to tens of minutes by design — so one event per poll is
    fifty events per run saying the query is still running. The span pair already records
    that a poll happened; the narrative must add information or say nothing.
    """
    athena_says.update({q: {"state": "RUNNING", "reason": None} for q in ("qid-p", "qid-r", "qid-d")})
    event = _event(profile="RUNNING", ragged="RUNNING", duplicates="RUNNING")

    for _ in range(20):
        event = v.handler(event, None)

    assert captured_events.levels() == [], (
        f"{len(captured_events.levels())} narrative events across 20 unchanged polls"
    )


def test_a_query_reaching_a_terminal_state_emits_exactly_one_event(athena_says, captured_events):
    athena_says.update({q: {"state": "RUNNING", "reason": None} for q in ("qid-p", "qid-r", "qid-d")})
    event = _event(profile="RUNNING", ragged="RUNNING", duplicates="RUNNING")

    event = v.handler(event, None)
    athena_says["qid-p"] = {"state": "SUCCEEDED", "reason": None}
    event = v.handler(event, None)
    event = v.handler(event, None)  # the settled block is never described again

    settled = [e for e in captured_events.messages("query settled") if e["fields"]["query"] == "profile"]
    assert len(settled) == 1
    assert settled[0]["fields"]["query_id"] == "qid-p"
    assert settled[0]["fields"]["status"] == "SUCCEEDED"


def test_a_queued_to_running_transition_is_not_worth_an_event(athena_says, captured_events):
    """A change, but not information: the query is still running either way."""
    athena_says.update({q: {"state": "RUNNING", "reason": None} for q in ("qid-p", "qid-r", "qid-d")})

    v.handler(_event(), None)

    assert captured_events.levels() == []


def test_a_degraded_query_is_a_warning_not_an_error(athena_says, captured_events):
    """The request still SUCCEEDS: a ragged-row count is not worth losing the null ratios
    and row counts over, so the level must not say the run failed.
    """
    athena_says.update(
        {
            "qid-p": {"state": "RUNNING", "reason": None},
            "qid-r": {"state": "FAILED", "reason": "SYNTAX_ERROR"},
            "qid-d": {"state": "RUNNING", "reason": None},
        }
    )

    v.handler(_event(), None)

    degraded = captured_events.messages("query degraded")
    assert len(degraded) == 1
    assert degraded[0]["level"] == "WARNING"
    assert degraded[0]["fields"]["query"] == "ragged"
    assert degraded[0]["fields"]["status"] == "not_computed"
    assert degraded[0]["fields"]["reason"] == "SYNTAX_ERROR"


def test_a_quota_kill_is_reported_as_a_timeout_not_a_generic_failure(athena_says, captured_events):
    athena_says["qid-p"] = {"state": "FAILED", "reason": "Query exceeded the limit of 30 minutes"}

    with pytest.raises(TerminalError):
        v.handler(_event(), None)

    timed_out = captured_events.messages("query timed out")
    assert timed_out and timed_out[0]["level"] == "ERROR"
    assert timed_out[0]["fields"]["status"] == "query_timeout"


def test_a_failed_profile_is_an_error_carrying_athenas_own_reason(athena_says, captured_events):
    """StateChangeReason is service text and is explicitly permitted — it is what an operator
    needs, and it is never a result row.
    """
    athena_says["qid-p"] = {"state": "FAILED", "reason": "COLUMN_NOT_FOUND"}

    with pytest.raises(TerminalError):
        v.handler(_event(), None)

    failed = captured_events.messages("query failed")
    assert failed and failed[0]["fields"]["reason"] == "COLUMN_NOT_FOUND"


def test_the_describe_phase_is_one_span_per_poll_not_one_per_query(athena_says, captured_events):
    """Three spans on a poll that repeats fifty times is a hundred and fifty extra events for
    a duration an operator reads as a single number anyway.
    """
    athena_says.update({q: {"state": "RUNNING", "reason": None} for q in ("qid-p", "qid-r", "qid-d")})

    v.handler(_event(), None)

    assert len(captured_events.spans("describe-queries")) == 1
