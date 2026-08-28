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


# ── Suppression is by ONE NAME, never by a heuristic ─────────────────────────


# ── No verified actor is a logged no-op, never a guess ───────────────────────


def test_a_failure_with_no_recoverable_actor_notifies_nobody(monkeypatch, sent):
    """The body's own actor field is attacker-controlled, and notifying it would let anyone
    deliver text to any inbox."""
    monkeypatch.setattr(auth, "verified_username_ignoring_expiry", lambda actor, **kw: "")

    verb.handler(_failed(raw=None), None)

    assert sent == []


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
