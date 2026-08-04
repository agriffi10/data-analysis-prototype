"""Unit tests for the table-builder apply-refresh Lambda (SPEC-144).

Athena and Glue are stubbed; the runner's clock seams are driven so nothing sleeps. What
this file is really about is the two statements and their ORDER — a failed drop and a
failed create leave the world in materially different states, and the user must be told
which one happened.

Runnable under pytest OR directly: ``python3 test_apply_refresh.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "dat-prod-user-space")
os.environ.setdefault("SHARED_SPACE_BUCKET", "dat-prod-shared-space")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import json

import apply_refresh as m
import pytest
import refresh_athena
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

BUCKET = "dat-prod-user-space"


class _FakeAthena:
    """Scripts each statement's terminal state, in submission order."""

    def __init__(self, states=("SUCCEEDED", "SUCCEEDED")):
        self._states = list(states)
        self.queries = []

    def start_query_execution(self, **kwargs):
        self.queries.append(kwargs)
        return {"QueryExecutionId": f"q{len(self.queries)}"}

    def get_query_execution(self, **kwargs):
        state = self._states[len(self.queries) - 1]
        return {"QueryExecution": {"Status": {"State": state, "StateChangeReason": "boom"}}}


class _FakeGlue:
    """Returns the columns a real rebuild would have left behind.

    Names, not a count: the post-condition compares the NAME SET, and a fake that returns
    `c0, c1` would pass a check that a real catalog read could not.
    """

    def __init__(self, columns=("order_id", "amount"), error=None):
        self._columns = columns
        self._error = error
        self.calls = []

    def get_table(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {
            "Table": {
                "StorageDescriptor": {
                    "Columns": [{"Name": name, "Type": "string"} for name in self._columns]
                }
            }
        }


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _install(athena_states=("SUCCEEDED", "SUCCEEDED"), glue_columns=("order_id", "amount"), glue_error=None):
    athena = _FakeAthena(athena_states)
    glue = _FakeGlue(glue_columns, glue_error)
    sqs = _FakeSqs()
    clients._athena = athena
    clients._glue = glue
    clients._sqs = sqs
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"
    config.ATHENA_WORKGROUP = "test-workgroup"
    refresh_athena._sleep = lambda _seconds: None
    return athena, glue, sqs


def _event(**over):
    event = {
        "mode": "refresh",
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/sales/", "database": "alice"},
        "tableName": "sales_2026",
        "requestId": "r1",
        "format": "csv",
        "location": f"s3://{BUCKET}/alice/sales/",
        "partitionKeys": [],
        "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        "existingColumns": [{"name": "order_id", "type": "string"}],
        "storage": {
            "serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
            "parameters": {"separatorChar": ","},
            "inputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "outputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        },
        "tableProperties": {"skip.header.line.count": "1"},
        "diff": {"changed": True, "added": [{"name": "amount", "type": "string"}], "removed": [], "retyped": [], "unchanged": 1},
    }
    event.update(over)
    return event


def _expect_reason(event, reason, **install):
    _install(**install)
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── The two statements, and their order ──────────────────────────────────────


def test_the_drop_runs_before_the_create_and_nothing_runs_between_them():
    """FR-006. Every call between the two widens the window in which the user's table does
    not exist — so the assertion is about what is NOT there as much as what is."""
    athena, glue, _sqs = _install()

    m.handler(_event(), None)

    assert len(athena.queries) == 2
    assert athena.queries[0]["QueryString"].startswith("DROP TABLE IF EXISTS")
    assert athena.queries[1]["QueryString"].startswith("CREATE EXTERNAL TABLE")
    # The post-condition read is the FIRST Glue call, i.e. it happens after both
    # statements rather than between them.
    assert len(glue.calls) == 1


def test_the_recreate_carries_no_if_not_exists():
    """After a drop that silently did not take, IF NOT EXISTS turns the recreate into a
    successful no-op — and the user is told their table was refreshed when its schema is
    unchanged. The create path keeps it; this one must not have it."""
    athena, _glue, _sqs = _install()

    m.handler(_event(), None)

    assert "IF NOT EXISTS" not in athena.queries[1]["QueryString"]


def test_both_statements_run_in_the_same_place_the_create_path_writes_to():
    """A results prefix that differs between the two DDL verbs shows up as a Lake
    Formation denial on whichever path is exercised less."""
    from tbcommon.results import results_location

    athena, _glue, _sqs = _install()
    event = _event()

    m.handler(event, None)

    expected = results_location(event["space"], event["actor"])
    for query in athena.queries:
        assert query["ResultConfiguration"]["OutputLocation"] == expected


def test_identifiers_are_quoted_so_a_reserved_word_table_name_still_parses():
    athena, _glue, _sqs = _install()

    m.handler(_event(tableName="order"), None)

    assert "`alice`.`order`" in athena.queries[0]["QueryString"]
    assert "`alice`.`order`" in athena.queries[1]["QueryString"]


# ── Failure modes: they mean different things ────────────────────────────────


def test_a_failed_drop_says_nothing_was_changed():
    exc = _expect_reason(_event(), "drop_failed", athena_states=("FAILED", "SUCCEEDED"))

    assert "boom" in exc.detail


def test_a_failed_create_after_a_successful_drop_is_its_own_reason():
    """The table IS GONE. Reporting this as a generic failure would let the user assume
    nothing happened — FR-006's whole point."""
    _expect_reason(_event(), "recreate_failed", athena_states=("SUCCEEDED", "FAILED"))


def test_the_two_failures_do_not_share_a_reason_code():
    """They describe materially different states of the world, and the message layer
    renders them differently — so a shared code would be a lie in one of the two cases."""
    from tbcommon import messages

    dropped = messages.failure_message("drop_failed", "sales_2026", "alice", "refresh")
    recreated = messages.failure_message("recreate_failed", "sales_2026", "alice", "refresh")

    assert "Nothing was changed" in dropped
    assert "Nothing was changed" not in recreated
    assert "files are untouched" in recreated


def test_a_throttle_is_retryable_rather_than_terminal():
    class _Throttled(Exception):
        def __init__(self):
            super().__init__("ThrottlingException")
            self.response = {"Error": {"Code": "ThrottlingException"}}

    athena, _glue, _sqs = _install()

    def _throttle(**_kwargs):
        raise _Throttled()

    athena.start_query_execution = _throttle

    with pytest.raises(TransientError):
        m.handler(_event(), None)


# ── The post-condition (FR-004) ──────────────────────────────────────────────


def test_a_create_that_reported_success_but_left_nothing_behind_is_caught():
    """SPEC-135's lesson, and this plane's canonical failure: a verb that COMPLETED while
    the table was not created (PRs #243-246). A SUCCEEDED query is not evidence."""
    exc = _expect_reason(_event(), "recreate_failed", glue_columns=())

    assert "0 columns" in exc.detail


def test_a_rebuild_that_landed_with_the_wrong_columns_is_caught():
    """A count cannot tell a correct rebuild from one that landed against a stale catalog
    entry with the same number of columns. The name set can, for the same cost."""
    exc = _expect_reason(_event(), "recreate_failed", glue_columns=("order_id", "wrong_name"))

    assert "missing ['amount']" in exc.detail
    assert "unexpected ['wrong_name']" in exc.detail


def test_a_column_colliding_with_a_partition_key_does_not_fail_a_good_rebuild():
    """THE BUG THE COUNT CHECK HAD, and it turned a perfect rebuild into "your table was
    removed and could not be rebuilt".

    build_create_table_ddl DROPS a data column whose name collides with a partition key —
    the key wins so the DDL stays valid — while infer-schema emits the FULL inferred list.
    So the statement declares one fewer column than `columns` has, the catalog agrees with
    the statement, and a naive count comparison reports a failure on a table that is
    exactly right.
    """
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100]}]
    columns = [
        {"name": "order_id", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "year", "type": "string"},
    ]
    athena, _glue, _sqs = _install(glue_columns=("order_id", "amount"))

    out = m.handler(_event(partitionKeys=keys, columns=columns), None)

    assert out["status"] == "refreshed"
    assert out["appliedColumnCount"] == 2
    assert "PARTITIONED BY (`year` int)" in athena.queries[1]["QueryString"]


