"""notify-failure: the archive plane's notification of last resort (SPEC-152).

It exists for the failures no verb can catch — a cold-start import error, a task that could
not be invoked — where the decorator never ran and the actor would otherwise be told nothing
at all.
"""

import io
import json
import logging
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in ("control-plane-common", "archive-common"):
    sys.path.insert(0, os.path.join(_HERE, "..", _p))

import ar_notify_failure as verb
from arcommon import notify
from cpcommon import clients
from token_shapes import JWT_SHAPED

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"

_DECISION = f"archive/{UUID}/source-decision.json"


class _S3Error(Exception):
    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _AdminBucket:
    """The admin bucket, holding whatever verdict delete-source recorded; ``fault`` fails every call.

    A missing key is a 403, as it is for a role that holds GetObject without ListBucket.
    """

    def __init__(self):
        self.objects = {}
        self.fault = None

    def get_object(self, Bucket, Key):
        if self.fault is not None:
            raise self.fault
        if Key not in self.objects:
            raise _S3Error("AccessDenied", 403)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType, IfNoneMatch=None):
        if self.fault is not None:
            raise self.fault
        if IfNoneMatch == "*" and Key in self.objects:
            raise _S3Error("PreconditionFailed", 412)
        self.objects[Key] = Body


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    return out


@pytest.fixture(autouse=True)
def admin(monkeypatch):
    bucket = _AdminBucket()
    monkeypatch.setattr(clients, "_s3", bucket)
    return bucket


def _verdict(decision):
    return json.dumps({"decision": decision, "changed": 0, "execution": "e"}).encode()


_JWT = JWT_SHAPED


def _raw(actor="alice", identity=True):
    body = {
        "requestId": UUID, "mode": "archive", "actor": _JWT,
        "source": {"space": {"kind": "personal", "name": "alice"}, "items": []},
    }
    if identity:
        body["identity"] = {"actor": actor, "delegated_by": None, "assurance": "interactive"}
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _failed(**overrides):
    request = {"requestId": UUID, "actor": None, "raw": _raw(), "status": "failed",
               "error": {"Error": "States.Timeout", "Cause": None}}
    request.update(overrides)
    return request


# ── The ordinary case: the actor comes from the REQUEST BODY ─────────────────


def test_the_actor_is_recovered_from_the_identity_block_in_the_raw_request(monkeypatch, sent):
    """THE PROPERTY THAT MAKES THIS STATE MORE THAN DECORATIVE. Every failure it exists for
    happens before a verb produced an actor, so the recorded object carries actor: null every
    time. Without this the notifier takes its no-recipient branch on EVERY failure, and
    SPEC-152's guarantee reads as satisfied while telling nobody anything."""
    verb.handler(_failed(), None)

    assert [user for user, _ in sent] == ["alice"]


# ── No verified actor is a logged no-op, never a guess ───────────────────────


def test_a_failure_with_no_recoverable_actor_notifies_nobody(monkeypatch, sent):
    """The body's own actor field is attacker-controlled, and notifying it would let anyone
    deliver text to any inbox."""
    verb.handler(_failed(raw=None), None)

    assert sent == []


def test_a_request_with_no_identity_block_degrades_rather_than_raising(monkeypatch, sent):
    """The pre-cutover envelope: a flat ``actor`` holding a raw token, and no block.

    It must not raise. A raise here is an async Lambda failure EventBridge retries, so one
    unattributable event becomes three — and it must not fall back to the flat field either,
    which would address a notification to a 900-character string.
    """
    verb.handler(_failed(raw=_raw(identity=False)), None)

    assert sent == []


def test_a_reused_request_id_a_verb_raised_is_told_to_nobody_here_either(sent, caplog):
    """The verb's decorator keeps this reason quiet because the run holding the id reports, and
    this state is the other half of that silence: it drops every ``TerminalError`` as already
    handled. Were it to let this one through, the user would read that something went wrong
    beside the first run's "Archived".

    The engine failure after it is the positive control: the same recovered actor IS told.
    """
    reused = {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorType": "TerminalError", "errorMessage": "request_id_reused: prefix occupied"}
        ),
    }

    with caplog.at_level(logging.INFO):
        verb.handler(_failed(error=reused), None)
    silent = list(sent)
    verb.handler(_failed(), None)

    assert silent == []
    assert "request_id_reused is told to nobody" in caplog.text
    assert [user for user, _ in sent] == ["alice"]


# ── The second door: a run the machine's own ceiling stopped (SPEC-169) ──────


