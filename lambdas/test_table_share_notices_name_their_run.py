"""Two shares ending alike are two notices, one share told twice is one, and one run's notices stay apart.

The notifications queue deduplicates within the recipient's message group, on the dedup id when a
send carries one and on the SHA-256 of the body when it does not, for five minutes. Every
table-share notice used to carry neither an id nor a payload, and its sentence names the source,
the recipient and the result table but nothing about the run, so two shares of one table by one
user that ended alike were delivered once. Table-share has no request id; each notice now carries a
dedup id built from the execution's name — or, in validate-authorize, the SQS message id.

**Driven against a fake SQS client, never a stubbed sender**, for the reason the archive and
file-send version of this file gives: a stub hides the body the sender builds and the id it
derives, which are the two things the queue deduplicates on.

**An id replaces the body as the key, so an id can merge what the body kept apart.** That is the
half the cross-run tests cannot see, and the in-run tests below exist for it: one run's notices
that differ today — the verb decorator's crash notice and notify-failure's engine notice, two
recipients refused alike, one owner told of two spaces — must still reach the queue under two keys.

The event shapes a notifier reads the name from are pinned on the template by
``table-share-common/test_state_machine_table_share.py``, and the verbs that pass the state on in
Python — inspect-source, the manifest builder and the collector — are asserted to keep it by their own
suites; the events here are built to those paths.

Attributes:
  RUN_A: One run's execution name.
  RUN_B: Another run's.
  IDENTITY: The identity block the API stamps, from which validate-authorize and the timeout door
    recover the actor.
  FAILURE_CASES: Every door a failure notice reaches the sender through, each a function sending
    one notice for a run.
"""

import hashlib
import json
import pathlib
import sys

import pytest

_LAMBDAS = pathlib.Path(__file__).resolve().parent
for _dir in (
    "control-plane-common",
    "table-share-common",
    "table-share-validate-authorize",
    "table-share-notify-failure",
):
    sys.path.insert(0, str(_LAMBDAS / _dir))

import table_share_validate_authorize
import ts_notify_failure
from cpcommon import clients, config
from cpcommon.errors import TerminalError
from tscommon import notify as tsnotify

RUN_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
RUN_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
IDENTITY = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}
_SOURCE = {"database": "alice", "table": "sales"}


