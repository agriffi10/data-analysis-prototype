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


def _raw(identity=True, fmt="parquet", filename=None):
    body = {"requestId": "req-1", "format": fmt, "actor": "not-a-username-a-token"}
    if filename:
        body["destination"] = {"filename": filename, "prefix": "out/", "space": {"kind": "personal", "name": "alice"}}
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


def test_a_converters_refusal_reaches_the_user_with_the_count_and_the_file_name():
    """The whole reason the machine routes a refusal through a Choice rather than a raise.

    A raise arrives here as a TerminalError and is SUPPRESSED as a duplicate of the verb's own
    notification; a refusal arrives as `{"Error": "<reason>"}` with no Cause, so this door is
    the one producer. It has to assemble the sentence from two sources — the row count is on
    the state, discovered by the converter, and the file name is in the request body under
    `$.raw` — and neither had a test. Dropping the token merge left the suite green while the
    user read "the results have  rows" and 'a file called ""'.
    """
    sent = _capture()
    n.handler(
        {
            **_request({"Error": "excel_row_limit"}, fmt="xlsx", raw=_raw(filename="q1.xlsx")),
            "tokens": {"count": 2_000_000},
        },
        None,
    )

    assert len(sent) == 1 and sent[0][0] == "alice"
    message = sent[0][1]
    assert "2000000 rows" in message, "the count is on the state and reaches the sentence"
    assert '"q1.xlsx"' in message, "the file name is in the request body and reaches it too"
    assert "as Excel" in message
    assert "{" not in message, "no marker was left unfilled"


def test_a_refusal_that_carries_no_count_still_names_the_file():
    """`destination_occupied` needs the name and no count, and `tokens` is null on its seed's
    two siblings — so the two sources have to be independent of each other."""
    sent = _capture()
    n.handler(
        {**_request({"Error": "destination_occupied"}, fmt="parquet", raw=_raw(filename="q1.parquet")), "tokens": None},
        None,
    )

    assert '"q1.parquet"' in sent[0][1]
    assert "{" not in sent[0][1]


def test_a_hostile_token_value_cannot_put_an_object_into_a_sentence():
    """`tokens` arrives from the state, and only strings and integers are taken from it — a
    bool is excluded too, because `isinstance(True, int)` is True and `{count}` would render
    as `True`."""
    sent = _capture()
    n.handler(
        {
            **_request({"Error": "excel_row_limit"}, fmt="xlsx", raw=_raw(filename="q1.xlsx")),
            "tokens": {"count": {"nested": "object"}, "filename": ["a"], "extra": True},
        },
        None,
    )

    assert "nested" not in sent[0][1] and "True" not in sent[0][1]
    assert '"q1.xlsx"' in sent[0][1], "the recovered name still fills the marker"


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
