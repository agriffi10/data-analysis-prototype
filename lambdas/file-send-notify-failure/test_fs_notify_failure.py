"""Unit tests for file-send notify-failure (SPEC-152 on this plane).

This is the notification of last resort — the one that fires when no verb's decorator could,
because no verb code ran. The tests that matter are the three ways it can go wrong: telling
nobody when it should, telling somebody twice, and telling the wrong person.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import fs_notify_failure as n
import pytest


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


def _raw(token="tok"):
    """The Pipe's forwarded batch, as the failure seed reads it from $$.Execution.Input."""
    return [{"body": json.dumps({"requestId": "req-1", "actor": token})}]


def test_an_engine_failure_notifies_the_sender():
    sent = _capture()

    n.handler(_request({"Error": "States.Timeout", "Cause": None}), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"


def test_an_import_time_failure_notifies_the_sender():
    """PR #196's own shape: a shared layer's config raising a bare RuntimeError at cold start,
    where no verb code ran and no decorator could have fired. This is the failure the whole
    state exists for, and the tempting "a dot means the engine" heuristic would silence it."""
    sent = _capture()

    n.handler(_request({"Error": "RuntimeError", "Cause": "missing ADMIN_BUCKET"}), None)

    assert len(sent) == 1


def test_a_verbs_own_terminal_error_is_not_notified_twice():
    """The verb's decorator already sent one. Suppression is on ONE positively-identified
    name — never on a heuristic — because a guess that suppresses is unrecoverable while a
    duplicate is a papercut."""
    sent = _capture()

    n.handler(_request({"Error": "TerminalError", "Cause": '{"reason": "forbidden"}'}), None)

    assert sent == []


def test_the_sender_is_recovered_from_the_request_when_no_verb_produced_one():
    """THE CASE THIS STATE ACTUALLY SEES. Every failure it exists for — a cold-start import
    error, a state timeout, a task that could not be invoked — happens before an actor exists,
    so the recorded object carries actor: null. Recovering the sender from the verified token
    in the captured request is the difference between SPEC-152's guarantee holding here and
    reading as satisfied while telling nobody anything."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"

    n.handler(_request({"Error": "RuntimeError", "Cause": "ModuleNotFoundError"}, actor=None, raw=_raw()), None)

    assert [user for user, _ in sent] == ["alice"]


def test_a_recorded_actor_wins_over_the_captured_request():
    """Once a verb has produced a verified actor, that is the answer; the body is only ever a
    fallback and must never override it."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "mallory"

    n.handler(_request({"Error": "States.Timeout"}, actor="alice", raw=_raw()), None)

    assert [user for user, _ in sent] == ["alice"]


def test_an_unverifiable_token_in_the_captured_request_notifies_nobody():
    """The body's own fields are attacker-controlled. If the token does not verify, there is no
    addressee — notifying anyway would let anyone deliver text to any inbox."""
    sent = _capture()

    def _reject(token, **kw):
        raise ValueError("bad signature")

    n.auth.verified_username_ignoring_expiry = _reject

    n.handler(_request({"Error": "States.Timeout"}, actor=None, raw=_raw()), None)

    assert sent == []


def test_a_malformed_captured_request_notifies_nobody_rather_than_raising():
    sent = _capture()

    n.handler(_request({"Error": "States.Timeout"}, actor=None, raw=[{"body": "{not json"}]), None)

    assert sent == []


def test_a_failure_with_no_verified_sender_notifies_nobody():
    """The body's actor field is attacker-controlled; notifying it would let anyone deliver
    text to any inbox."""
    sent = _capture()

    n.handler(_request({"Error": "States.Timeout"}, actor=None), None)

    assert sent == []


def test_an_actor_that_is_not_the_expected_shape_notifies_nobody():
    sent = _capture()

    n.handler({"actor": "alice", "error": {"Error": "States.Timeout"}}, None)

    assert sent == []


def test_the_request_is_threaded_onward_unchanged():
    _capture()
    request = _request({"Error": "States.Timeout"})

    assert n.handler(request, None) == request


def test_a_non_dict_event_does_not_raise():
    """The execution has already failed. A crash here replaces a friendly notification with
    nothing at all."""
    _capture()

    assert n.handler(None, None) == {}


def test_the_message_carries_no_raw_engine_text():
    """SPEC-106: the Cause is for the logs and the SFN record, never the user's sentence."""
    sent = _capture()

    n.handler(_request({"Error": "Lambda.Unknown", "Cause": "Task timed out after 15.00 seconds"}), None)

    assert "Task timed out" not in sent[0][1]


def test_the_emit_is_the_shared_swallowing_one():
    """A failing send must never fail this state — the execution has already failed, and an
    exception here would replace a recorded failure with an unhandled one.

    Asserted as an IDENTITY rather than by stubbing a raising emitter, which is the version
    this test had first and which proved nothing: stubbing the emitter replaces the very code
    whose catching is the claim. The swallowing lives in ``cpcommon.notify.emit_notification``
    and is tested there; what this plane has to get right is using that one.
    """
    from cpcommon import notify as cpnotify

    assert n.notify.emit_notification is cpnotify.emit_notification


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-166 FR-005: the second door ────────────────────────────────────────


def _timed_out(input_json=None, included=True):
    """An EventBridge Step Functions status-change event for a timed-out execution.

    The execution's input is what the Pipe forwarded — the raw SQS batch — so the sender comes
    from the verified token in it, exactly as the ASL door's fallback does.
    """
    detail = {"status": "TIMED_OUT", "inputDetails": {"included": included}}
    if input_json is not None:
        detail["input"] = input_json
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_a_timed_out_execution_notifies_the_sender():
    """The failure the ASL door CANNOT reach. Step Functions catchers cover Task, Parallel and
    Map states but not top-level execution failures, so a run that exhausts TimeoutSeconds is
    terminated outright: no state runs, no Catch fires, and without this door the sender is told
    nothing at all — the exact silence SPEC-152 exists to close."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"


def test_the_timeout_message_is_not_the_generic_failure_sentence():
    """A timeout is the one whole-request failure that can leave a recipient holding PART of a
    send — the guard and the copy may both have run — so "try again" alone would be wrong
    advice, and trying again would then conflict on what did arrive."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert "part" in sent[0][1].lower()
    assert sent[0][1] != n.messages.failure_message("unexpected_error")


def test_the_timeout_door_verifies_the_token_and_never_trusts_the_body():
    """The body is attacker-controlled: it reached the queue from a browser. Notifying whoever
    it names would let anyone deliver text to any inbox."""
    sent = _capture()

    def _reject(token, **kw):
        raise ValueError("bad signature")

    n.auth.verified_username_ignoring_expiry = _reject

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert sent == []


def test_the_timeout_door_ignores_expiry_deliberately():
    """By construction the token IS expired by the time a three-hour timeout fires. The
    relaxation is the DLQ drain's, through the same separately-named entry point, and it is safe
    for the same reason: this path grants nothing, it only addresses a message."""
    sent = _capture()
    n.auth.verified_username = lambda token, **kw: (_ for _ in ()).throw(ValueError("expired"))
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert sent and sent[0][0] == "alice"


@pytest.mark.parametrize(
    "event",
    [
        _timed_out(),
        _timed_out("", included=False),
        _timed_out("not json"),
        {"detail-type": "Step Functions Execution Status Change", "detail": "not an object"},
    ],
    ids=["no-input", "omitted-input", "unparseable", "detail-not-an-object"],
)
def test_an_unattributable_timeout_is_a_logged_no_op_rather_than_a_raise(event):
    """A raise here would be an async Lambda failure, and EventBridge RETRIES those — turning
    one unattributable event into three."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"

    n.handler(event, None)

    assert sent == []


def test_the_asl_door_is_unaffected_by_the_second_one():
    """The two doors are dispatched on the detail-type, not on the presence of a `detail` field:
    the ASL door's payload is a request object, and a request could in principle carry any field
    name."""
    sent = _capture()

    n.handler(_request({"Error": "States.DataLimitExceeded"}, actor="alice", raw=None), None)

    assert len(sent) == 1
    assert "part" not in sent[0][1].lower()


def test_a_timed_out_execution_whose_input_was_omitted_is_read_back():
    """The ordinary case for a large send, not an edge one. EventBridge caps an event at 256 KB
    and drops the input rather than exceed it, while SEND_MAX_ITEM_BYTES deliberately allows a
    Pipe record approaching 200 KB — so the sends most likely to run for three hours are exactly
    the ones the event alone cannot attribute.

    The read-back ITSELF is cpcommon's and is tested there; what this asserts is that THIS door
    is wired to it and attributes the sender it recovers."""
    sent = _capture()
    n.auth.verified_username_ignoring_expiry = lambda token, **kw: "alice"
    described = []

    class _Sfn:
        def describe_execution(self, executionArn):
            described.append(executionArn)
            return {"input": json.dumps(_raw())}

    n.events.clients._sfn = _Sfn()
    event = _timed_out("", included=False)
    event["detail"]["executionArn"] = "arn:aws:states:us-east-1:1:execution:m:e"

    n.handler(event, None)

    assert described == ["arn:aws:states:us-east-1:1:execution:m:e"]
    assert sent and sent[0][0] == "alice"