class _Sqs:
    """Records every send, as the notifications queue would receive it.

    Attributes:
      calls: The keyword arguments of each ``send_message``, in order.
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
        self.calls = []

    def send_message(self, **kwargs):
        """Keeps one send.

        Args:
          **kwargs: The send's arguments.

        Returns:
          A response carrying a message id.

        Raises:
          None.
        """
        self.calls.append(kwargs)
        return {"MessageId": "m"}


@pytest.fixture
def sent(monkeypatch):
    """Routes the real sender to a recording client and returns what it records.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      The list each send is appended to.

    Raises:
      None.
    """
    fake = _Sqs()
    monkeypatch.setattr(clients, "_sqs", fake)
    monkeypatch.setattr(
        config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/notifications.fifo", raising=False
    )
    return fake.calls


def _key(call: dict) -> tuple:
    """Returns what the queue deduplicates one send on.

    Args:
      call: One recorded send.

    Returns:
      The message group, and the explicit dedup id or else the SHA-256 of the body.

    Raises:
      None.
    """
    body_hash = hashlib.sha256(call["MessageBody"].encode()).hexdigest()
    return call["MessageGroupId"], call.get("MessageDeduplicationId") or body_hash


def _state(run: str | None) -> dict:
    """Builds the request as every verb after the stamp holds it.

    Args:
      run: The execution name the stamp wrote, or None for a state carrying none.

    Returns:
      The state.

    Raises:
      None.
    """
    state = {
        "traceparent": None,
        "actor": "alice",
        "source": dict(_SOURCE),
        "tableName": "sales_copy",
        "recipients": [{"kind": "user", "name": "bob", "valid": True}],
    }
    if run is not None:
        state["execution"] = {"name": run}
    return state


def _item(run: str | None, name: str = "bob", kind: str = "user") -> dict:
    """Builds a guard or finish Map item: the recipient beside the whole state.

    Args:
      run: The run's execution name, or None.
      name: The recipient's name.
      kind: The recipient kind.

    Returns:
      The item.

    Raises:
      None.
    """
    return {"recipient": {"kind": kind, "name": name, "database": name}, "request": _state(run)}


def _pipe_batch(message_id: str | None, **fields) -> list:
    """Builds the Pipe's forwarded batch for a share request.

    Args:
      message_id: The SQS message id, or None for a record carrying none.
      **fields: The rest of the body.

    Returns:
      A one-record SQS batch.

    Raises:
      None.
    """
    record: dict = {"body": json.dumps({"identity": IDENTITY, "source": dict(_SOURCE), **fields})}
    if message_id is not None:
        record["messageId"] = message_id
    return [record]


def _raises(handler, event, expected: type[Exception], match: str) -> None:
    """Runs a handler that must fail, and swallows the failure it re-raises.

    Args:
      handler: The handler.
      event: Its event.
      expected: The exception the handler re-raises.
      match: A pattern its message must match.

    Returns:
      None.

    Raises:
      AssertionError: When the handler did not raise that exception.
    """
    with pytest.raises(expected, match=match):
        handler(event, None)


def _refusing(reason: str):
    """Builds a table-share verb that refuses with one reason.

    Args:
      reason: The refusal's reason code.

    Returns:
      The decorated verb.

    Raises:
      None.
    """

    @tsnotify.notifies_on_failure("check")
    def verb(event, context):
        """Refuses.

        Args:
          event: Unused.
          context: Unused.

        Returns:
          Nothing; it always raises.

        Raises:
          TerminalError: Always.
        """
        raise TerminalError(reason, "refused")

    return verb


def _crashing():
    """Builds a table-share verb that fails with an exception nobody predicted.

    Args:
      None.

    Returns:
      The decorated verb.

    Raises:
      None.
    """

    @tsnotify.notifies_on_failure("inspect")
    def verb(event, context):
        """Crashes.

        Args:
          event: Unused.
          context: Unused.

        Returns:
          Nothing; it always raises.

        Raises:
          RuntimeError: Always.
        """
        raise RuntimeError("boom")

    return verb


def verb_refuses_the_request(run):
    """A whole-request verb's refusal, told by the decorator."""
    _raises(_refusing("source_empty"), _state(run), TerminalError, "source_empty")


def verb_refuses_a_recipient(run):
    """check-target-absent refusing one recipient, told by the decorator."""
    _raises(_refusing("conflict"), _item(run), TerminalError, "conflict")


def verb_crashes_on_the_request(run):
    """A whole-request verb's unexpected fault, told by the decorator."""
    _raises(_crashing(), _state(run), RuntimeError, "boom")


def verb_crashes_on_a_recipient(run):
    """create-table's unexpected fault for one recipient, told by the decorator."""
    _raises(_crashing(), _item(run), RuntimeError, "boom")


def validator_refuses(run):
    """validate-authorize refusing a result name, before any AWS call; the run is the message id."""
    event = _pipe_batch(run, tableName="not a table name", recipients=[{"kind": "user", "name": "bob"}])
    _raises(
        lambda e, c: table_share_validate_authorize._validate_and_authorize(e),
        event,
        TerminalError,
        "invalid_table_name",
    )


def validator_refuses_a_single_record(run):
    """validate-authorize refusing the same request handed one record rather than a batch of one."""
    event = _pipe_batch(run, tableName="not a table name", recipients=[{"kind": "user", "name": "bob"}])[0]
    _raises(
        lambda e, c: table_share_validate_authorize._validate_and_authorize(e),
        event,
        TerminalError,
        "invalid_table_name",
    )


def collector_reports_a_copy_failure(run):
    """collect-transfer-results telling the sender one recipient's copy failed, from the state."""
    tsnotify.emit_recipient_failure(_state(run), "user", "bob", "copy_failed")


