"""The table-builder created notification's sentence about columns kept under a new name.

The notification is sent after the table exists, so its two properties are that the sentence stays
bounded however many columns were renamed, and that a state the derivation cannot read costs the
sentence and never the notification. Driven through ``emit_created`` with a fake queue, the one
boundary it crosses.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from cpcommon import clients, config
from tbcommon import notify


class _FakeSqs:
    """Records every message the notification would send."""

    def __init__(self):
        """Starts with nothing sent.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls = []

    def send_message(self, **kwargs):
        """Records one send.

        Args:
          **kwargs: The ``SendMessage`` arguments.

        Returns:
          A message id.

        Raises:
          None.
        """
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _sent_message(event):
    """Emits the created notification for one state and returns the text it carried.

    Args:
      event: The task input.

    Returns:
      The notification's message.

    Raises:
      AssertionError: When not exactly one notification was sent.
    """
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"
    queue = _FakeSqs()
    clients._sqs = queue
    clients._sqs_bounded = queue

    notify.emit_created(event)

    assert len(queue.calls) == 1
    return json.loads(queue.calls[0]["MessageBody"])["message"]


def _state(columns, keys):
    """A created state over CSV columns and partition keys, named as given.

    Args:
      columns: The data column names.
      keys: The partition key names.

    Returns:
      The task input.

    Raises:
      None.
    """
    return {
        "actor": "alice",
        "requestId": "r1",
        "tableName": "sales",
        "space": {"database": "alice"},
        "format": "csv",
        "columns": [{"name": name, "type": "string"} for name in columns],
        "partitionKeys": [{"name": name} for name in keys],
    }


def test_more_renames_than_the_cap_are_counted_rather_than_spelled_out():
    """Twenty-five keys each with a column of their name: twenty pairs, then the other five as a
    count, so a wide partition scheme cannot grow the notification without bound.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    keys = [f"key{index:02d}" for index in range(25)]

    message = _sent_message(_state(keys, keys))

    shown = ", ".join(f'"{key}" is "{key}_in_file"' for key in keys[:20])
    assert message == (
        'Table "sales" is ready to query in "alice". Columns named after a partition key keep '
        f"their values under new names: {shown}, and 5 more."
    )


def test_a_name_at_the_key_length_limit_is_shown_whole_with_its_new_name():
    """A partition key may be 63 characters, and clipping at 60 cut off exactly the suffix the
    user needs to find the column.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    key = "k" * 63

    message = _sent_message(_state([key.upper()], [key]))

    assert message.endswith(f'"{key.upper()}" is "{key}_in_file".')


def test_a_name_that_cannot_be_encoded_costs_the_sentence_not_the_notification():
    """A lone surrogate fails the byte cut's UTF-8 encode. The table already exists by the time
    this is sent, so the user is still told it is ready.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    message = _sent_message(_state(["\ud800"], ["\ud800"]))

    assert message == 'Table "sales" is ready to query in "alice".'
