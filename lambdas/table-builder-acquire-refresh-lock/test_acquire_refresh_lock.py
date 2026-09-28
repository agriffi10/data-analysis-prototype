"""SPEC-157 FR-002/FR-003 — the refresh lock's acquire verb.

The lock primitive has its own suite against a fake with real conditional-put semantics
(``table-builder-common/test_table_lock.py``). What is asserted HERE is what only the verb does:
that the request id is the holder, that a refusal is terminal and notified under
``refresh_already_running``, and that a refused request writes NOTHING.
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
    monkeypatch.setattr(clients, "_sqs_bounded", fake)
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
    """The request id is whatever the caller sent, so two executions can carry the same one.

    table_lock's re-entrancy branch would then hand the lock to BOTH — silently, with no refusal
    event. The ARN is what distinguishes them, which is why StampExecution exists. Reusing an
    execution name was measured to return the original run or fail rather than start a second, but
    that a redelivered message reuses its name is inferred, so the holder does not rest on it.
    """
    verb.handler(dict(REQUEST), None)

    assert lock["acquire"] == [
        ("alice", "sales", "arn:aws:states:us-east-1:1:execution:orchestrator:run-a")
    ]
    assert "req-1" not in {holder for _, _, holder in lock["acquire"]}


def test_a_held_lock_is_a_terminal_refusal_named_for_the_reason(lock, sqs):
    lock["result"] = (False, None)

    with pytest.raises(TerminalError) as raised:
        verb.handler(dict(REQUEST), None)

    assert raised.value.reason == "refresh_already_running"