def _recorded_failure(run: str | None) -> dict:
    """Builds RecordFailure's output for a failure no verb reported.

    Args:
      run: The execution name the terminal copied from the context object, or None.

    Returns:
      The recorded failure.

    Raises:
      None.
    """
    recorded = {
        "raw": _pipe_batch("m-1", tableName="sales_copy"),
        "traceparent": None,
        "actor": "alice",
        "source": dict(_SOURCE),
        "tableName": "sales_copy",
        "status": "failed",
        "error": {"Error": "RuntimeError", "Cause": "boom"},
    }
    if run is not None:
        recorded["execution"] = {"name": run}
    return recorded


def engine_failure(run):
    """notify-failure's ASL door, on a failure no verb reported."""
    ts_notify_failure.handler(_recorded_failure(run), None)


def timed_out(run):
    """notify-failure's timeout door, where the name is the event's own ``detail.name``."""
    detail = {
        "executionArn": f"arn:aws:states:us-east-1:000000000000:execution:m:{run}",
        "status": "TIMED_OUT",
        "input": json.dumps(_pipe_batch("m-1", tableName="sales_copy")),
    }
    if run is not None:
        detail["name"] = run
    ts_notify_failure.handler({"detail-type": "Step Functions Execution Status Change", "detail": detail}, None)


FAILURE_CASES = [
    verb_refuses_the_request,
    verb_refuses_a_recipient,
    verb_crashes_on_the_request,
    verb_crashes_on_a_recipient,
    validator_refuses,
    validator_refuses_a_single_record,
    collector_reports_a_copy_failure,
    engine_failure,
    timed_out,
]


def _one_notice(sent: list, case, run) -> dict:
    """Runs one case and returns the one notice it sent.

    Exactly one, because a door that sends nothing would make every comparison vacuous: two absent
    notices never collapse.

    Args:
      sent: The recording.
      case: The door.
      run: The run's identity, or None.

    Returns:
      The send.

    Raises:
      AssertionError: When the case did not send exactly one notice.
    """
    before = len(sent)
    case(run)
    assert len(sent) == before + 1, f"{case.__name__} sent {len(sent) - before} notices, not one"
    return sent[-1]


@pytest.mark.parametrize("case", FAILURE_CASES, ids=lambda case: case.__name__)
def test_two_runs_failing_alike_are_two_notices_naming_their_runs(sent, case) -> None:
    """Two runs, one user, one reason: the queue must see two different keys.

    The bodies are asserted identical, which is what makes the differing keys evidence: nothing but
    the id keeps the two notices apart.

    Args:
      sent: The recording.
      case: The door.

    Returns:
      None.

    Raises:
      AssertionError: If the two runs collapse, or differ in anything but the id.
    """
    first = _one_notice(sent, case, RUN_A)
    second = _one_notice(sent, case, RUN_B)

    assert _key(first) != _key(second), f"{case.__name__}: two runs collapse into one notice"
    assert first["MessageBody"] == second["MessageBody"]
    assert "payload" not in json.loads(first["MessageBody"])


@pytest.mark.parametrize("case", FAILURE_CASES, ids=lambda case: case.__name__)
def test_one_run_told_twice_is_one_notice(sent, case) -> None:
    """A retry of one run composes the same key, which is the retry safety content dedup gave.

    Args:
      sent: The recording.
      case: The door.

    Returns:
      None.

    Raises:
      AssertionError: If a re-invocation of one run would reach the user twice.
    """
    first = _one_notice(sent, case, RUN_A)
    again = _one_notice(sent, case, RUN_A)

    assert first.get("MessageDeduplicationId"), f"{case.__name__} sent no dedup id"
    assert _key(first) == _key(again)


