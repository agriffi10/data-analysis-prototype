"""Unit tests for the table-builder execute-ddl Lambda.

Athena is stubbed via ``clients._athena`` (a fake client with a scripted state sequence); the
poll clock is driven by fake ``_now`` / ``_sleep`` seams so the timeout path is deterministic
with no real sleeping. Glue is stubbed via ``clients._glue``, because the verb reads the table
back after the statement and refuses unless the catalog agrees with what this run declared.

**The post-condition is a GATE, so it gets a corpus rather than a sample.** Each of its three
checks — the LOCATION, the partition keys, the projection each key was declared with — has a
catalog fixture that reddens only that check, and the corpus carries the cases that must stay
SILENT too: a trailing-slash difference, a property the run never declared, and a replay over
the table this run itself created. Half a gate's regressions are false positives, and a gate
run only against the thing it guards proves the artifact passes rather than that the gate works.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import json

import execute_ddl as e
import pytest
from botocore.exceptions import ClientError
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

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


def _glue_error(code):
    """A botocore ClientError carrying one error code, as the verb classifies it.

    Args:
      code: The AWS error code to raise under.

    Returns:
      The ClientError.

    Raises:
      None.
    """
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetTable")


# ── Fakes ────────────────────────────────────────────────────────────────────


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


class _FakeGlue:
    """The catalog the statement's table is read back from.

    ``table`` is what ``GetTable`` reports; ``error`` is raised instead when set. The read-back
    is the only Glue call this verb makes, so one scripted answer is the whole surface.

    Attributes:
      table: The table dict to report.
      error: An exception to raise instead of reporting it.
      calls: One entry per ``GetTable``.
    """

    def __init__(self, table=None, error=None):
        """Serves one table, or one fault.

        Args:
          table: The table dict to report.
          error: An exception to raise instead.

        Returns:
          None.

        Raises:
          None.
        """
        self.table = table
        self.error = error
        self.calls = []

    def get_table(self, **kwargs):
        """Reports the table, or raises the scripted fault.

        Args:
          **kwargs: The ``GetTable`` arguments.

        Returns:
          The table.

        Raises:
          Exception: The scripted fault, when one is set.
        """
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"Table": self.table}


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


def _catalog(*, partitioned=False, location=None, partition_keys=None, parameters=None):
    """The table Athena lands for ``_event``, or a variant of it a losing run would meet.

    Defaults to exactly what this run's own statement creates, so a test names only the fact it
    is changing and every other fact still agrees.

    Args:
      partitioned: Whether the default carries the event's declared ``year`` key.
      location: Override the storage descriptor's LOCATION.
      partition_keys: Override the catalog's partition keys.
      parameters: Override the table parameters.

    Returns:
      The Glue table dict.

    Raises:
      None.
    """
    default_keys = [{"Name": "year", "Type": "int"}] if partitioned else []
    default_parameters = {"portal.managed": "true", "EXTERNAL": "TRUE"}
    if partitioned:
        default_parameters |= {
            "projection.enabled": "true",
            "projection.year.type": "integer",
            "projection.year.range": "2020,2030",
        }
    return {
        "Name": "sales_2026",
        "TableType": "EXTERNAL_TABLE",
        "PartitionKeys": default_keys if partition_keys is None else partition_keys,
        "Parameters": default_parameters if parameters is None else parameters,
        "StorageDescriptor": {
            "Location": f"s3://{BUCKET}/alice/sales/" if location is None else location,
            "Columns": [{"Name": "amount", "Type": "double"}],
        },
    }


def _install(athena, *, max_polls=5, glue=None):
    """Point execute-ddl at the fake Athena, a fake fast poll clock and a fake catalog."""
    clients._athena = athena
    clients._glue = _FakeGlue() if glue is None else glue
    clock = {"t": 0.0}
    # The seams moved from a module (`athena_run.py`, deleted) onto the runner instance the
    # verb holds (SPEC-156 FR-005). Still read at call time, so patching still takes effect.
    e.athena_run._now = lambda: clock["t"]
    e.athena_run._sleep = lambda s: clock.__setitem__("t", clock["t"] + s)
    e.athena_run.MAX_POLL_DURATION_SECONDS = max_polls * e.athena_run.POLL_INTERVAL_SECONDS
    config.ATHENA_WORKGROUP = "dat-prod-portal-wg"
    config.USER_SPACE_BUCKET = BUCKET
    config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    return athena


def _succeeding(*, partitioned=False, catalog=None):
    """Installs a statement that succeeds and a catalog that agrees with this run.

    Args:
      partitioned: Whether the default catalog carries the event's declared key.
      catalog: An explicit catalog table, for a run that did NOT build what stands.

    Returns:
      The ``(athena, glue)`` fakes.

    Raises:
      None.
    """
    table = _catalog(partitioned=partitioned) if catalog is None else catalog
    glue = _FakeGlue(table)
    athena = _install(_FakeAthena(["QUEUED", "RUNNING", "SUCCEEDED"]), glue=glue)
    return athena, glue


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


# ── Success ──────────────────────────────────────────────────────────────────

def test_flat_source_succeeds_with_one_query():
    athena, glue = _succeeding()
    out = e.handler(_event(), None)
    assert out["status"] == "created"
    # Exactly ONE query is run (no MSCK REPAIR / no second statement).
    assert len(athena.start_calls) == 1
    # The table is read back once, and it is the one the statement named.
    assert glue.calls == [{"DatabaseName": "alice", "Name": "sales_2026"}]
    # The request threads through unchanged for the RecordSuccess projection.
    assert out["tableName"] == "sales_2026"
    assert out["actor"] == "alice"


def test_a_partitioned_create_is_confirmed_against_its_own_projection():
    """The declared key's projection properties are re-rendered and matched, not assumed.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding(partitioned=True)
    out = e.handler(_event(partitioned=True), None)
    assert out["status"] == "created"


