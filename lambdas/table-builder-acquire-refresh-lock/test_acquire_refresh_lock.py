"""SPEC-157 FR-002/FR-003 — the refresh lock's acquire verb.

The lock primitive has its own suite against a fake with real conditional-put semantics
(``table-builder-common/test_table_lock.py``). What is asserted HERE is what only the verb does:
that the request id is the holder, that a refusal is terminal and notified under
``refresh_already_running``, and that a refused request writes NOTHING.

Runnable under pytest or directly: python3 test_acquire_refresh_lock.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import acquire_refresh_lock as verb
from cpcommon import clients, config
from cpcommon.errors import TerminalError
from tbcommon import table_lock

REQUEST = {
    "requestId": "req-1",
    "actor": "alice",
    "mode": "refresh",
    "tableName": "sales",
    "space": {"database": "alice", "bucket": "dat-prod-user-space"},
    "execution": {"arn": "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"},
}


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


@pytest.fixture
def sqs(monkeypatch):
    monkeypatch.setattr(
        config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/notifications.fifo", raising=False
    )
    fake = _FakeSqs()
    monkeypatch.setattr(clients, "_sqs", fake)
    return fake


@pytest.fixture
def lock(monkeypatch):
    """Records what the verb asked of the primitive, and answers however the test wants."""
    calls = {"acquire": [], "result": (True, '"etag-1"')}

    def _acquire(database, table, holder):
        calls["acquire"].append((database, table, holder))
        return calls["result"]

    monkeypatch.setattr(table_lock, "acquire", _acquire)
    return calls


def test_the_holder_is_the_execution_arn_and_not_the_request_id(lock, sqs):
    """The request id identifies the MESSAGE, and Pipes delivery is at-least-once.

    Two executions of one redelivered message carry the same request id, and table_lock's
    re-entrancy branch would then hand the lock to BOTH — silently, with no refusal event. The
    ARN is what distinguishes them, which is why StampExecution exists.
    """
    verb.handler(dict(REQUEST), None)

    assert lock["acquire"] == [
        ("alice", "sales", "arn:aws:states:us-east-1:1:execution:orchestrator:run-a")
    ]
    assert "req-1" not in {holder for _, _, holder in lock["acquire"]}


def test_a_successful_claim_threads_the_etag_without_disturbing_the_request(lock, sqs):
    """The release state conditions its write on this tag, and the shared spine downstream
    must see the same object it always did."""
    result = verb.handler(dict(REQUEST), None)

    assert result["lock"] == {"etag": '"etag-1"'}
    assert {k: v for k, v in result.items() if k != "lock"} == REQUEST


def test_a_held_lock_is_a_terminal_refusal_named_for_the_reason(lock, sqs):
    lock["result"] = (False, None)

    with pytest.raises(TerminalError) as raised:
        verb.handler(dict(REQUEST), None)

    assert raised.value.reason == "refresh_already_running"


def test_the_refusal_notifies_the_actor(lock, sqs):
    """FR-003 AC2. The refusal IS the notification — nothing else tells the user this request
    did nothing, and silence is the failure mode SPEC-152 exists to close."""
    lock["result"] = (False, None)

    with pytest.raises(TerminalError):
        verb.handler(dict(REQUEST), None)

    assert len(sqs.calls) == 1


def test_a_refused_request_returns_no_lock_for_anything_downstream_to_release(lock, sqs):
    """FR-003 AC4. A refused request must leave the table, the lock and the registry
    byte-identical — and the release verb keys entirely off the absence of $.lock."""
    lock["result"] = (False, None)

    with pytest.raises(TerminalError):
        verb.handler(dict(REQUEST), None)

    assert "lock" not in REQUEST


@pytest.mark.parametrize("missing", ["execution", "tableName", "space"])
def test_a_malformed_request_is_terminal_before_any_lock_is_touched(lock, sqs, missing):
    event = {k: v for k, v in REQUEST.items() if k != missing}

    with pytest.raises(TerminalError):
        verb.handler(event, None)

    assert lock["acquire"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