def test_a_post_condition_read_that_cannot_see_the_table_is_terminal():
    _expect_reason(_event(), "recreate_failed", glue_error=RuntimeError("EntityNotFoundException"))


def test_a_throttled_post_condition_read_is_TERMINAL_not_retryable():
    """Deliberately NOT transient, unlike every other Glue read on this plane.

    The drop and the create are already committed. A Step Functions Retry re-invokes the
    WHOLE verb, so making a failed verification retryable would re-run the destructive
    pair — dropping the table it had just rebuilt — because a read failed. A verification
    failing is not a reason to repeat the work it was verifying.
    """
    class _Throttled(Exception):
        def __init__(self):
            super().__init__("ThrottlingException")
            self.response = {"Error": {"Code": "ThrottlingException"}}

    _expect_reason(_event(), "recreate_failed", glue_error=_Throttled())


def test_both_statements_carry_an_idempotency_token_derived_from_the_request():
    """What makes a Retry SAFE on a destructive pair: a re-invocation recomputes the same
    token, so Athena re-attaches to the original execution instead of dropping the table a
    second time. cpcommon.athena has warned about this since SPEC-111; run_ddl simply
    never offered the parameter until now.
    """
    athena, _glue, _sqs = _install()

    m.handler(_event(), None)

    assert athena.queries[0]["ClientRequestToken"] == "r1-refresh-drop"
    assert athena.queries[1]["ClientRequestToken"] == "r1-refresh-create"
    assert athena.queries[0]["ClientRequestToken"] != athena.queries[1]["ClientRequestToken"]