def test_a_replay_after_the_create_committed_still_succeeds():
    """The property ``IF NOT EXISTS`` exists for: a Step Functions retry must not fail.

    The second invocation runs the same statement against a catalog that already holds the
    table — the state a retry after a committed create meets — and the post-condition matches
    because the table standing is this run's own.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    athena, _ = _succeeding()
    first = e.handler(_event(), None)
    second = e.handler(_event(), None)
    assert (first["status"], second["status"]) == ("created", "created")
    assert len(athena.start_calls) == 2, "the replay re-runs the statement, which is the no-op"


@pytest.mark.parametrize(
    "name,catalog",
    [
        (
            "a trailing slash is not a different folder",
            _catalog(location=f"s3://{BUCKET}/alice/sales"),
        ),
        (
            "a projection property this run never declared is ignored",
            _catalog(
                partitioned=True,
                parameters={
                    "projection.enabled": "true",
                    "projection.year.type": "integer",
                    "projection.year.range": "2020,2030",
                    "projection.year.digits": "4",
                },
            ),
        ),
        (
            "a column set this run did not infer is not the gate's business",
            _catalog(
                location=f"s3://{BUCKET}/alice/sales/",
                parameters={"portal.managed": "true"},
            )
            | {"StorageDescriptor": {"Location": f"s3://{BUCKET}/alice/sales/", "Columns": []}},
        ),
    ],
)
def test_the_gate_stays_silent_on(name, catalog):
    """Cases the post-condition must NOT refuse, because a false refusal is worse than the bug.

    Args:
      name: What the case is, for the failure message.
      catalog: The table the catalog reports.

    Returns:
      None.

    Raises:
      None.
    """
    partitioned = bool(catalog["PartitionKeys"])
    _succeeding(catalog=catalog)
    out = e.handler(_event(partitioned=partitioned), None)
    assert out["status"] == "created", name


# ── The lost race ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,partitioned,catalog",
    [
        (
            "another folder",
            False,
            _catalog(location=f"s3://{BUCKET}/alice/invoices/"),
        ),
        (
            "another bucket",
            False,
            _catalog(location=f"s3://{SHARED_BUCKET}/alice/sales/"),
        ),
        (
            "a LOCATION the portal cannot resolve",
            False,
            _catalog(location="s3://somebody-elses-bucket/alice/sales/"),
        ),
        (
            "partition keys this run did not declare",
            False,
            _catalog(
                partition_keys=[{"Name": "year", "Type": "int"}],
                parameters={
                    "projection.enabled": "true",
                    "projection.year.type": "integer",
                    "projection.year.range": "2020,2030",
                },
            ),
        ),
        (
            "no partition keys where this run declared one",
            True,
            _catalog(partition_keys=[], parameters={"portal.managed": "true"}),
        ),
        (
            "a partition key of another name",
            True,
            _catalog(
                partition_keys=[{"Name": "month", "Type": "int"}],
                parameters={
                    "projection.enabled": "true",
                    "projection.month.type": "integer",
                    "projection.month.range": "1,12",
                },
            ),
        ),
        (
            "the same key projected over another range",
            True,
            _catalog(
                partitioned=True,
                parameters={
                    "projection.enabled": "true",
                    "projection.year.type": "integer",
                    "projection.year.range": "2000,2100",
                },
            ),
        ),
        (
            "the same key with its projection missing",
            True,
            _catalog(partitioned=True, parameters={"portal.managed": "true"}),
        ),
    ],
)
def test_a_statement_that_was_a_no_op_over(name, partitioned, catalog):
    """Every way the standing table can disagree with this run's declaration refuses.

    The corpus is per-check: the first three redden the LOCATION comparison, the next three the
    partition keys, and the last two the projection. Each fixture changes ONE fact, so a check
    that stopped firing leaves its own rows failing and nothing else.

    Args:
      name: What the standing table is, for the failure message.
      partitioned: Whether this run declares a partition key.
      catalog: The table the catalog reports.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding(catalog=catalog)
    with pytest.raises(TerminalError) as caught:
        e.handler(_event(partitioned=partitioned), None)
    assert caught.value.reason == "table_exists", name
    assert "another request" in caught.value.detail


