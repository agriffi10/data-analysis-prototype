"""The notification sender's deduplication id: a key the queue accepts is sent, one it refuses is digested.

Only the SQS send is faked, and the fake refuses a key the way SQS does instead of recording
whatever it is handed. A recording fake cannot tell a delivered notification from a lost one:
the sender swallows the refusal, so the only evidence of the defect is a send that never happens.
The fake writes the queue's rule out for itself rather than borrowing the module's pattern, so a
change to that pattern cannot move the fake along with it.
"""

import hashlib

import pytest
from cpcommon import clients, config, notify

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
