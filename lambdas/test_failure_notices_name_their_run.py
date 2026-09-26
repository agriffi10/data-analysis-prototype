"""Two runs failing alike are two notices, and one run told twice is still one.

The notifications queue deduplicates a send that carries no dedup id on the SHA-256 of its body,
within the recipient's message group, for five minutes. Archive's and file-send's failure notices
carry no dedup id, and their generic sentences name nothing about the run, so two runs by one user
failing the same way became ONE inbox row and the second was never told. Each notice now carries
its run's request id in the payload.

**Driven against a fake SQS client, never a stubbed sender.** A stub of ``emit_notification`` is
handed the arguments and hides both things the queue deduplicates on: the body the sender builds
from them and the dedup id it derives. Every case runs the real emitter and the real sender, and
the assertions read what reached ``send_message``.

**A case is one DOOR a failure reaches the user through**, per plane: the verb decorator on a
refusal and on an unexpected fault, validate-authorize's own refusal, notify-failure's ASL door
where the error replaced the state and the id survives only in the forwarded request, and its
timeout door where the id is only in the execution input — plus file-send's per-recipient refusal,
told by its producer.

Attributes:
  RUN_A: One run's request id.
  RUN_B: Another run's.
  IDENTITY: The identity block the API stamps, from which every door recovers the actor.
  CASES: Every door, each a function that sends one failure notice for a run.
"""

import hashlib
import io
import json
import pathlib
import sys

import pytest

_LAMBDAS = pathlib.Path(__file__).resolve().parent
for _dir in (
    "control-plane-common",
    "archive-common",
    "file-send-common",
    "archive-validate-authorize",
    "archive-notify-failure",
    "file-send-validate-authorize",
    "file-send-notify-failure",
    "file-send-notify",
):
    sys.path.insert(0, str(_LAMBDAS / _dir))

import ar_notify_failure
import archive_validate_authorize
import file_send_notify
import file_send_validate_authorize
import fs_notify_failure
from arcommon import notify as arnotify
from cpcommon import clients, config
from cpcommon.errors import TerminalError
from fscommon import notify as fsnotify

RUN_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
RUN_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
IDENTITY = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}


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


class _AdminBucket:
    """The admin bucket the archive's timeout door claims delete-source's verdict in.

    It starts empty, so the door claims ``stopped`` and sends its ordinary sentence, and a second
    call for the same run meets that claim — the retry this file's second test is about.
    """

    def __init__(self):
        """Starts with no verdict recorded.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.objects = {}

    def get_object(self, Bucket, Key):
        """Returns a recorded verdict.

        Args:
          Bucket: Unused.
          Key: The verdict's key.

        Returns:
          The object, with a readable body.

        Raises:
          KeyError: When nothing was recorded, which the reader treats as absent.
        """
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType, IfNoneMatch=None):
        """Records a verdict create-only.

        Args:
          Bucket: Unused.
          Key: The verdict's key.
          Body: The verdict.
          ContentType: Unused.
          IfNoneMatch: ``*`` for a create-only write.

        Returns:
          None.

        Raises:
          _PreconditionFailed: When a create-only write finds the key taken.
        """
        if IfNoneMatch == "*" and Key in self.objects:
            raise _PreconditionFailed()
        self.objects[Key] = Body


class _PreconditionFailed(Exception):
    """S3's refusal of a create-only write whose key is taken."""

    def __init__(self):
        """Carries the response shape the conditional-write classifier reads.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__("PreconditionFailed")
        self.response = {
            "Error": {"Code": "PreconditionFailed"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        }


@pytest.fixture
def sent(monkeypatch):
    """Routes the real sender to a recording client and returns what it records.

    The admin bucket is faked beside it, because the archive's timeout door claims a verdict there
    before it sends, and an unfaked client would reach real S3.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      The list each send is appended to.

    Raises:
      None.
    """
    fake = _Sqs()
    monkeypatch.setattr(clients, "_sqs", fake)
    monkeypatch.setattr(clients, "_s3", _AdminBucket())
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


def _pipe_batch(request_id: str | None, **fields) -> list:
    """Builds the Pipe's forwarded batch for a request, as every door reads it.

    Args:
      request_id: The run's id, or None for a request that carries none.
      **fields: The rest of the body.

    Returns:
      A one-record SQS batch.

    Raises:
      None.
    """
    body = {"identity": IDENTITY, **fields}
    if request_id is not None:
        body["requestId"] = request_id
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _timed_out(request_id: str | None, **fields) -> dict:
    """Builds the EventBridge event for a run the machine's own ceiling stopped.

    Args:
      request_id: The run's id, carried only inside the execution input.
      **fields: The rest of the request body.

    Returns:
      The status-change event.

    Raises:
      None.
    """
    return {
        "detail-type": "Step Functions Execution Status Change",
        "detail": {
            "executionArn": "arn:aws:states:us-east-1:000000000000:execution:m:e",
            "status": "TIMED_OUT",
            "input": json.dumps(_pipe_batch(request_id, **fields)),
        },
    }


def _engine_failure(request_id: str | None, **seed) -> dict:
    """Builds the recorded failure the pre-identity seed hands the ASL door.

    The error replaced the state, so the seed's ``requestId`` is null and the id survives only in
    the forwarded request under ``raw``, which is the harder of the two shapes to read it from.

    Args:
      request_id: The run's id, carried only under ``raw``.
      **seed: The plane's other seeded literals.

    Returns:
      The recorded failure.

    Raises:
      None.
    """
    return {
        "requestId": None,
        "actor": None,
        **seed,
        "raw": _pipe_batch(request_id),
        "status": "failed",
        "error": {"Error": "RuntimeError", "Cause": "boom"},
    }


def _raises(handler, event, expected: type[Exception], match: str) -> None:
    """Runs a handler that must fail, and swallows the failure it re-raises.

    The failure is named, so a case that broke on the way — an import, a missing fixture key — is
    not mistaken for the refusal it exists to report.

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


