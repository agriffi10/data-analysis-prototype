"""notify-failure: the archive plane's notification of last resort (SPEC-152).

It exists for the failures no verb can catch — a cold-start import error, a task that could
not be invoked — where the decorator never ran and the actor would otherwise be told nothing
at all.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in ("control-plane-common", "archive-common"):
    sys.path.insert(0, os.path.join(_HERE, "..", _p))

import ar_notify_failure as verb
from arcommon import notify
from cpcommon import auth

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    return out


def _raw(actor_token="eyJ-token"):
    return [{"messageId": "m-1", "body": json.dumps({
        "requestId": UUID, "mode": "archive", "actor": actor_token,
        "source": {"space": {"kind": "personal", "name": "alice"}, "items": []},
    })}]


def _raw_restore(actor_token="eyJ-token"):
    """A RESTORE request body, for the timeout door's wording. See the tests at the foot of this
    file: SPEC-171's retrieval wait is what makes a timed-out restore reachable at all."""
    return [{"messageId": "m-1", "body": json.dumps({
        "requestId": UUID, "mode": "restore", "actor": actor_token,
        "space": {"kind": "personal", "name": "alice"},
        "archiveId": "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c",
    })}]


def _failed(**overrides):
    request = {"requestId": UUID, "actor": None, "raw": _raw(), "status": "failed",
               "error": {"Error": "States.Timeout", "Cause": None}}
    request.update(overrides)
    return request


# ── The ordinary case: the actor comes from the REQUEST BODY ─────────────────


def test_the_actor_is_recovered_from_the_verified_token_in_the_raw_request(monkeypatch, sent):
    """THE PROPERTY THAT MAKES THIS STATE MORE THAN DECORATIVE. Every failure it exists for
    happens before a verb produced an actor, so the recorded object carries actor: null every
    time. Without this the notifier takes its no-recipient branch on EVERY failure, and
    SPEC-152's guarantee reads as satisfied while telling nobody anything."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "alice")

    verb.handler(_failed(), None)

    assert [user for user, _ in sent] == ["alice"]


def test_expiry_is_deliberately_not_enforced(monkeypatch, sent):
    """A failure surfaces long after the token was minted, and this path GRANTS nothing — it
    only addresses a message. Asserted by which entry point is called."""
    calls = []
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: calls.append("lenient") or "alice")
    monkeypatch.setattr(auth, "verified_username", lambda actor, **kw: pytest.fail("expiry enforced"))

    verb.handler(_failed(), None)

    assert calls == ["lenient"]


def test_an_actor_already_on_the_state_is_used_without_re_verifying(monkeypatch, sent):
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: pytest.fail("re-verified"))

    verb.handler(_failed(actor={"username": "bob"}), None)

    assert [user for user, _ in sent] == ["bob"]


def test_the_message_is_composed_from_the_reason_never_from_raw_engine_text(monkeypatch, sent):
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "alice")

    verb.handler(_failed(error={"Error": "Lambda.Unknown", "Cause": "RequestId: abc Process exited"}), None)

    assert "RequestId" not in sent[0][1]
    assert sent[0][1].startswith("Couldn't archive that: ")


# ── Suppression is by ONE NAME, never by a heuristic ─────────────────────────


def test_a_verbs_own_terminal_error_is_not_notified_twice(monkeypatch, sent):
    """The decorator already fired on the way out. TerminalError is the only error treated as
    already-reported, because it is the only POSITIVE evidence."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "alice")

    verb.handler(_failed(error={"Error": "TerminalError", "Cause": json.dumps(
        {"errorType": "TerminalError", "errorMessage": "reserved_folder: x"})}), None)

    assert sent == []


def test_a_bare_runtime_error_from_an_import_IS_notified(monkeypatch, sent):
    """The tempting heuristic — a dotted error name means the engine, a bare one means a
    handler ran — is wrong in the dangerous direction, and this fleet has the outage to prove
    it: a config module raising a bare RuntimeError at import is PR #196's own shape, and that
    rule would have silenced exactly the class of failure this function exists to report."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "alice")

    verb.handler(_failed(error={"Error": "RuntimeError", "Cause": "required environment variable"}), None)

    assert [user for user, _ in sent] == ["alice"]


# ── No verified actor is a logged no-op, never a guess ───────────────────────


def test_a_failure_with_no_recoverable_actor_notifies_nobody(monkeypatch, sent):
    """The body's own actor field is attacker-controlled, and notifying it would let anyone
    deliver text to any inbox."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "")

    verb.handler(_failed(raw=None), None)

    assert sent == []


def test_an_unrecoverable_token_degrades_to_a_no_op_rather_than_raising(monkeypatch, sent):
    def boom(actor, **kw):
        raise ValueError("bad signature")

    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", boom)

    assert verb.handler(_failed(), None)["requestId"] == UUID
    assert sent == []


def test_a_non_dict_event_does_not_crash(sent):
    """The execution has already failed; a crash here would replace a friendly notification
    with nothing."""
    assert verb.handler("not an event", None) == {}


# ── The second door: a run the machine's own ceiling stopped (SPEC-169) ──────


class _FakeSfn:
    """Step Functions, for the input read-back the timeout door falls back to.

    Only the succeeding shape is needed here: the read-back's own failure modes are
    ``cpcommon.events.timed_out_execution_input``'s and are tested there.
    """

    def __init__(self, described=None):
        self._described = described
        self.calls = []

    def describe_execution(self, executionArn):
        self.calls.append(executionArn)
        return self._described or {}


