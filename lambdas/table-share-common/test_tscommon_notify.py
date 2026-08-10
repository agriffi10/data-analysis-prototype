"""Unit tests for tscommon.notify + tscommon.messages (SPEC-094).

clients.sqs() is stubbed with a fake whose send_message records kwargs (or raises,
to prove best-effort); config.NOTIFICATIONS_QUEUE_URL is patched per test; the
registry owner lookup is faked for the space-success fan-out. Runnable under
pytest or directly: python3 test_tscommon_notify.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError
from tscommon import messages, notify

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


def _install(raises=False, queue=QUEUE, owner="olivia"):
    config.NOTIFICATIONS_QUEUE_URL = queue
    fake = _FakeSqs(raises=raises)
    clients._sqs = fake
    notify.reg.load = lambda name: {"owner": owner} if owner is not None else None
    return fake


def _sent(fake):
    return [(c["MessageGroupId"], json.loads(c["MessageBody"])["message"]) for c in fake.calls]


def _map_event(kind="user", name="bob"):
    return {
        "recipient": {"kind": kind, "name": name, "valid": True, "database": name},
        "request": {"actor": "alice", "source": {"database": "alice", "table": "orders"}, "tableName": "orders_copy"},
    }


def _request_event():
    return {"actor": "alice", "source": {"database": "alice", "table": "orders"}, "tableName": "orders_copy"}


def test_emit_notification_builds_the_create_envelope_grouped_by_recipient():
    fake = _install()
    notify.emit_notification("alice", "hi")
    call = fake.calls[0]
    assert call["QueueUrl"] == QUEUE
    assert call["MessageGroupId"] == "alice"
    assert "MessageDeduplicationId" not in call  # content-based dedup queue
    assert json.loads(call["MessageBody"]) == {"action": "create", "username": "alice", "message": "hi"}


def test_emit_is_noop_without_queue_or_recipient_and_never_raises():
    fake = _install(queue="")
    notify.emit_notification("alice", "hi")
    assert fake.calls == []
    fake = _install()
    notify.emit_notification("", "hi")
    assert fake.calls == []
    fake = _install(raises=True)
    notify.emit_notification("alice", "hi")  # SQS down -> logged, not raised
    assert len(fake.calls) == 1


def test_per_recipient_failure_notifies_the_sender_with_the_recipient_and_reason():
    fake = _install()
    err = TerminalError("conflict", "already there")
    notify.emit_failure(_map_event(kind="space", name="salesteam"), err, "check")
    [(group, message)] = _sent(fake)
    assert group == "alice"
    assert message == 'Couldn\'t share "orders" to space "salesteam": a table named "orders_copy" already exists there.'


def test_whole_request_failure_names_only_the_source():
    fake = _install()
    notify.emit_failure(_request_event(), TerminalError("source_is_view", "v"), "inspect")
    [(group, message)] = _sent(fake)
    assert group == "alice"
    assert message == 'Couldn\'t share "orders": views can\'t be shared - only tables with data files.'


def test_create_failed_omits_raw_athena_detail():
    # SPEC-106 FR-008: the raw Athena StateChangeReason must not reach the inbox.
    fake = _install()
    notify.emit_failure(_map_event(), TerminalError("create_failed", "SYNTAX_ERROR: line 1"), "create")
    [(_, message)] = _sent(fake)
    assert "SYNTAX_ERROR" not in message
    assert message.endswith("creating the table failed. Please try again or contact the Administrator.")


def test_the_errors_tokens_reach_the_message_rather_than_being_discarded():
    """SPEC-156 FR-002. `emit_failure` used to drop `err.tokens` on the floor, so a body
    needing a value had no way to get one — which is why the recipient cap was baked into a
    literal. Detail and tokens are opposite channels: the detail must stay out of the inbox
    and the tokens must reach it.
    """
    from cpcommon import messages as cpmessages

    fake = _install()
    messages._BODIES["_token_probe"] = "the widget {thing} broke."  # test-only
    cpmessages.register_reasons(["_token_probe"])
    try:
        notify.emit_failure(
            _request_event(),
            TerminalError("_token_probe", "raw operator text", tokens={"thing": "gizmo"}),
            "inspect",
        )
    finally:
        messages._BODIES.pop("_token_probe", None)

    [(_, message)] = _sent(fake)
    assert message == 'Couldn\'t share "orders": the widget gizmo broke.'
    assert "raw operator text" not in message


def test_access_denied_reasons_surface_no_table_detail():
    assert messages.failure_message("forbidden", "orders") == "You don't have access to share that table."


def test_a_collected_copy_failure_reads_like_any_other_per_recipient_failure():
    """SPEC-160. The copy failure is the one per-recipient outcome with no failing verb to
    notify from — the batch that failed spans several recipients and succeeds anyway — so the
    collector emits it. The sentence must be the one the decorator would have produced.
    """
    fake = _install()

    notify.emit_recipient_failure(
        {"actor": "alice", "source": {"database": "alice", "table": "orders"}, "tableName": "orders_copy"},
        "user",
        "bob",
        "copy_failed",
    )

    assert _sent(fake) == [
        ("alice", 'Couldn\'t share "orders" to user "bob": copying the data failed.')
    ]


def test_a_collected_failure_with_no_actor_is_a_no_op():
    fake = _install()
    notify.emit_recipient_failure({}, "user", "bob", "copy_failed")
    assert _sent(fake) == []


def test_user_recipient_success_notifies_sender_and_the_user():
    fake = _install()
    notify.emit_recipient_success(_map_event(kind="user", name="bob"))
    assert _sent(fake) == [
        ("alice", 'Shared "orders" to user "bob" as "orders_copy".'),
        ("bob", 'alice shared table "orders_copy" with you in "bob".'),
    ]


def test_space_recipient_success_notifies_sender_and_the_owner_only():
    fake = _install(owner="olivia")
    notify.emit_recipient_success(_map_event(kind="space", name="salesteam"))
    assert _sent(fake) == [
        ("alice", 'Shared "orders" to space "salesteam" as "orders_copy".'),
        ("olivia", 'alice shared table "orders_copy" into your space "salesteam".'),
    ]


def test_unresolvable_owner_skips_the_owner_message_but_keeps_the_senders():
    fake = _install(owner=None)  # registry record missing
    notify.emit_recipient_success(_map_event(kind="space", name="salesteam"))
    assert _sent(fake) == [("alice", 'Shared "orders" to space "salesteam" as "orders_copy".')]

    fake = _install()
    notify.reg.load = lambda name: (_ for _ in ()).throw(RuntimeError("s3 down"))
    notify.emit_recipient_success(_map_event(kind="space", name="salesteam"))
    assert _sent(fake) == [("alice", 'Shared "orders" to space "salesteam" as "orders_copy".')]


def test_wrapper_notifies_sender_on_terminal_error_by_default():
    fake = _install()

    @notify.notifies_on_failure("check")
    def terminal(event, context):
        raise TerminalError("conflict", "x")

    # Default: the wrapper owns the TerminalError notification (verbs dropped their own
    # try/except) — the sender hears exactly one failure message naming the source table.
    try:
        terminal(_map_event(), None)
    except TerminalError:
        pass
    [(group, message)] = _sent(fake)
    assert group == "alice"
    assert 'Couldn\'t share "orders"' in message


def test_wrapper_stays_quiet_on_transient_and_when_notify_terminal_false():
    @notify.notifies_on_failure("check")
    def transient(event, context):
        raise TransientError("throttled")

    # notify_terminal=False → validate-authorize owns its own actor-aware notification.
    @notify.notifies_on_failure("validate", notify_terminal=False)
    def terminal_quiet(event, context):
        raise TerminalError("unauthorized", "no token")

    for fn, exc in ((transient, TransientError), (terminal_quiet, TerminalError)):
        fake = _install()
        try:
            fn(_map_event(), None)
        except exc:
            pass
        assert fake.calls == []


def test_wrapper_notifies_generic_on_unexpected_exception():
    fake = _install()

    @notify.notifies_on_failure("check")
    def unexpected(event, context):
        raise RuntimeError("boom")

    try:
        unexpected(_map_event(), None)
    except RuntimeError:
        pass
    [(group, message)] = _sent(fake)
    assert group == "alice"
    assert "something went wrong" in message


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
