"""Unit tests for the table-builder diff-schema Lambda (SPEC-144).

`compute_diff` is pure and tested directly against column-list pairs; the verb is tested
for the two decisions it owns — the removal opt-in and the no-op short circuit.

Runnable under pytest OR directly: ``python3 test_diff_schema.py``.
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

import diff_schema as m
import pytest
from cpcommon import clients, config
from cpcommon.errors import TerminalError


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


def _cols(*pairs):
    return [{"name": n, "type": t} for n, t in pairs]


def _event(existing, inferred, *, allow_removals=False, partition_keys=()):
    return {
        "mode": "refresh",
        "actor": "alice",
        "space": {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/", "database": "alice"},
        "tableName": "sales_2026",
        "requestId": "r1",
        "allowRemovals": allow_removals,
        "partitionKeys": [{"name": n} for n in partition_keys],
        "existingColumns": existing,
        "columns": inferred,
    }


def _expect_reason(event, reason):
    try:
        m.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── compute_diff: pure classification (FR-001) ───────────────────────────────


def test_an_identical_schema_is_unchanged():
    diff = m.compute_diff(_cols(("a", "string"), ("b", "bigint")), _cols(("a", "string"), ("b", "bigint")), set())

    assert diff == {"changed": False, "added": [], "removed": [], "retyped": [], "unchanged": 2}


def test_all_four_classes_at_once():
    diff = m.compute_diff(
        _cols(("keep", "string"), ("gone", "bigint"), ("widened", "int")),
        _cols(("keep", "string"), ("widened", "bigint"), ("fresh", "double")),
        set(),
    )

    assert diff["added"] == [{"name": "fresh", "type": "double"}]
    assert diff["removed"] == [{"name": "gone", "type": "bigint"}]
    assert diff["retyped"] == [{"name": "widened", "from": "int", "to": "bigint"}]
    assert diff["unchanged"] == 1
    assert diff["changed"] is True


def test_unchanged_is_a_count_not_a_list():
    """On a wide table the names would dominate the Step Functions state payload, and they
    are the one part of the diff nobody needs by name."""
    diff = m.compute_diff(_cols(*[(f"c{i}", "string") for i in range(50)]), _cols(*[(f"c{i}", "string") for i in range(50)]), set())

    assert diff["unchanged"] == 50


def test_names_are_matched_case_sensitively():
    """Athena treats `Amount` and `amount` as distinct columns. A case-insensitive match
    would report `unchanged` for a pair the engine considers a rename — the silent wrong
    answer this feature exists to prevent."""
    diff = m.compute_diff(_cols(("Amount", "string")), _cols(("amount", "string")), set())

    assert diff["added"] == [{"name": "amount", "type": "string"}]
    assert diff["removed"] == [{"name": "Amount", "type": "string"}]


def test_partition_keys_are_excluded_by_compute_diff_itself():
    """FR-001 AC6, and the fixture is the point: a data file whose header carries a column
    NAMED AFTER a partition key does reach this verb. `infer-schema` emits the full
    inferred list, and the partition-collision drop happens inside build_create_table_ddl,
    where it affects only the DDL body. Without this exclusion, that column would be
    reported as added or removed on EVERY refresh, forever.
    """
    diff = m.compute_diff(
        _cols(("amount", "double")),
        _cols(("year", "bigint"), ("amount", "double")),
        {"year"},
    )

    assert diff == {"changed": False, "added": [], "removed": [], "retyped": [], "unchanged": 1}


def test_a_partition_key_missing_from_the_existing_columns_is_not_a_removal():
    """The existing list comes from Glue's Columns, which EXCLUDE partition keys, while the
    inferred list includes them — so the exclusion has to apply to both sides or every
    partitioned refresh reports its own keys as added."""
    diff = m.compute_diff(_cols(("amount", "double")), _cols(("amount", "double"), ("year", "bigint")), {"year"})

    assert diff["added"] == []


# ── The removal opt-in (FR-003) ──────────────────────────────────────────────


def test_a_removal_without_the_opt_in_is_refused_and_names_the_columns():
    queue = _arm_notifications()
    event = _event(_cols(("keep", "string"), ("gone", "bigint")), _cols(("keep", "string")))

    exc = _expect_reason(event, "columns_removed")

    assert json.loads(exc.tokens["removedNames"]) == ["gone"]
    body = json.loads(queue.calls[0]["MessageBody"])
    assert "gone" in body["message"]
    assert body["link"] == "/query?refreshTable=alice.sales_2026&removed=gone"


def test_the_refusal_changes_nothing():
    """FR-003 AC6. The verb issues no DDL at all — it has no Athena client — so the
    assertion that matters is that it RAISES rather than returning a state a later verb
    would act on."""
    event = _event(_cols(("gone", "bigint")), [])

    _expect_reason(event, "columns_removed")


def test_a_removal_with_the_opt_in_proceeds():
    event = _event(_cols(("keep", "string"), ("gone", "bigint")), _cols(("keep", "string")), allow_removals=True)

    out = m.handler(event, None)

    assert out["diff"]["removed"] == [{"name": "gone", "type": "bigint"}]
    assert out["diff"]["changed"] is True
    # Not a terminal outcome — apply-refresh owns the notification on this path.
    assert "status" not in out


def test_an_added_column_never_needs_the_opt_in():
    event = _event(_cols(("keep", "string")), _cols(("keep", "string"), ("fresh", "double")))

    out = m.handler(event, None)

    assert out["diff"]["added"] == [{"name": "fresh", "type": "double"}]


# ── The no-op short circuit (FR-002) ─────────────────────────────────────────


def test_an_unchanged_schema_sets_the_status_record_success_reads():
    """RecordSuccess threads `$.status`, and a Pass state's JSONPath raises an UNCATCHABLE
    States.Runtime on an absent key — after the run already succeeded. No Lambda runs after
    this one on the unchanged path, so it is set here or nowhere."""
    _arm_notifications()
    out = m.handler(_event(_cols(("a", "string")), _cols(("a", "string"))), None)

    assert out["status"] == "unchanged"
    assert out["diff"]["changed"] is False


def test_the_unchanged_outcome_is_notified_by_this_verb():
    """FR-002 AC2. The state machine has NO notification state and every notification on
    this plane is emitted in-Lambda — so on the path where nothing runs after this verb,
    silence is the alternative."""
    queue = _arm_notifications()

    m.handler(_event(_cols(("a", "string")), _cols(("a", "string"))), None)

    assert len(queue.calls) == 1
    body = json.loads(queue.calls[0]["MessageBody"])
    assert "no schema changes were found" in body["message"]
    assert queue.calls[0]["MessageDeduplicationId"] == "r1:refresh"


def test_exactly_one_notification_per_run_on_each_path():
    """FR-002 AC5. Two emits would be two inbox entries for one run; zero is silence on an
    outcome the user asked for."""
    unchanged = _arm_notifications()
    m.handler(_event(_cols(("a", "string")), _cols(("a", "string"))), None)
    assert len(unchanged.calls) == 1

    changed = _arm_notifications()
    m.handler(_event(_cols(("a", "string")), _cols(("a", "string"), ("b", "int"))), None)
    assert changed.calls == [], "the changed path is apply-refresh's to notify"

    refused = _arm_notifications()
    _expect_reason(_event(_cols(("a", "string"), ("b", "int")), _cols(("a", "string"))), "columns_removed")
    assert len(refused.calls) == 1


# ── Shape + observability ────────────────────────────────────────────────────


def test_a_malformed_state_is_a_typed_terminal():
    for missing in ("existingColumns", "columns"):
        event = _event(_cols(("a", "string")), _cols(("a", "string")))
        del event[missing]

        _expect_reason(event, "malformed_event")


def test_the_verb_narrates_the_classification_without_naming_any_data():
    _arm_notifications()
    events = []
    real_info = m.observability.info
    m.observability.info = lambda message, **fields: events.append((message, fields))
    try:
        m.handler(
            _event(_cols(("keep", "string"), ("gone", "int")), _cols(("keep", "string")), allow_removals=True),
            None,
        )
    finally:
        m.observability.info = real_info

    message, fields = events[0]
    assert message == "diffed schema"
    assert fields["removed_count"] == 1
    assert fields["removed_names"] == ["gone"]
    assert fields["unchanged_count"] == 1
    assert fields["allow_removals"] is True


def test_traced_is_outermost_above_notifies_on_failure():
    import inspect

    source = inspect.getsource(m)

    assert source.index('@observability.traced("diff-schema")') < source.index('@notify.notifies_on_failure("diff")')


def test_the_opt_in_is_read_from_the_request_and_persisted_nowhere():
    """FR-003 AC7. The flag authorises data loss for ONE run; a persisted copy would carry
    that authorisation into a later refresh nobody opted in for."""
    verbs = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    allowed = {
        os.path.join("table-builder-validate-authorize", "validate_authorize.py"),
        os.path.join("table-builder-validate-authorize", "test_validate_authorize.py"),
        os.path.join("table-builder-diff-schema", "diff_schema.py"),
        os.path.join("table-builder-diff-schema", "test_diff_schema.py"),
    }

    offenders = []
    for root, _dirs, files in os.walk(verbs):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, verbs)
            if relative in allowed:
                continue
            with open(path) as handle:
                if "allowRemovals" in handle.read():
                    offenders.append(relative)

    assert not offenders, f"allowRemovals appears outside the request path: {offenders}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
