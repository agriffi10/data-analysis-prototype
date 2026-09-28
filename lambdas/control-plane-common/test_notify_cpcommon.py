"""The notification sender: its deduplication id, and how long it waits for a send.

A key the queue accepts is sent, one it refuses is digested. Only the SQS send is faked, and the
fake refuses a key the way SQS does instead of recording whatever it is handed. A recording fake
cannot tell a delivered notification from a lost one: the sender swallows the refusal, so the only
evidence of the defect is a send that never happens. The fake writes the queue's rule out for
itself rather than borrowing the module's pattern, so a change to that pattern cannot move the fake
along with it.

A send is waited for no longer than the budget's cap. Each of those tests asserts the MESSAGE of
the ``TimeoutError`` the sender logged, because the cap and the deadline raise the same type and a
test reading only the type passes with either one removed.
"""

import hashlib
import itertools
import threading
import time
import types

import pytest
from cpcommon import budget, clients, config, notify

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/1/dat-prod-notifications-requests.fifo"


class _Sqs:
    """Records each accepted send, refusing a deduplication id SQS would refuse."""

    def __init__(self):
        """Starts with nothing sent.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.sent = []

    def send_message(self, **kwargs):
        """Accepts a send whose deduplication id is one to 128 printable ASCII characters.

        Args:
          **kwargs: The send's parameters.

        Returns:
          A send response.

        Raises:
          ValueError: If the deduplication id is one SQS refuses.
        """
        key = kwargs.get("MessageDeduplicationId")
        if key is not None and not (1 <= len(key) <= 128 and all("!" <= c <= "~" for c in key)):
            raise ValueError("InvalidParameterValue: MessageDeduplicationId")
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}


@pytest.fixture
def sqs(monkeypatch):
    """Points the sender at the refusing fake and a configured queue.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      The fake.

    Raises:
      None.
    """
    fake = _Sqs()
    monkeypatch.setattr(clients, "_sqs", fake)
    monkeypatch.setattr(clients, "_sqs_bounded", fake)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", QUEUE_URL)
    return fake


@pytest.mark.parametrize(
    "key",
    ["r" * 121 + ":failure", "r 1:failure", "r\x7f1:failure", "r-1:failure\n", "r-\ud800:failure"],
    ids=["one-past-the-limit", "a-space", "a-delete", "a-final-newline", "a-lone-surrogate"],
)
def test_a_key_the_queue_would_refuse_still_sends_under_its_digest(sqs, key):
    """The first row is 129 characters, which a 121-character id and a plane's step already reach.

    The space and delete rows sit one past each end of the class. The newline row is the one ``$``
    would admit, and the surrogate row is the one strict UTF-8 would raise on before the send.
    """
    notify.emit_notification("alice", "Your request couldn't be started.", dedup_id=key)

    assert [s["MessageGroupId"] for s in sqs.sent] == ["alice"]
    assert sqs.sent[0]["MessageDeduplicationId"] == hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()


def test_a_key_the_queue_accepts_is_sent_unchanged_up_to_its_limit(sqs):
    """128 characters spanning both ends of the class, so narrowing either bound digests it."""
    key = "!" + "r" * 126 + "~"

    notify.emit_notification("alice", "Your request couldn't be started.", dedup_id=key)

    assert sqs.sent[0]["MessageDeduplicationId"] == key


class _Refusing:
    """A client no send may reach: it records what was asked of it and refuses it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"a send reached the wrong client ({name})")


class _Slow:
    """A queue that answers every send, but only after longer than the cap."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.sent_on = []

    def send_message(self, **kwargs):
        time.sleep(self.seconds)
        self.sent_on.append(threading.current_thread())
        return {"MessageId": "m-1"}


def test_a_send_that_never_answers_is_abandoned_at_the_cap(stalled_sends, caplog):
    """A stall raises nothing for the sender's swallow to catch, so only the cap ends the wait."""
    started = time.perf_counter()

    notify.emit_notification("alice", "Your check completed.", dedup_id="r-1:completed")

    assert time.perf_counter() - started < 1
    assert stalled_sends.started == 1
    assert stalled_sends.reasons(caplog.records) == ["a notification: a call ran past 0.05s"]


def test_a_shared_budget_starts_no_send_once_its_deadline_has_passed(monkeypatch, sqs, caplog):
    """The budget a loop passes is the one read: a send given its own would start after it."""
    readings = itertools.chain([0], itertools.count(notify.SEND_DEADLINE_SECONDS + 1))
    monkeypatch.setattr(budget, "time", types.SimpleNamespace(monotonic=lambda: next(readings)))
    sends = notify.send_budget()

    notify.emit_notification("bob", "You were removed.", dedup_id="r-1:remove:bob", budget=sends)

    assert sqs.sent == []
    assert [str(r.exc_info[1]) for r in caplog.records if r.exc_info] == ["notifications ran out of time"]


def test_the_bounded_client_is_built_on_the_callers_thread_and_is_the_only_one_used(monkeypatch, sqs):
    """Only the send goes to the worker: a cold container building the client there would spend
    the cap importing boto3, and two abandoned workers could build from the default session at once.
    """
    built_on = []

    def _build():
        built_on.append(threading.current_thread())
        return sqs

    monkeypatch.setattr(clients, "sqs_bounded", _build)
    monkeypatch.setattr(clients, "_sqs", _Refusing())

    notify.emit_notification("alice", "Your check completed.", dedup_id="r-1:completed")

    assert built_on == [threading.current_thread()]
    assert [s["MessageGroupId"] for s in sqs.sent] == ["alice"]


def test_an_unbounded_send_is_waited_for_on_the_default_client(monkeypatch, caplog):
    """The drain's send is its whole job, so a slow one is waited for rather than abandoned.

    The bounded slot keeps the suite's refusing stand-in, which fails this test at teardown if the
    send is made there.
    """
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", QUEUE_URL)
    slow = _Slow(0.2)
    monkeypatch.setattr(clients, "_sqs", slow)

    notify.emit_notification("alice", "Your request couldn't be started.", dedup_id="dlq:r-1", bounded=False)

    assert slow.sent_on == [threading.current_thread()]
    assert [r for r in caplog.records if r.exc_info] == []

