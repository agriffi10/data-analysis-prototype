"""Unit tests for the data-quality drop-temp-tables Lambda (SPEC-111 FR-005).

AWS stubbed: ``athena.run_ddl`` is replaced on the verb module. The properties under test
are the ones that make this verb safe to invoke from EVERY path — idempotence, tolerance
of having nothing to do, and never raising.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_drop_temp_tables as v
import pytest
from cpcommon.errors import TerminalError
from dqcommon import messages

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


# ── Reached before anything was created (FR-005) ─────────────────────────────


# ── Never raising (FR-005) ───────────────────────────────────────────────────


def test_a_drop_failure_is_swallowed_so_it_cannot_mask_the_original_reason(monkeypatch, ran):
    """On the failure path, raising here would replace the reason the user is notified
    about with a cleanup error. On the success path it would tell the user their check
    failed while their report sits finished in S3. Neither is acceptable."""
    _fail_with(monkeypatch, TerminalError(messages.QUERY_FAILED, "glue exploded"))

    out = v.handler(_event(), None)  # must not raise

    assert out["cleanup"]["dropped"] == []
    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]


# ── The failure-path invocation shape ────────────────────────────────────────


# -- SPEC-132: cleanup narrates, and never claims the run failed ------------------------