def _refusing(notifies_on_failure, reason: str):
    """Builds a decorated verb that refuses with one reason.

    Args:
      notifies_on_failure: The plane's decorator factory.
      reason: The refusal's reason code.

    Returns:
      The decorated verb.

    Raises:
      None.
    """

    @notifies_on_failure("inspect")
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


def _crashing(notifies_on_failure):
    """Builds a decorated verb that fails with an exception nobody predicted.

    Args:
      notifies_on_failure: The plane's decorator factory.

    Returns:
      The decorated verb.

    Raises:
      None.
    """

    @notifies_on_failure("inspect")
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


def archive_verb_refuses(request_id):
    """An archive verb's refusal, told by the decorator."""
    event = {"requestId": request_id, "mode": "archive", "actor": {"username": "alice"}}
    _raises(_refusing(arnotify.notifies_on_failure, "nothing_to_archive"), event, TerminalError, "nothing_to_archive")


def archive_verb_crashes(request_id):
    """An archive verb's unexpected fault, told by the decorator."""
    event = {"requestId": request_id, "mode": "restore", "actor": {"username": "alice"}}
    _raises(_crashing(arnotify.notifies_on_failure), event, RuntimeError, "boom")


def archive_validator_refuses(request_id):
    """validate-authorize refusing a malformed archive request, before any AWS call."""
    event = _pipe_batch(request_id, mode="archive", unexpected="field")
    _raises(
        lambda e, c: archive_validate_authorize._validate_and_authorize(e), event, TerminalError, "malformed_event"
    )


def archive_engine_failure(request_id):
    """notify-failure's ASL door, on a failure no verb reported."""
    ar_notify_failure.handler(_engine_failure(request_id, mode=None), None)


def archive_timed_out(request_id):
    """notify-failure's timeout door, for an archive the ceiling stopped."""
    ar_notify_failure.handler(_timed_out(request_id, mode="archive"), None)


def file_send_verb_refuses(request_id):
    """A file-send verb's refusal, told by the decorator."""
    event = {"requestId": request_id, "actor": {"username": "alice"}}
    _raises(_refusing(fsnotify.notifies_on_failure, "nothing_to_send"), event, TerminalError, "nothing_to_send")