def test_the_two_statements_share_one_poll_budget():
    """Two independent 240 s caps inside a 300 s function would let Lambda kill the
    invocation BETWEEN the drop and the create — table gone, and no notification at all,
    because the process is dead before @notifies_on_failure can run."""
    _install()
    budgets = []
    real_run = refresh_athena.athena.run_ddl

    def _capture(**kwargs):
        budgets.append(kwargs["max_poll_duration_seconds"])
        return real_run(**kwargs)

    refresh_athena.athena.run_ddl = _capture
    try:
        m.handler(_event(), None)
    finally:
        refresh_athena.athena.run_ddl = real_run

    assert sum(budgets) <= refresh_athena.TOTAL_POLL_BUDGET_SECONDS * 2
    assert max(budgets) <= refresh_athena.TOTAL_POLL_BUDGET_SECONDS
    # Both statements plus the post-condition must fit inside the function's own timeout.
    assert refresh_athena.TOTAL_POLL_BUDGET_SECONDS < 300


# ── The regenerated statement ────────────────────────────────────────────────


def test_projection_properties_are_emitted_exactly_once_on_a_partitioned_refresh():
    """clone_definition copies EVERY Glue parameter, so a partitioned table's capture
    always carries the projection keys — and the builder regenerates the same keys from
    the reconstructed partition keys. Merging naively emits each one twice inside one
    TBLPROPERTIES (…)."""
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4}]
    captured = {
        "skip.header.line.count": "1",
        "projection.enabled": "true",
        "projection.year.type": "integer",
        "projection.year.range": "2000,2100",
        "projection.year.digits": "4",
    }
    athena, _glue, _sqs = _install()

    m.handler(_event(partitionKeys=keys, tableProperties=captured), None)

    statement = athena.queries[1]["QueryString"]
    for prop in ("projection.enabled", "projection.year.type", "projection.year.range", "projection.year.digits"):
        assert statement.count(f"'{prop}'=") == 1, prop
    assert "'projection.year.range'='2000,2100'" in statement


