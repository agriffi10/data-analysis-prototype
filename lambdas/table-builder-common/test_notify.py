"""Unit tests for the best-effort notification emit helper.

clients.sqs() is stubbed with a fake whose send_message records kwargs (or raises,
to prove best-effort); config.NOTIFICATIONS_QUEUE_URL is patched per test. Runnable
under pytest or directly: python3 test_notify.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients, config
from cpcommon.errors import TerminalError
from tbcommon import notify

QUEUE = "https://sqs.us-east-1.amazonaws.com/123/dat-prod-notifications-requests.fifo"


class _FakeSqs:
    def __init__(self, raises=False):
        self.calls = []
        self._raises = raises

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("SQS down")
        return {"MessageId": "m1"}


def _install(raises=False, queue=QUEUE):
    config.NOTIFICATIONS_QUEUE_URL = queue
    fake = _FakeSqs(raises=raises)
    clients._sqs = fake
    return fake


def _event(**over):
    e = {"actor": "alice", "tableName": "orders", "space": {"database": "sales"}, "requestId": "r1"}
    e.update(over)
    return e


def test_builds_the_create_envelope_fifo_grouped_by_recipient():
    fake = _install()
    notify.emit_notification("alice", "hi", dedup_id="r1:check")
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["QueueUrl"] == QUEUE
    assert call["MessageGroupId"] == "alice"
    assert call["MessageDeduplicationId"] == "r1:check"
    assert json.loads(call["MessageBody"]) == {"action": "create", "username": "alice", "message": "hi"}


def test_noop_when_queue_url_unset():
    fake = _install(queue="")
    notify.emit_notification("alice", "hi")
    assert fake.calls == []


def test_noop_when_no_recipient():
    fake = _install()
    notify.emit_notification("", "hi")
    assert fake.calls == []


def test_best_effort_swallows_send_errors():
    _install(raises=True)
    # Must NOT raise (the pipeline outcome is already recorded).
    notify.emit_notification("alice", "hi", dedup_id="r1:x")


def test_emit_failure_maps_the_reason_and_dedups_by_step():
    fake = _install()
    notify.emit_failure(_event(), TerminalError("table_exists", "detail"), "check")
    call = fake.calls[0]
    assert call["MessageGroupId"] == "alice"
    assert call["MessageDeduplicationId"] == "r1:check"
    body = json.loads(call["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "orders": a table with that name already exists in "sales".'


def test_emit_failure_omits_raw_ddl_detail():
    # SPEC-106 FR-008: the raw Athena StateChangeReason must not reach the inbox.
    fake = _install()
    notify.emit_failure(_event(), TerminalError("ddl_execution_failed", "SYNTAX_ERROR near LOCATION"), "execute")
    body = json.loads(fake.calls[0]["MessageBody"])
    assert "SYNTAX_ERROR" not in body["message"]
    assert body["message"].endswith("creating the table failed. Please try again or contact the Administrator.")


def test_emit_created_sends_the_ready_message():
    fake = _install()
    notify.emit_created(_event())
    call = fake.calls[0]
    assert call["MessageDeduplicationId"] == "r1:created"
    body = json.loads(call["MessageBody"])
    assert body["message"] == 'Table "orders" is ready to query in "sales".'


def test_emit_failure_without_actor_is_a_noop():
    fake = _install()
    notify.emit_failure(_event(actor=""), TerminalError("forbidden"), "validate")
    assert fake.calls == []


# ── notifies_on_failure wrapper ──────────────────────────────────────────────
from cpcommon.errors import TransientError


def test_wrapper_passes_result_through_on_success():
    fake = _install()

    @notify.notifies_on_failure("check")
    def h(event, context):
        return {"ok": True}

    assert h(_event(), None) == {"ok": True}
    assert fake.calls == []  # success never notifies


def test_wrapper_notifies_actor_on_terminal_error_by_default():
    fake = _install()

    @notify.notifies_on_failure("check")
    def h(event, context):
        raise TerminalError("table_exists", "already there")

    try:
        h(_event(), None)
    except TerminalError:
        pass
    # The wrapper now owns the TerminalError notification (verbs dropped their own
    # try/except): exactly one actor-addressed failure message, deduped by step.
    assert len(fake.calls) == 1
    assert fake.calls[0]["MessageDeduplicationId"] == "r1:check"
    body = json.loads(fake.calls[0]["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "orders": a table with that name already exists in "sales".'


def test_wrapper_stays_quiet_on_terminal_error_when_notify_terminal_false():
    fake = _install()

    @notify.notifies_on_failure("validate", notify_terminal=False)
    def h(event, context):
        raise TerminalError("unauthorized", "no token")

    try:
        h(_event(), None)
    except TerminalError:
        pass
    # validate-authorize notifies inside its own actor-aware orchestration, so the
    # wrapper must stay quiet on TerminalError.
    assert fake.calls == []


def test_wrapper_does_not_notify_transient_error():
    fake = _install()

    @notify.notifies_on_failure("execute")
    def h(event, context):
        raise TransientError("throttled")

    try:
        h(_event(), None)
    except TransientError:
        pass
    # Retryable — the SFN Retry re-runs it; notifying now would be premature.
    assert fake.calls == []


def test_wrapper_notifies_and_reraises_on_unexpected_error():
    fake = _install()

    @notify.notifies_on_failure("check")
    def h(event, context):
        raise RuntimeError("AccessDenied")

    try:
        h(_event(), None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the original exception must propagate")
    assert len(fake.calls) == 1
    assert fake.calls[0]["MessageDeduplicationId"] == "r1:check"
    body = json.loads(fake.calls[0]["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "orders": something went wrong. Please try again.'


def test_wrapper_tolerates_non_dict_event():
    # validate-authorize's raw input is the SQS array; an unexpected failure there has
    # no bound actor, so the emit is a no-op (not a crash).
    fake = _install()

    @notify.notifies_on_failure("validate")
    def h(event, context):
        raise RuntimeError("boom")

    try:
        h([{"body": "..."}], None)
    except RuntimeError:
        pass
    assert fake.calls == []


# ── The refresh channel (SPEC-144 FR-009) ────────────────────────────────────


def test_the_mode_on_the_event_picks_the_failure_verb():
    fake = _install()
    notify.emit_failure(_event(mode="refresh"), TerminalError("table_not_found", "d"), "load")
    body = json.loads(fake.calls[0]["MessageBody"])

    assert body["message"].startswith('Couldn\'t refresh table "orders":')


def test_tokens_reach_the_message():
    """The channel `cpcommon.errors` documents as deliberately unused by this plane until
    now — FR-003's warning is nothing without it, since the message must NAME the columns."""
    fake = _install()
    notify.emit_failure(
        _event(mode="refresh"),
        TerminalError("columns_removed", "2 columns", notify.removed_tokens(["legacy_id", "old_total"])),
        "diff",
    )
    body = json.loads(fake.calls[0]["MessageBody"])

    assert "legacy_id, old_total" in body["message"]