def file_send_verb_crashes(request_id):
    """A file-send verb's unexpected fault, told by the decorator."""
    event = {"requestId": request_id, "actor": {"username": "alice"}}
    _raises(_crashing(fsnotify.notifies_on_failure), event, RuntimeError, "boom")


def file_send_validator_refuses(request_id):
    """validate-authorize refusing a malformed send, before any AWS call."""
    event = _pipe_batch(request_id, unexpected="field")
    _raises(
        lambda e, c: file_send_validate_authorize._validate_and_authorize(e), event, TerminalError, "malformed_event"
    )


def file_send_engine_failure(request_id):
    """notify-failure's ASL door, on a failure no verb reported."""
    fs_notify_failure.handler(_engine_failure(request_id), None)


def file_send_timed_out(request_id):
    """notify-failure's timeout door, for a send the ceiling stopped."""
    fs_notify_failure.handler(_timed_out(request_id), None)


def file_send_recipient_refused(request_id):
    """The producer telling the sender one recipient already held the file."""
    summary = {
        "sender": "alice",
        "itemNames": ["notes.txt"],
        "objectCount": 1,
        "recipients": [
            {"kind": "user", "name": "bob", "status": "refused", "reason": "conflict", "detail": "notes.txt"}
        ],
    }
    if request_id is not None:
        summary["requestId"] = request_id
    file_send_notify.handler(summary, None)


CASES = [
    archive_verb_refuses,
    archive_verb_crashes,
    archive_validator_refuses,
    archive_engine_failure,
    archive_timed_out,
    file_send_verb_refuses,
    file_send_verb_crashes,
    file_send_validator_refuses,
    file_send_engine_failure,
    file_send_timed_out,
    file_send_recipient_refused,
]


def _one_notice(sent: list, case, request_id) -> dict:
    """Runs one case and returns the one notice it sent.

    Exactly one, because a door that sends nothing would make every comparison below vacuous: two
    absent notices never collapse.

    Args:
      sent: The recording.
      case: The door.
      request_id: The run's id, or None.

    Returns:
      The send.

    Raises:
      AssertionError: When the case did not send exactly one notice.
    """
    before = len(sent)
    case(request_id)
    assert len(sent) == before + 1, f"{case.__name__} sent {len(sent) - before} notices, not one"
    return sent[-1]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_two_runs_failing_alike_are_two_notices_naming_their_runs(sent, case) -> None:
    """Two runs, one user, one reason: the queue must see two different keys.

    The bodies are also compared with the payload removed, which is what stops a case passing
    because something else in it happened to vary per run: the notices differ in the run they name
    and in nothing else.

    Args:
      sent: The recording.
      case: The door.

    Returns:
      None.

    Raises:
      AssertionError: If the two runs collapse, or differ in anything but the named run.
    """
    first = _one_notice(sent, case, RUN_A)
    second = _one_notice(sent, case, RUN_B)

    assert _key(first) != _key(second), f"{case.__name__}: two runs collapse into one notice"
    bodies = [json.loads(call["MessageBody"]) for call in (first, second)]
    assert [body.pop("payload", None) for body in bodies] == [
        {"requestId": RUN_A},
        {"requestId": RUN_B},
    ]
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_one_run_told_twice_is_one_notice(sent, case) -> None:
    """A retry of one run composes the same key, which is the retry safety content dedup gives.

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

    assert _key(first) == _key(again)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_without_a_request_id_two_runs_collapse(sent, case) -> None:
    """The positive control: with no id to name, this harness sees the collapse the queue makes.

    It is what makes the first test evidence. Each door's sentence is otherwise the same for two
    runs, and the key this file computes does find two such notices equal — so a payload that went
    missing would redden the first test rather than leave it passing on a sentence that varied.

    Args:
      sent: The recording.
      case: The door.

    Returns:
      None.

    Raises:
      AssertionError: If the door's notice varies with no request id, or carries a payload anyway.
    """
    first = _one_notice(sent, case, None)
    second = _one_notice(sent, case, None)

    assert "payload" not in json.loads(first["MessageBody"])
    assert _key(first) == _key(second)
