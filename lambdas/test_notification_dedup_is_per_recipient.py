"""A notice can only be deduplicated against another notice to the same person.

Producers key notices on ``{requestId}:{outcome}``, and a request id is chosen by whoever sent the
request. The property that makes that safe has two halves in two languages: the queue deduplicates
within a message group, and the sender makes the recipient the group. Either half alone leaves a
request that borrows somebody else's id able to drop their notice, so both are asserted here.

Attributes:
  ROOT: The repository root.
  QUEUES: The notifications module's queue definitions.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUEUES = ROOT / "infra" / "modules" / "notifications" / "sqs.tf"

sys.path.insert(0, str(ROOT / "lambdas" / "control-plane-common"))


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _requests_queue_block() -> str:
    """Returns the requests queue's resource block from the module.

    Args:
      None.

    Returns:
      The block's text, from its header to the brace that closes it.

    Raises:
      AssertionError: When the resource is not found, which would leave the assertion nothing to
        read.
    """
    text = QUEUES.read_text()
    start = text.find('resource "aws_sqs_queue" "requests" {')
    assert start >= 0, f"no requests queue in {QUEUES.name}"
    depth = 0
    for index in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[start : index + 1]
    raise AssertionError(f"the requests queue block in {QUEUES.name} never closes")


def test_the_requests_queue_deduplicates_within_a_message_group() -> None:
    """The queue's own half: deduplication scoped to the group rather than the whole queue.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the requests queue is not a FIFO queue scoped to the message group.
    """
    block = _requests_queue_block()

    assert re.search(r"fifo_queue\s*=\s*true", block), "the requests queue is not FIFO"
    assert re.search(r'deduplication_scope\s*=\s*"messageGroup"', block), (
        "the requests queue deduplicates across the whole queue, so a request carrying somebody "
        "else's id can drop their notice"
    )


def test_one_dedup_key_sent_to_two_people_goes_out_in_two_groups() -> None:
    """The sender's half: the group is the recipient, so the same key lands in different groups.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a send's group is not its recipient.
    """
    from cpcommon import clients, config, notify

    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake

    for username in ("alice", "bob"):
        notify.emit_notification(username, "a notice", dedup_id="0f8fad5b-d9cb-469f-a165-70867728950e:failure")

    assert [(call["MessageGroupId"], json.loads(call["MessageBody"])["username"]) for call in fake.calls] == [
        ("alice", "alice"),
        ("bob", "bob"),
    ]
    assert len({call["MessageDeduplicationId"] for call in fake.calls}) == 1
