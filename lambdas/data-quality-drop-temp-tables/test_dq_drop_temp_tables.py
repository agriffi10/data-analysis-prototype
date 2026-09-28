"""Unit tests for the data-quality drop-temp-tables Lambda (SPEC-111 FR-005).

AWS stubbed: ``athena.run_ddl`` is replaced on the verb module, or the bounded Athena client is
when the real poll loop is under test. The properties under test are the ones that make this verb
safe to invoke from EVERY path — idempotence, tolerance of having nothing to do, never raising,
and never outlasting its own Lambda timeout.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_drop_temp_tables as v
import pytest
from cpcommon import athena, budget
from cpcommon.errors import TerminalError, TransientError
from dqcommon import messages
from test_index_store_dqcommon import _verb_timeout

BUCKET = "dq-user-bkt"
REQUEST_ID = "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
HEX32 = "7f3ac19d2b4e4c8a9f016d5e3a7b8c02"


def _event(**overrides):
    event = {
        "requestId": REQUEST_ID,
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
        "database": "alice_db",
        "tempTable": f"dq_tmp_{HEX32}",
        "tempRawTable": f"dq_tmp_raw_{HEX32}",
    }
    event.update(overrides)
    return event


BOUNDED = object()


@pytest.fixture(autouse=True)
def bounded_client(monkeypatch):
    """Stands in for the bounded client, and fails loudly if the verb reaches for the default one."""
    monkeypatch.setattr(v.clients, "athena_bounded", lambda: BOUNDED)
    monkeypatch.setattr(v.clients, "athena", lambda: pytest.fail("the unbounded Athena client"))


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

    # `alice_db`, not `alice`: the fixture's database differs from the one re-derivation
    # would produce, so this also pins that a state carrying the names is believed over the
    # fallback. With the two equal, the early return asserted nothing.
    assert [kw["query"] for kw in ran] == [
        f"DROP TABLE IF EXISTS `alice_db`.`dq_tmp_{HEX32}`",
        f"DROP TABLE IF EXISTS `alice_db`.`dq_tmp_raw_{HEX32}`",
    ]
    assert out["cleanup"]["dropped"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]
    assert out["cleanup"]["failed"] == []
    assert [kw["client"] for kw in ran] == [BOUNDED, BOUNDED]


# ── Never raising (FR-005) ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [TerminalError(messages.QUERY_FAILED, "glue exploded"), TransientError("Athena: transient ThrottlingException")],
    ids=["terminal", "transient"],
)
def test_a_drop_failure_is_swallowed_so_it_cannot_mask_the_original_reason(monkeypatch, ran, exc):
    """On the failure path, raising here would replace the reason the user is notified
    about with a cleanup error. On the success path it would tell the user their check
    failed while their report sits finished in S3. Neither is acceptable — and a throttle is
    the likeliest failure of all, which run_ddl raises as transient rather than terminal."""
    _fail_with(monkeypatch, exc)

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


def test_a_state_with_a_manifest_but_no_request_id_is_a_no_op_rather_than_a_raise(ran):
    """The half of the gate that holds this verb's never-raise contract.

    Without it, `event["requestId"]` on the derive path raises KeyError straight through
    `@notifies_on_failure` — from the one verb whose whole safety argument is that it can be
    invoked from anywhere and will not raise. Unreachable through the machine today, which is
    exactly why nothing would notice the line being deleted.
    """
    event = _mid_create()
    event.pop("requestId")

    out = v.handler(event, None)  # must not raise

    assert ran == []
    assert out["cleanup"]["skipped"] is True


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




# ── never outlasting the Lambda timeout ──────────────────────────────────────


def _worst_case_seconds():
    """The longest cleanup can take: the shared deadline, one call cap and one poll interval.

    The budget refuses a call that would start past the deadline, so the last call starts just
    inside it and is waited on for at most the cap; ``run_ddl`` then sleeps once more before its
    next call is refused, and every call after that, the second drop's start included, is refused
    before it begins.
    """
    return v.DROP_DEADLINE_SECONDS + budget.CALL_CAP_SECONDS + athena.DEFAULT_POLL_INTERVAL_SECONDS


def test_cleanup_cannot_outlast_the_verbs_timeout():
    """A slow drop is swallowed only if polling it ends before the verb's Lambda timeout does.

    On the success path this verb runs after the user was told the check completed, and a timeout
    lands in the Catch that records the run failed. Half the timeout is the line, and the other
    half is margin for what the worst case does not count: the telemetry flush the handler runs on
    its way out.
    """
    worst = _worst_case_seconds()
    timeout = _verb_timeout("drop-temp-tables")

    assert worst <= timeout / 2, (
        f"cleanup can take {worst}s inside drop-temp-tables, whose timeout is {timeout}s"
    )


class _Clock:
    """A clock that moves only when a call or a sleep moves it."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class _StalledAthena:
    """An Athena client whose statement never settles, and each of whose polls holds its caller
    for a whole cap.

    The start answers at once, which lines the polls up so that the last one starts exactly at the
    deadline: the schedule reaches the worst case rather than stopping short of it.
    """

    def __init__(self, clock):
        self.clock = clock
        self.started = []

    def start_query_execution(self, **params):
        self.started.append(params["QueryString"])
        return {"QueryExecutionId": f"qid-{len(self.started)}"}

    def get_query_execution(self, QueryExecutionId):
        self.clock.t += budget.CALL_CAP_SECONDS
        return {"QueryExecution": {"Status": {"State": "RUNNING"}}}


def test_drops_that_never_settle_give_up_inside_the_worst_case(monkeypatch):
    """Every call of both drops runs under one budget, so a first drop that never settles leaves
    the second nothing to start with.

    Driven through the real poll loop and the real budget on a clock that moves only when a call
    or a sleep does, so what it measures is the verb's wiring and not the test's speed. A budget
    per drop, or a poll made outside the budget, carries the run past the worst case the timeout
    test holds; a start made outside it starts the second drop, which a spent budget must not.
    The second table, never started, is recorded as leaked.
    """
    clock = _Clock()
    stalled = _StalledAthena(clock)
    run_ddl = v.athena.run_ddl
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=clock.now))
    monkeypatch.setattr(
        v.athena, "run_ddl", lambda **kw: run_ddl(**kw, now=clock.now, sleep=clock.sleep)
    )
    monkeypatch.setattr(v.clients, "athena_bounded", lambda: stalled)

    out = v.handler(_event(), None)

    assert clock.t <= _worst_case_seconds()
    assert stalled.started == [f"DROP TABLE IF EXISTS `alice_db`.`dq_tmp_{HEX32}`"]
    assert out["cleanup"]["failed"] == [f"dq_tmp_{HEX32}", f"dq_tmp_raw_{HEX32}"]
