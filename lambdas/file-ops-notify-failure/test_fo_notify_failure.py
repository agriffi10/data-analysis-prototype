"""Unit tests for file-ops notify-failure (the spec on this plane).

This is the notification of last resort — the one that fires when no verb's decorator could,
because no verb code ran. The tests that matter are the three ways it can go wrong: telling
nobody when it should, telling somebody twice, and telling the wrong person.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import fo_notify_failure as n
import pytest
from token_shapes import JWT_SHAPED


def _capture():
    sent = []
    n.notify.emit_notification = lambda user, message: sent.append((user, message))
    return sent


def _request(error, actor="alice", raw=None):
    return {
        "requestId": "req-1",
        "actor": {"username": actor} if actor else None,
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "raw": raw,
        "status": "failed",
        "error": error,
    }


_JWT = JWT_SHAPED


def _raw(actor="alice", identity=True):
    """The Pipe's forwarded batch, as the failure seed reads it from $$.Execution.Input.

    The flat ``actor`` still carries the raw token until the API stops sending it, and is kept
    here for that reason: the recovery must come from the block beside it, and dropping the
    field would stop this fixture proving so.

    Args:
      actor: The verified username the identity block names.
      identity: Whether to carry the block at all — False is the pre-cutover envelope.

    Returns:
      The forwarded SQS batch.

    Raises:
      None.
    """
    body = {"requestId": "req-1", "actor": _JWT}
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    return [{"body": json.dumps(body)}]


def test_an_engine_failure_notifies_the_actor():
    sent = _capture()

    n.handler(_request({"Error": "States.Timeout", "Cause": None}), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"


def test_the_actor_is_recovered_from_the_request_when_no_verb_produced_one():
    """THE CASE THIS STATE ACTUALLY SEES. Every failure it exists for — a cold-start import
    error, a state timeout, a task that could not be invoked — happens before an actor exists,
    so the recorded object carries actor: null. Recovering the actor from the verified token
    in the captured request is the difference between the spec's guarantee holding here and
    reading as satisfied while telling nobody anything."""
    sent = _capture()

    n.handler(_request({"Error": "RuntimeError", "Cause": "ModuleNotFoundError"}, actor=None, raw=_raw()), None)

    assert [user for user, _ in sent] == ["alice"]


def test_the_door_degrades_when_the_request_carries_no_identity_block():
    """The pre-cutover envelope, and the one shape this door must NOT raise on.

    A raise here is an async Lambda failure EventBridge retries, so one unattributable event
    becomes three. The honest outcome is a logged no-op and no notification: there is no
    trustworthy recipient, and the flat ``actor`` beside the missing block is a raw token.
    """
    sent = _capture()

    n.handler(_request({"Error": "RuntimeError", "Cause": None}, actor=None, raw=_raw(identity=False)), None)

    assert sent == []


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))


# ── The timeout door: the second door ────────────────────────────────────────


def _timed_out(input_json=None, included=True):
    """An EventBridge Step Functions status-change event for a timed-out execution.

    The execution's input is what the Pipe forwarded — the raw SQS batch — so the actor comes
    from the verified token in it, exactly as the ASL door's fallback does.
    """
    detail = {"status": "TIMED_OUT", "inputDetails": {"included": included}}
    if input_json is not None:
        detail["input"] = input_json
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_a_timed_out_execution_notifies_the_actor():
    """The failure the ASL door CANNOT reach. Step Functions catchers cover Task, Parallel and
    Map states but not top-level execution failures, so a run that exhausts TimeoutSeconds is
    terminated outright: no state runs, no Catch fires, and without this door the actor is told
    nothing at all — the exact silence the spec exists to close."""
    sent = _capture()

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"