def test_a_column_comment_survives_the_rebuild():
    """THE ONE PIECE OF COLUMN METADATA A USER WRITES, and a DROP + CREATE is exactly where
    it disappears. Inference returns names and types; it has nothing to say about what a
    column MEANS, so the comment is metadata only the old table holds.
    """
    athena, _glue, _sqs = _install()
    existing = [
        {"name": "order_id", "type": "string", "comment": "the shop's own id"},
        {"name": "gone", "type": "string", "comment": "dropped upstream"},
    ]

    m.handler(_event(existingColumns=existing), None)

    statement = athena.queries[1]["QueryString"]
    # An apostrophe in free text must not end the literal and turn the rest into syntax.
    assert "`order_id` string COMMENT 'the shop\\'s own id'" in statement
    # A column that no longer exists carries nothing into the rebuild.
    assert "dropped upstream" not in statement
    # A newly inferred column simply has no comment.
    assert "`amount` string," in statement or statement.count("`amount` string") == 1


def test_a_comment_is_matched_case_insensitively_like_every_other_comparison():
    """Athena's Hive-backed DDL stores what it creates in lower case, so the captured name
    and the freshly inferred one can differ only by case — the same fold the diff uses."""
    athena, _glue, _sqs = _install()
    existing = [{"name": "Order_ID", "type": "string", "comment": "kept"}]

    m.handler(_event(existingColumns=existing), None)

    assert "COMMENT 'kept'" in athena.queries[1]["QueryString"]


def test_a_carried_property_survives_the_rebuild():
    athena, _glue, _sqs = _install()

    m.handler(_event(), None)

    assert "'skip.header.line.count'='1'" in athena.queries[1]["QueryString"]


def test_the_rebuilt_table_is_still_marked_portal_managed():
    """apply-refresh is a DROP + CREATE, so the marker survives only because the rebuild
    re-emits it — clone_definition strips it from the capture (SPEC-143 FR-007)."""
    athena, _glue, _sqs = _install()

    m.handler(_event(), None)

    assert "'portal.managed'='true'" in athena.queries[1]["QueryString"]


# ── Outcome ──────────────────────────────────────────────────────────────────


def test_success_emits_the_refreshed_status_and_exactly_one_notification():
    _athena, _glue, sqs = _install()

    out = m.handler(_event(), None)

    assert out["status"] == "refreshed"
    assert out["appliedColumnCount"] == 2
    assert len(sqs.calls) == 1
    body = json.loads(sqs.calls[0]["MessageBody"])
    assert "1 column added" in body["message"]
    assert sqs.calls[0]["MessageDeduplicationId"] == "r1:refresh"


def test_a_failure_notifies_the_actor_before_the_state_machine_records_it():
    _install(athena_states=("SUCCEEDED", "FAILED"))
    try:
        m.handler(_event(), None)
    except TerminalError:
        pass

    body = json.loads(clients._sqs.calls[0]["MessageBody"])
    assert "files are untouched" in body["message"]


def test_the_generated_ddl_is_logged_so_an_operator_can_reproduce_it():
    """FR-006. Schema, not file contents — permitted by the field rule, and the only way
    to reproduce a failed rebuild by hand."""
    _install()
    events = []
    real_info = m.observability.info
    m.observability.info = lambda message, **fields: events.append((message, fields))
    try:
        m.handler(_event(), None)
    finally:
        m.observability.info = real_info

    applying = next(fields for message, fields in events if message == "applying refresh")
    assert applying["ddl"].startswith("CREATE EXTERNAL TABLE `alice`.`sales_2026`")

    applied = next(fields for message, fields in events if message == "refresh applied")
    assert applied["drop_query_execution_id"] == "q1"
    assert applied["create_query_execution_id"] == "q2"


def test_traced_is_outermost_above_notifies_on_failure():
    import inspect

    source = inspect.getsource(m)

    assert source.index('@observability.traced("apply-refresh")') < source.index('@notify.notifies_on_failure("apply")')


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
