"""notify-failure: the archive plane's notification of last resort (SPEC-152).

It exists for the failures no verb can catch — a cold-start import error, a task that could
not be invoked — where the decorator never ran and the actor would otherwise be told nothing
at all.
"""

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
from token_shapes import JWT_SHAPED

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: out.append((user, text)))
    return out


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
