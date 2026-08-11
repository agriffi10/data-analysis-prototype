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
    """The Pipe's forwarded batch, as CaptureRequest stores it."""
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
