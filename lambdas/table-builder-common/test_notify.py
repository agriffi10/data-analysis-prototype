"""Unit tests for the best-effort notification emit helper.

clients.sqs() is stubbed with a fake whose send_message records kwargs (or raises,
to prove best-effort); config.NOTIFICATIONS_QUEUE_URL is patched per test. Runnable
under pytest or directly: python3 test_notify.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients, config  # noqa: E402
from tbcommon import notify  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402

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
from cpcommon.errors import TransientError  # noqa: E402


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