def _timed_out(included=True, input_body=None, arn="arn:aws:states:us-east-1:1:execution:m:e"):
    detail = {"executionArn": arn, "status": "TIMED_OUT"}
    if included:
        detail["input"] = json.dumps(input_body if input_body is not None else _raw())
    else:
        detail["inputDetails"] = {"included": False}
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_a_timed_out_execution_notifies_the_actor_from_the_token_in_its_input(monkeypatch, sent):
    """AWS catchers cover Task, Parallel and Map states but NOT a top-level execution failure:
    the ceiling terminates the run outright, so no state runs, the ASL door is never invoked and
    the actor would be told nothing at all — after waiting three hours."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_timed_out(), None)

    assert [user for user, _ in sent] == ["alice"]
    assert "ran for too long" in sent[0][1]


def test_the_timeout_message_promises_the_source_and_nothing_about_the_vault(monkeypatch, sent):
    """What a timeout can leave behind decides what the message may say. The source deletion sits
    DOWNSTREAM of the commit gate, so a timed-out archive has never deleted anything — whatever
    else it did — and the user's files are exactly where they were."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_timed_out(), None)

    assert "nothing was deleted" in sent[0][1].lower()


def test_a_timed_out_RESTORE_is_worded_as_a_restore_and_promises_the_right_thing(monkeypatch, sent):
    """FOUND IN REVIEW. The second door is the ONE path where the mode cannot come off the state —
    a top-level timeout terminates the execution outright — so it reads it back out of the same raw
    body the actor comes from.

    **SPEC-171 is what makes this reachable**: nothing on the restore arm waits today, and that
    spec adds a 3-5 hour retrieval, which makes the timeout predominantly a RESTORE event. Left
    alone, the user would have read "Couldn't archive that: ... Nothing was deleted and your files
    are exactly where they were" — the wrong operation, and a promise about a deletion that says
    nothing true about a restore.
    """
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_timed_out(input_body=_raw_restore()), None)

    text = sent[0][1]
    assert text.startswith("Couldn't restore that: ")
    assert "nothing was changed in your space" in text.lower()
    assert "deleted" not in text.lower()


def test_a_timed_out_archive_is_still_worded_as_an_archive(monkeypatch, sent):
    """The control for the test above: reading the mode must not have made every timeout a
    restore, and the archive sentence's deletion promise is load-bearing."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_timed_out(), None)

    assert sent[0][1].startswith("Couldn't archive that: ")


def test_an_unrecoverable_mode_falls_back_to_the_archive_wording(monkeypatch, sent):
    """A dropped or unparseable input degrades to the archive sentence rather than to no message —
    the same direction every other fallback on this door takes."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_timed_out(input_body=[{"messageId": "m-1", "body": "{not json"}]), None)

    assert not sent or sent[0][1].startswith("Couldn't archive that: ")


def test_the_input_is_read_back_when_eventbridge_dropped_it(monkeypatch, sent):
    """**The ordinary case for the archives most likely to time out**, not belt and braces.
    EventBridge caps an event at 256 KB and Step Functions drops the input rather than exceed it;
    this plane's execution input is the Pipe's record, which ARCHIVE_MAX_ITEM_BYTES deliberately
    allows to approach 200 KB. So the biggest selections — the ones that run for three hours —
    are exactly the ones the event alone cannot attribute.

    The read-back ITSELF is cpcommon's and is tested there; what this asserts is that THIS door
    is wired to it and attributes the actor it recovers."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")
    fake = _FakeSfn(described={"input": json.dumps(_raw())})
    monkeypatch.setattr(verb.events.clients, "sfn", lambda: fake)

    verb.handler(_timed_out(included=False), None)

    assert fake.calls == ["arn:aws:states:us-east-1:1:execution:m:e"]
    assert [user for user, _ in sent] == ["alice"]


@pytest.mark.parametrize(
    "event",
    [
        {"detail-type": "Step Functions Execution Status Change", "detail": "not-an-object"},
        {"detail-type": "Step Functions Execution Status Change", "detail": {}},
    ],
    ids=["detail-of-the-wrong-type", "no-execution-arn"],
)
def test_a_malformed_timeout_event_notifies_nobody_and_does_not_raise(event, sent):
    outcome = verb.handler(event, None)

    assert sent == []
    assert outcome["error"]["Error"] == "States.Timeout"


def test_an_unparseable_input_notifies_nobody(monkeypatch, sent):
    detail = _timed_out()
    detail["detail"]["input"] = "{not json"

    outcome = verb.handler(detail, None)

    assert sent == []
    assert outcome["actor"]["username"] == ""


def test_the_asl_door_is_untouched_by_the_second_one(monkeypatch, sent):
    """The two doors cannot double-notify: the ASL door is reached only through a Catch, which a
    timeout never fires, and the rule matches TIMED_OUT only, never FAILED. This asserts the
    dispatch does not swallow an ordinary failed request that happens to carry a `detail` field."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice")

    verb.handler(_failed(detail={"status": "TIMED_OUT"}), None)

    assert [user for user, _ in sent] == ["alice"]
    assert "ran for too long" not in sent[0][1]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