def _timed_out(included=True, input_body=None, arn="arn:aws:states:us-east-1:1:execution:m:e"):
    detail = {"executionArn": arn, "status": "TIMED_OUT"}
    if included:
        detail["input"] = json.dumps(input_body if input_body is not None else _raw())
    else:
        detail["inputDetails"] = {"included": False}
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_a_timed_out_execution_notifies_the_actor_from_the_block_in_its_input(monkeypatch, sent):
    """AWS catchers cover Task, Parallel and Map states but NOT a top-level execution failure:
    the ceiling terminates the run outright, so no state runs, the ASL door is never invoked and
    the actor would be told nothing at all — after waiting three hours."""
    verb.handler(_timed_out(), None)

    assert [user for user, _ in sent] == ["alice"]
    assert "ran for too long" in sent[0][1]


def test_a_timed_out_execution_with_an_unhashable_mode_still_notifies(monkeypatch, sent):
    """The mode picks the WORDING and nothing else, so a bad one must cost the wording, not the
    message. Only THIS door reads it off the untrusted body — the ASL door reads the mode the
    machine recorded — and it HASHES on the way into the membership test, so before the type check
    a list raised TypeError out of a reader documented as raising nothing, inside the notifier of
    last resort, three hours into a restore the user is now told nothing about."""
    body = json.loads(_raw()[0]["body"])
    body["mode"] = ["restore"]

    verb.handler(_timed_out(input_body=[{"messageId": "m-1", "body": json.dumps(body)}]), None)

    assert [user for user, _ in sent] == ["alice"]
    assert "ran for too long" in sent[0][1]


# ── What a timed-out archive may promise depends on delete-source's recorded verdict ────────


@pytest.mark.parametrize(
    "state", ["a verdict to delete", "an unreadable verdict", "a verdict to delete, id in capitals"]
)
def test_a_timeout_that_may_have_deleted_does_not_say_nothing_was_deleted(admin, sent, state):
    """The ceiling can land while delete-source runs, or while the receipt is written after it —
    originals partly or wholly gone, no receipt, and a message saying nothing was deleted. A
    verdict that cannot be read is told the same way, because only that sentence is true either
    way. The id in the input is the browser's own, and delete-source keys its verdict on the id
    validate-authorize lowercased — reading the raw spelling would find nothing and promise."""
    body = json.loads(_raw()[0]["body"])
    if state == "an unreadable verdict":
        admin.fault = _S3Error("SlowDown", 503)
    else:
        admin.objects[_DECISION] = _verdict("delete")
    if state.endswith("capitals"):
        body["requestId"] = UUID.upper()

    verb.handler(_timed_out(input_body=[{"messageId": "m-1", "body": json.dumps(body)}]), None)

    assert [user for user, _ in sent] == ["alice"]
    assert "Nothing was deleted" not in sent[0][1]
    assert "may already be archived" in sent[0][1]
    assert f"Your archive id is {UUID}" in sent[0][1]


@pytest.mark.parametrize("earlier", [None, "refuse", "unconfirmed"])
def test_a_timeout_before_any_deletion_claims_the_verdict_that_keeps_its_promise(
    admin, sent, earlier
):
    """A delete-source invocation outlives the ceiling by up to its own timeout, so a verdict
    merely READ as absent could still be written as "delete" a minute later. The door claims it
    create-only instead, and a late delete-source meets "stopped" and deletes nothing. A refusal
    recorded first is left alone: it deletes no original either."""
    if earlier:
        admin.objects[_DECISION] = _verdict(earlier)

    verb.handler(_timed_out(), None)

    assert "Nothing was deleted and your files are exactly where they were" in sent[0][1]
    assert json.loads(admin.objects[_DECISION])["decision"] == (earlier or "stopped")


def test_a_timeout_nobody_can_be_told_about_still_stops_a_late_deletion(admin, sent):
    """The claim guards the originals, not the message, so a run with no verified actor takes
    it too."""
    verb.handler(_timed_out(input_body=_raw(identity=False)), None)

    assert sent == []
    assert json.loads(admin.objects[_DECISION])["decision"] == "stopped"


def test_a_timed_out_restore_claims_no_deletion_verdict(admin, sent):
    """A restore deletes no original, and its request id names no delete-source verdict."""
    body = json.loads(_raw()[0]["body"])
    body["mode"] = "restore"

    verb.handler(_timed_out(input_body=[{"messageId": "m-1", "body": json.dumps(body)}]), None)

    assert admin.objects == {}
    assert "that restore ran for too long" in sent[0][1]
