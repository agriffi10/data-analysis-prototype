"""notify-failure: the archive plane's notification of last resort (SPEC-152).

It exists for the failures no verb can catch — a cold-start import error, a task that could
not be invoked — where the decorator never ran and the actor would otherwise be told nothing
at all.
"""

import json
import os
import pathlib
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


# ── This plane has ONE door, and saying so is the point ──────────────────────


def test_there_is_no_eventbridge_timeout_door_yet():
    """File-send's twin grew a second door because its machine has a top-level TimeoutSeconds
    and catchers do not cover a top-level execution failure. This machine validates and stops.

    This test is a tripwire on SPEC-169: the moment that spec adds the transfer it must add
    the ceiling, the EventBridge TIMED_OUT rule, the states:DescribeExecution grant and the
    second door together — a ceiling that cannot notify is SPEC-152 satisfied on paper and
    silent in practice.
    """
    source = pathlib.Path(verb.__file__).read_text()

    assert "Step Functions Execution Status Change" not in source
    assert "describe_execution" not in source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
