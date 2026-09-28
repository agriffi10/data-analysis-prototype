"""Table share's success notices: the owner lookup a space recipient needs is capped in time.

create-table tells the sender first and looks the space's owner up after, so a lookup that stalled
held the verb to its timeout and recorded a table that had been shared as a failed recipient.
"""

import threading
import time

from cpcommon import budget, clients, config
from tscommon import notify


class _Queue:
    """Records every send, as the notifications queue would receive it."""

    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def test_a_stalled_owner_lookup_costs_the_owners_notice_and_not_the_verb(monkeypatch, caplog):
    """The lookup reads on the bounded client under a budget labelled for it, and is abandoned at
    the cap, after the sender's notice and in place of the owner's."""
    queue = _Queue()
    monkeypatch.setattr(clients, "_sqs", queue)
    monkeypatch.setattr(clients, "_sqs_bounded", queue)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/n.fifo", raising=False)
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    bounded_s3 = object()
    monkeypatch.setattr(clients, "_s3_bounded", bounded_s3)
    released = threading.Event()
    read_with = []

    def _stalled_load(name, client=None):
        read_with.append(client)
        released.wait(5)
        return {"owner": "bob"}

    monkeypatch.setattr(notify.reg, "load", _stalled_load)
    event = {
        "request": {
            "actor": "alice",
            "source": {"table": "orders"},
            "tableName": "orders_copy",
            "execution": {"name": "exec-1"},
        },
        "recipient": {"kind": "space", "name": "finance"},
    }
    started = time.perf_counter()
    try:
        notify.emit_recipient_success(event)
        held = time.perf_counter() - started
    finally:
        released.set()

    lookup = [r for r in caplog.records if "owner lookup failed" in r.getMessage()]
    assert [c["MessageGroupId"] for c in queue.calls] == ["alice"]
    assert read_with == [bounded_s3]
    assert [str(r.exc_info[1]) for r in lookup] == ["the owner lookup for finance: a call ran past 0.05s"]
    assert held < 1
