"""The logs queue's message group is the event, never the service or the trace.

A FIFO group yields ten messages per receive-write-delete cycle, so the grouping IS the sweep's
ceiling: grouped by service, one working session's API traffic outran it for hours. The guard
drives the production ``init`` and a traced handler through the real library, and reads the group
ids off the wire — the property lives in what SQS receives, and an event the library assembled is
the only kind that can show a renamed id field collapsing the fleet into one fallback group.
"""

import json

from cpcommon import observability


class _RecordingSQS:
    """An SQS client that accepts every batch and keeps each entry as SQS would receive it.

    Attributes:
      entries: Every ``SendMessageBatch`` entry, in send order.
    """

    def __init__(self):
        """Starts with nothing sent.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.entries = []

    def send_message_batch(self, QueueUrl, Entries):
        """Keeps one batch and reports every entry delivered.

        Args:
          QueueUrl: The queue, unused.
          Entries: The batch entries.

        Returns:
          A response naming every entry successful.

        Raises:
          None.
        """
        self.entries.extend(Entries)
        return {"Successful": [{"Id": entry["Id"]} for entry in Entries], "Failed": []}


def test_every_event_of_one_run_travels_in_a_group_of_its_own(monkeypatch, captured_events):
    """One service, one trace, and still one group per event, each named by that event's id.

    Every event here shares the service AND the trace, so this reddens under either coarser
    grouping — the service's, which saturated the sweep, and the library's per-trace default,
    which would leave a large run, or the sweep's own, as one ten-a-cycle group. Reading the id
    out of the body the library built, rather than one this test wrote, is what catches the id
    field being renamed: the sink would then fall back to one constant group for the fleet.
    ``captured_events`` is requested for its teardown, which re-points delivery away from the
    sink ``init`` installs here.
    """
    sent = _RecordingSQS()
    monkeypatch.setattr(
        observability, "LOGS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/dat-test-logs.fifo"
    )
    monkeypatch.setattr(observability, "_initialized", False)
    monkeypatch.setattr(observability.clients, "sqs", lambda: sent)

    @observability.traced("probe-verb")
    def handler(event, context=None):
        """Emits two narrative events inside the run's span.

        Args:
          event: Unused.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        observability.info("first thing")
        observability.info("second thing")

    observability.init(service="api")
    handler({})

    bodies = [json.loads(entry["MessageBody"]) for entry in sent.entries]
    assert len(bodies) >= 3, "the run's span and both narrative events should reach the queue"
    assert {body["service"] for body in bodies} == {"api"}
    assert len({body["trace_id"] for body in bodies}) == 1
    groups = [entry["MessageGroupId"] for entry in sent.entries]
    assert groups == [body["log_id"] for body in bodies]
    assert len(set(groups)) == len(groups)