@pytest.mark.parametrize("case", FAILURE_CASES, ids=lambda case: case.__name__)
def test_without_a_run_name_two_runs_collapse(sent, case) -> None:
    """The positive control: with no name to read, this harness sees the collapse the queue makes.

    It is what makes the first test evidence. Each door's sentence is otherwise the same for two
    runs, so a name that stopped reaching a notifier reddens the first test rather than leaving it
    passing on a sentence that happened to vary.

    Args:
      sent: The recording.
      case: The door.

    Returns:
      None.

    Raises:
      AssertionError: If the door's notice varies with no run name, or carries an id anyway.
    """
    first = _one_notice(sent, case, None)
    second = _one_notice(sent, case, None)

    assert "MessageDeduplicationId" not in first
    assert _key(first) == _key(second)


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        (verb_crashes_on_the_request, engine_failure),
        (verb_refuses_a_recipient, timed_out),
    ],
    ids=["a verb crash and the engine notice", "a recipient refusal and the timeout notice"],
)
def test_one_run_told_of_two_failures_in_two_ways_keeps_both_notices(sent, earlier, later) -> None:
    """Two whole-request failure notices one run sends on purpose are not merged by their ids.

    A verb's unexpected fault is told by its decorator as ``unexpected_error`` and again by
    notify-failure under the engine's error name, in a shorter sentence; a run whose guard refused
    one recipient carries on and can then time out. Content dedup kept each pair apart because the
    sentences differ, and an id of ``failure`` alone would merge the first, since the queue then
    ignores the body.

    Args:
      sent: The recording.
      earlier: The door told first.
      later: The door told second, in the same run.

    Returns:
      None.

    Raises:
      AssertionError: If the two notices share a key.
    """
    first = _one_notice(sent, earlier, RUN_A)
    second = _one_notice(sent, later, RUN_A)

    assert first["MessageBody"] != second["MessageBody"]
    assert first.get("MessageDeduplicationId") and second.get("MessageDeduplicationId")
    assert _key(first) != _key(second)


def test_one_run_refusing_two_recipients_alike_keeps_both_notices(sent) -> None:
    """Per-recipient failure ids name the recipient, so two refusals and two copy failures stay four.

    Both notices of each pair reach the sender's group in one run, which is the only arrangement in
    which their ids can meet.

    Args:
      sent: The recording.

    Returns:
      None.

    Raises:
      AssertionError: If one run's notices about two recipients collapse.
    """
    for name in ("bob", "carol"):
        _raises(_refusing("conflict"), _item(RUN_A, name=name), TerminalError, "conflict")
    for name in ("bob", "carol"):
        tsnotify.emit_recipient_failure(_state(RUN_A), "user", name, "copy_failed")

    assert len(sent) == 4
    assert {call["MessageGroupId"] for call in sent} == {"alice"}
    assert len({_key(call) for call in sent}) == 4


def test_every_success_notice_names_its_run_side_and_recipient(sent, monkeypatch) -> None:
    """A re-share delivered alike is told again to everyone, a retry to no one, and nothing merges in a run.

    ``bob`` is a user recipient and the owner of two space recipients, so his three notices share a
    message group and meet on their ids; ``alice`` owns a third space, so her ``sent`` and
    ``received`` notices about it meet in hers. The bodies are identical across the two runs, which
    is what makes the differing keys evidence.

    Args:
      sent: The recording.
      monkeypatch: The pytest fixture.

    Returns:
      None.

    Raises:
      AssertionError: If two runs collapse, a retry is told twice, or one run's notices merge.
    """
    owners = {"finance": "bob", "ops": "bob", "data": "alice"}
    monkeypatch.setattr(tsnotify.reg, "load", lambda name: {"owner": owners[name]})
    recipients = [("user", "bob"), ("space", "finance"), ("space", "ops"), ("space", "data")]

    runs = []
    for run in (RUN_A, RUN_B, RUN_A, None, None):
        before = len(sent)
        for kind, name in recipients:
            tsnotify.emit_recipient_success(_item(run, name=name, kind=kind))
        runs.append(sent[before:])
    first, second, _retry, unnamed, _unnamed_again = runs
    keys = [[_key(call) for call in run] for run in runs]

    assert [call["MessageGroupId"] for call in first] == ["alice", "bob", "alice", "bob", "alice", "bob", "alice", "alice"]
    assert [c["MessageBody"] for c in first] == [c["MessageBody"] for c in second]
    assert all(call.get("MessageDeduplicationId") for call in first), "a success went out with no dedup id"
    assert len(set(keys[0])) == len(keys[0]), "one run's notices collapse into each other"
    assert not set(keys[0]) & set(keys[1]), "two runs' notices collapse"
    assert keys[2] == keys[0], "a retry of one run is told twice"
    assert keys[3] == keys[4], "with no run name the harness no longer sees the queue's collapse"
    assert not any("MessageDeduplicationId" in call for call in unnamed)