def test_partition_keys_declared_in_another_order_are_another_table():
    """The key comparison is ORDERED, and a count or a set would not notice.

    Keys are declared in granularity order and the folder is laid out `year=…/month=…`, so a table
    partitioned `month, year` over the same folder with the same projection is a different table.
    Every other fact agrees — same LOCATION, same key names, same projection properties — so this
    is the row that fails when the comparison stops being a list.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    projection = {
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": "2020,2030",
        "projection.month.type": "integer",
        "projection.month.range": "1,12",
    }
    _succeeding(
        catalog=_catalog(
            partition_keys=[{"Name": "month", "Type": "int"}, {"Name": "year", "Type": "int"}],
            parameters=projection,
        )
    )
    event = _event() | {
        "partitionKeys": [
            {"name": "year", "type": "integer", "range": [2020, 2030]},
            {"name": "month", "type": "integer", "range": [1, 12]},
        ]
    }

    with pytest.raises(TerminalError) as caught:
        e.handler(event, None)

    assert caught.value.reason == "table_exists"
    assert "partition keys" in caught.value.detail, "the ORDER is what disagreed, not the projection"


def test_the_loser_is_told_the_name_is_taken_and_never_that_it_succeeded():
    """The refusal reaches the actor with check-table-absent's own sentence, and nothing else.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding(catalog=_catalog(location=f"s3://{BUCKET}/alice/invoices/"))
    q = _arm_notifications()

    with pytest.raises(TerminalError):
        e.handler(_event(), None)

    assert len(q.calls) == 1, "one notification, and it is the refusal"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:execute"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body["message"] == (
        'Couldn\'t create table "sales_2026": a table with that name already exists in "alice".'
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


def test_a_table_absent_after_a_successful_statement_is_transient():
    """A read-after-write blip must cost a retry, never a user's successful create.

    Glue publishes no read-after-write guarantee, so an absent table is not evidence the create
    failed. ``TransientError`` is what ``ExecuteDdl``'s Retry names, so the machine looks again;
    a genuinely absent table still fails once that budget is spent.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _install(
        _FakeAthena(["SUCCEEDED"]),
        glue=_FakeGlue(error=_glue_error("EntityNotFoundException")),
    )
    q = _arm_notifications()

    with pytest.raises(TransientError):
        e.handler(_event(), None)

    assert q.calls == [], "a transient fault is passed through un-notified for the Retry"


def test_a_glue_throttle_on_the_read_back_is_transient():
    """The read-back re-runs rather than failing a create that may well have landed.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _install(_FakeAthena(["SUCCEEDED"]), glue=_FakeGlue(error=_glue_error("ThrottlingException")))
    with pytest.raises(TransientError):
        e.handler(_event(), None)


def test_a_deterministic_glue_fault_on_the_read_back_is_ddl_execution_failed():
    """A success that cannot be confirmed is reported as a failure, not as a created table.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _install(_FakeAthena(["SUCCEEDED"]), glue=_FakeGlue(error=_glue_error("AccessDeniedException")))
    with pytest.raises(TerminalError) as caught:
        e.handler(_event(), None)
    assert caught.value.reason == "ddl_execution_failed"


def test_a_request_whose_own_location_does_not_resolve_is_malformed():
    """This run's own LOCATION is a field of the request, so an unusable one is malformed_event.

    It is deliberately NOT ``table_exists``: nothing has been learned about another request.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding()
    event = _event() | {"location": "alice/sales/"}
    with pytest.raises(TerminalError) as caught:
        e.handler(event, None)
    assert caught.value.reason == "malformed_event"


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


def test_the_ddl_run_is_a_child_span_of_the_verbs_own_span(captured_events):
    """The Athena round trip is most of this verb's latency and the only part that can hang.

    The span is named for the operation and NOT `execute-ddl`, which is already this verb's root
    span: a child sharing its parent's name returns both to the one query an operator runs, with
    the durations counted twice. Parentage is asserted rather than presence alone.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding()

    out = e.handler(_event(), None)

    assert out["status"] == "created", "the span is asserted on a SUCCESSFUL run"
    root = captured_events.spans("execute-ddl")
    assert len(root) == 1, f"expected one execute-ddl root span, got {len(root)}"
    children = captured_events.child_spans("execute-ddl", name="athena-run-ddl")
    assert len(children) == 1, (
        f"execute-ddl emitted {len(children)} 'athena-run-ddl' child spans, expected exactly one"
    )
    assert children[0]["parent_span_id"] == root[0]["span_id"]


def test_the_read_back_is_a_child_span_of_its_own(captured_events):
    """The second AWS round trip this verb makes is told apart from the first.

    It carries apply-refresh's read-back name on purpose — the same operation asking the same
    question — so an operator filtering on it sees both planes' read-backs and neither verb's
    total.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _succeeding()

    out = e.handler(_event(), None)

    assert out["status"] == "created", "the span is asserted on a SUCCESSFUL run"
    root = captured_events.spans("execute-ddl")
    children = captured_events.child_spans("execute-ddl", name="glue-read-back-table")
    assert len(children) == 1, (
        f"execute-ddl emitted {len(children)} 'glue-read-back-table' child spans, expected one"
    )
    assert children[0]["parent_span_id"] == root[0]["span_id"]
