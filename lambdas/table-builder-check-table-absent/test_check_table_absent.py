"""Unit tests for the table-builder check-table-absent Lambda.

Glue is stubbed via clients.glue(): a fake catalog client whose get_table either
returns (table exists), raises EntityNotFoundException (absent → pass), or raises a
transient error (must propagate, not be terminalized). Runnable under pytest or
directly: python3 test_check_table_absent.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import check_table_absent as c  # noqa: E402
from cpcommon import clients, config  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    """Configure the notifications queue + a fake SQS so emits are observable."""
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


class _EntityNotFound(Exception):
    pass


class _FakeClientError(Exception):
    """A botocore-SHAPED error: carries ``.response["Error"]["Code"]`` so the verb's
    ``raise_if_transient`` classifier can actually read the code. The old ``_Throttling``
    double had the code in its message only (no ``.response``), so the transient mapping
    never fired and the transient test passed regardless of the fix."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeGlue:
    """Minimal Glue client double: `.exceptions.EntityNotFoundException` + get_table."""

    class exceptions:
        EntityNotFoundException = _EntityNotFound

    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def get_table(self, DatabaseName, Name):  # noqa: N803 - boto3 kwarg names
        self.calls.append((DatabaseName, Name))
        if self._behaviour == "found":
            return {"Table": {"Name": Name}}
        if self._behaviour == "absent":
            raise _EntityNotFound("not found")
        if self._behaviour == "transient":
            raise _FakeClientError("ThrottlingException")
        if self._behaviour == "denied":
            raise _FakeClientError("AccessDenied")
        raise AssertionError(self._behaviour)


def _install(behaviour):
    fake = _FakeGlue(behaviour)
    clients._glue = fake
    return fake


def _event(table="sales_2026", database="alice"):
    return {"space": {"database": database}, "tableName": table, "requestId": "r1"}


def test_absent_table_passes_through_unchanged():
    _install("absent")
    out = c.handler(_event(), None)
    assert out == _event()  # untouched


def test_existing_table_is_terminal_table_exists():
    _install("found")
    try:
        c.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == "table_exists"
        assert "sales_2026" in str(exc) and "alice" in str(exc)
        return
    raise AssertionError("expected TerminalError(table_exists)")


def test_transient_glue_throttle_is_raised_as_TransientError():
    """A Glue throttle must reach the SFN as TransientError — the name CheckTableAbsent's
    Retry list now recognizes. A bare ClientError matches nothing there and would
    permanently fail the build."""
    _install("transient")
    try:
        c.handler(_event(), None)
    except TransientError:
        return
    except TerminalError:
        raise AssertionError("a throttle must not be terminalized")
    raise AssertionError("expected TransientError from a throttled get_table")


def test_non_transient_glue_error_propagates_unchanged():
    """AccessDenied is deterministic — mapping it to TransientError would waste retries."""
    _install("denied")
    try:
        c.handler(_event(), None)
    except TransientError:
        raise AssertionError("a deterministic fault must NOT become TransientError")
    except _FakeClientError as err:
        assert err.response["Error"]["Code"] == "AccessDenied"
        return
    raise AssertionError("expected the original ClientError to propagate")


def test_check_table_absent_state_retries_TransientError():
    """The code half is useless without the infra half — pin that CheckTableAbsent's
    Retry names TransientError."""
    import re

    tftpl = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "infra", "modules", "table-builder", "state-machine.asl.json.tftpl",
    )
    with open(tftpl) as fh:
        asl = json.loads(re.sub(r"\$\{[^}]+\}", "ARN", fh.read()))
    named = [e for r in asl["States"]["CheckTableAbsent"]["Retry"] for e in r["ErrorEquals"]]
    assert "TransientError" in named, f"CheckTableAbsent Retry must name TransientError; got {named}"


def test_targets_the_declared_database_and_table():
    fake = _install("absent")
    c.handler(_event(table="orders", database="salesdata"), None)
    assert fake.calls == [("salesdata", "orders")]


def _actor_event():
    ev = _event()
    ev["actor"] = "alice"  # the validated payload carries the actor
    return ev


def test_notifies_actor_on_table_exists():
    _install("found")
    q = _arm_notifications()
    try:
        c.handler(_actor_event(), None)
    except TerminalError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:check"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body == {
        "action": "create",
        "username": "alice",
        "message": 'Couldn\'t create table "sales_2026": a table with that name already exists in "alice".',
    }


def test_no_notification_when_absent():
    _install("absent")
    q = _arm_notifications()
    c.handler(_actor_event(), None)
    assert q.calls == []


def test_notifies_actor_on_unexpected_glue_error():
    # A DETERMINISTIC error that escapes the handler (not a TerminalError, not transient) —
    # e.g. AccessDenied — is a terminal failure the SFN records; @notifies_on_failure tells
    # the actor rather than failing silently, and the original exception propagates
    # unchanged. NOTE: a *transient* throttle is now mapped to TransientError and passes
    # through un-notified (it will be retried) — so this deliberately uses "denied".
    _install("denied")
    q = _arm_notifications()
    try:
        c.handler(_actor_event(), None)
    except _FakeClientError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"
    assert q.calls[0]["MessageDeduplicationId"] == "r1:check"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body == {
        "action": "create",
        "username": "alice",
        "message": 'Couldn\'t create table "sales_2026": something went wrong. Please try again.',
    }


def test_malformed_event_is_terminal_and_notifies():
    # SPEC-083 FR-002: a task input missing a required key becomes a typed terminal +
    # actor notification, not a bare KeyError.
    _install("absent")
    q = _arm_notifications()
    bad = {"actor": "alice", "requestId": "r1"}  # no space.database / tableName
    try:
        c.handler(bad, None)
    except TerminalError as exc:
        assert exc.reason == "malformed_event"
    else:
        raise AssertionError("expected TerminalError(malformed_event)")
    assert len(q.calls) == 1 and q.calls[0]["MessageGroupId"] == "alice"


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
