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


# ── Never raising (FR-005) ───────────────────────────────────────────────────


def test_a_drop_failure_is_swallowed_so_it_cannot_mask_the_original_reason(monkeypatch, ran):
    """On the failure path, raising here would replace the reason the user is notified
    about with a cleanup error. On the success path it would tell the user their check
    failed while their report sits finished in S3. Neither is acceptable."""
    _fail_with(monkeypatch, TerminalError(messages.QUERY_FAILED, "glue exploded"))

    out = v.handler(_event(), None)  # must not raise

    assert out["cleanup"]["dropped"] == []
    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]


# ── reached from a create that never returned ────────────────────────────────


def _mid_create(**overrides):
    """The state a Catch on CreateTempTables hands this verb.

    A Catch merges its error under `$.error` and keeps the state that went INTO the failed
    state, so NOTHING the create verb attaches to its own output is here — no database, no
    table names. What is here is what inspect-source returned.
    """
    event = _event(format="csv", manifestKey=f"alice/_data-quality-reports/{REQUEST_ID}/manifest.json")
    for key in ("database", "tempTable", "tempRawTable"):
        event.pop(key)
    event.update(overrides)
    return event


def test_it_drops_the_tables_a_create_built_before_it_died(ran):
    """The leak this verb exists to prevent, on the one path that used to reach it silently.

    A CSV create runs two statements. If the second fails terminally — or the invocation is
    killed between them — the typed table exists and its name was never returned, so reading the
    names off the state finds none and cleanup no-ops over a real `dq_tmp_*` table in the user's
    own database.
    """
    out = v.handler(_mid_create(), None)

    assert [kw["query"] for kw in ran] == [
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_{HEX32}`",
        f"DROP TABLE IF EXISTS `alice`.`dq_tmp_raw_{HEX32}`",
    ]
    assert out["cleanup"]["skipped"] is False


def test_a_non_csv_run_has_no_raw_table_to_drop(ran):
    """The raw-line table is CSV-only, so deriving one for Parquet would drop a name that
    never existed — harmless but a lie in the cleanup record an operator reads."""
    v.handler(_mid_create(format="parquet"), None)

    assert [kw["query"] for kw in ran] == [f"DROP TABLE IF EXISTS `alice`.`dq_tmp_{HEX32}`"]


def test_a_shared_space_run_derives_its_own_database(ran):
    """The database is re-derived from the space, not defaulted to the actor."""
    v.handler(
        _mid_create(space={"kind": "shared", "bucket": BUCKET, "prefix": "team-data/"}),
        None,
    )

    assert [kw["query"] for kw in ran] == [
        f"DROP TABLE IF EXISTS `team-data`.`dq_tmp_{HEX32}`",
        f"DROP TABLE IF EXISTS `team-data`.`dq_tmp_raw_{HEX32}`",
    ]


def test_a_failure_before_the_create_verb_stays_a_clean_no_op(ran):
    """The overwhelmingly common failure — a validator or inspection refusal — created nothing.

    `manifestKey` is the discriminator: inspect-source is its only writer and the create verb
    requires it, so its absence means no table could exist. Without this the fix would put two
    Athena statements on every failed request.
    """
    event = _mid_create()
    event.pop("manifestKey")

    out = v.handler(event, None)

    assert ran == []
    assert out["cleanup"] == {"dropped": [], "failed": [], "skipped": True}


