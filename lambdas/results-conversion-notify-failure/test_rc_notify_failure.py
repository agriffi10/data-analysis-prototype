"""notify-failure on this plane: tell the actor once, from the identity block, through both doors."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results-conversion-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_notify_failure as n


def _capture():
    sent = []
    n.notify.emit_notification = lambda user, message, **kw: sent.append((user, message))
    return sent


def _request(error, username="alice", fmt="json", raw=None):
    return {"requestId": "req-1", "username": username, "format": fmt, "raw": raw, "status": "failed", "error": error}


def _raw(identity=True, fmt="parquet"):
    body = {"requestId": "req-1", "format": fmt, "actor": "not-a-username-a-token"}
    if identity:
        body["identity"] = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}
    return [{"body": json.dumps(body)}]


def _timed_out(input_json=None, included=True):
    detail = {"status": "TIMED_OUT", "inputDetails": {"included": included}}
    if input_json is not None:
        detail["input"] = input_json
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_an_engine_failure_notifies_the_actor_naming_the_format():
    sent = _capture()
    n.handler(_request({"Error": "States.Timeout", "Cause": None}), None)
    assert sent == [("alice", "Couldn't save the query results as JSON: something went wrong.")]


def test_the_actor_is_recovered_from_the_request_when_no_verb_produced_one():
    sent = _capture()
    n.handler(_request({"Error": "RuntimeError", "Cause": "ModuleNotFoundError"}, username=None, fmt=None, raw=_raw()), None)
    assert [user for user, _ in sent] == ["alice"]
    assert "as Parquet" in sent[0][1]


def test_a_request_with_no_identity_block_notifies_nobody_and_does_not_raise():
    """no_identity_block: the flat field beside the missing block is never a recipient."""
    sent = _capture()
    n.handler(_request({"Error": "RuntimeError", "Cause": None}, username=None, raw=_raw(identity=False)), None)
    assert sent == []


def test_a_verbs_own_terminal_error_is_not_notified_twice():
    sent = _capture()
    cause = json.dumps({"errorType": "TerminalError", "errorMessage": "results_too_large: 5 bytes"})
    n.handler(_request({"Error": "TerminalError", "Cause": cause}), None)
    assert sent == []


def test_a_timed_out_execution_notifies_the_actor_from_the_event_input():
    sent = _capture()
    n.handler(_timed_out(json.dumps(_raw())), None)
    assert sent == [("alice", "Couldn't save the query results as Parquet: the conversion was still running after an hour and was stopped. Nothing was saved.")]


@pytest.mark.parametrize("event", [_timed_out(None, included=False), _timed_out("not json"), {"detail-type": "Step Functions Execution Status Change", "detail": "x"}])
def test_the_timeout_door_degrades_on_every_bad_shape(event):
    sent = _capture()
    assert n.handler(event, None)["username"] == ""
    assert sent == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
