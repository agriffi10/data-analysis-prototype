"""Unit tests for the data-quality check-query Lambda (SPEC-111 FR-004).

The verb the Step Function's Wait -> CheckQuery -> Choice loop calls. What matters here is
the DIVERGENCE: a failed profile query ends the request, a failed ragged or duplicates
query degrades one figure and the request still succeeds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_check_query as v
import pytest
from cpcommon.errors import TerminalError
from dqcommon import messages


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


def test_settled_only_when_every_query_is_done(athena_says):
    out = v.handler(_event(), None)  # all default to SUCCEEDED
    assert out["queryStatus"] == "SUCCEEDED"
    assert out["profile"]["status"] == "SUCCEEDED"
    assert out["duplicates"]["status"] == "SUCCEEDED"


# ── The profile query is terminal (FR-004) ───────────────────────────────────


def test_a_failed_profile_query_is_a_terminal_query_failed(athena_says):
    athena_says["qid-p"] = {"state": "FAILED", "reason": "COLUMN_NOT_FOUND: line 1:8"}

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)
    assert exc.value.reason == messages.QUERY_FAILED