def test_columns_removed_carries_a_link_that_names_the_columns():
    fake = _install()
    notify.emit_failure(
        _event(mode="refresh"),
        TerminalError("columns_removed", "2 columns", notify.removed_tokens(["legacy_id", "old_total"])),
        "diff",
    )
    body = json.loads(fake.calls[0]["MessageBody"])

    assert body["link"] == "/query?refreshTable=sales.orders&removed=legacy_id,old_total"


def test_a_column_name_that_is_not_catalog_safe_cannot_corrupt_the_link():
    """COLUMN NAMES ARE NOT CATALOG-SAFE — the database and table are, and it is easy to
    assume the names are too. They come verbatim from a file header (`infer_schema` reads
    the CSV header / polars schema and validates nothing), so an ordinary spreadsheet
    export produces `Order ID`, and `&` or `#` in a header is entirely possible.

    Unencoded, `&` invents a query parameter and `#` truncates the rest into a fragment —
    the link would name the wrong columns or lose them, silently.
    """
    link = notify._columns_removed_link(
        "sales", "orders", notify.removed_tokens(["Order ID", "a&b", "x#y", "co,mma"])
    )

    assert link == (
        "/query?refreshTable=sales.orders&removed=Order%20ID,a%26b,x%23y,co%2Cmma"
    )
    # Exactly one `&` (the separator this link owns) and one `?`; the comma still
    # separates names because only the names themselves are encoded.
    assert link.count("&") == 1 and link.count("?") == 1
    assert link.split("removed=")[1].count(",") == 3


def test_the_link_satisfies_the_browsers_own_safety_rule():
    """`isSafeInAppPath` (SPEC-061) lives in TypeScript and is NOT applied server-side —
    `emit_notification` says so explicitly, because duplicating the rule would give two
    places to keep in step. The constant `/q` prefix decides it, so this is cheap; the
    parameter tests above are the ones doing real work.
    """
    link = notify._columns_removed_link("sales", "orders", notify.removed_tokens(["a", "b"]))

    assert link.startswith("/")
    assert link[1] not in ("/", "\\")


def test_every_other_failure_reason_still_emits_without_a_link():
    fake = _install()
    for reason in ("table_exists", "no_data_files", "update_failed", "unexpected_error"):
        notify.emit_failure(_event(mode="refresh"), TerminalError(reason, "d"), "diff")

    for call in fake.calls:
        assert "link" not in json.loads(call["MessageBody"])


def test_the_link_is_capped_and_omitted_when_there_is_nothing_to_name():
    tokens = notify.removed_tokens([f"col_{i}" for i in range(30)])
    link = notify._columns_removed_link("sales", "orders", tokens)

    assert link.split("removed=")[1].count(",") == notify.MAX_NAMED_COLUMNS - 1
    assert notify._columns_removed_link("sales", "orders", {}) is None
    assert notify._columns_removed_link("", "orders", notify.removed_tokens(["a"])) is None
    # A malformed token must not raise inside a best-effort notify path.
    assert notify._columns_removed_link("sales", "orders", {"removedNames": "not json"}) is None


def test_the_display_string_is_capped_with_a_tail_and_never_re_split():
    """The tail is the reason the link reads a SEPARATE token: `and 10 more` is not a
    column name, and splitting the display string back apart would put it in the URL."""
    tokens = notify.removed_tokens([f"col_{i}" for i in range(30)])

    assert tokens["removed"].endswith(", and 10 more")
    assert len(json.loads(tokens["removedNames"])) == notify.MAX_NAMED_COLUMNS
    assert "and 10 more" not in notify._columns_removed_link("sales", "orders", tokens)


def test_both_refresh_outcomes_share_one_dedup_token():
    """Per OUTCOME, not per verb (SPEC-114): a run yields `refreshed` or `unchanged`, never
    both, and the two are emitted by different verbs on different branches."""
    fake = _install()
    notify.emit_refresh_outcome(_event(), "unchanged")
    notify.emit_refresh_outcome(_event(), "refreshed", {"added": [{"name": "c"}]})

    assert [c["MessageDeduplicationId"] for c in fake.calls] == ["r1:refresh", "r1:refresh"]
    messages = [json.loads(c["MessageBody"])["message"] for c in fake.calls]
    assert "no schema changes were found" in messages[0]
    assert "1 column added" in messages[1]


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
