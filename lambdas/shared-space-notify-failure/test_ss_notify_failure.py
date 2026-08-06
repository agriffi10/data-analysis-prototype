"""Unit tests for the shared-space notify-failure handler (SPEC-152 FR-002/FR-004).

The state this covers fires when NO VERB CODE RAN — the shape of PR #196, where this
plane's shared layer raised at import on one missing environment variable and every verb
died at cold start. Its input is whatever RecordFailure could shape, and its job is to
still put a friendly sentence in the actor's inbox.

Every assertion is on the NOTIFICATION BODY the user would receive rather than on a mock's
call args (FR-004).

Runnable as a plain script or under pytest; the common layer is added to sys.path so the
flat layer modules resolve either way.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, os.path.join(_HERE, "..", "shared-space-common"))
sys.path.insert(0, _HERE)

import ss_notify_failure as nf
from cpcommon import clients
from cpcommon import config as cpconfig

QUEUE = "https://sqs.test/dat-prod-notifications-requests.fifo"


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}

    def messages(self):
        return [json.loads(c["MessageBody"])["message"] for c in self.calls]


def _arm():
    cpconfig.NOTIFICATIONS_QUEUE_URL = QUEUE
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


def _event(error, actor="alice", action="create", space="sales", request_id="r-1"):
    """RecordFailure's output shape (state-machine.asl.json.tftpl)."""
    return {
        "requestId": request_id,
        "actor": actor,
        "action": action,
        "space": space,
        "status": "failed",
        "error": error,
    }


# ── The failures no verb can catch (FR-004) ───────────────────────────────────


def test_a_cold_start_import_failure_reaches_the_user():
    """PR #196 IS THIS TEST. The shared layer's import-time _require raised on one missing
    env var and every verb died before a line of handler code ran — so the verbs' own
    inline notifications, which is all this plane had, never fired."""
    fake = _arm()
    nf.handler(
        _event(
            {
                "Error": "Runtime.ImportModuleError",
                "Cause": json.dumps(
                    {
                        "errorType": "Runtime.ImportModuleError",
                        "errorMessage": "Unable to import module 'create_space': No module named 'registry'",
                    }
                ),
            }
        ),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "create_space" not in message and "registry" not in message
    assert 'We couldn\'t create shared workspace "sales"' in message


def test_a_step_functions_timeout_still_notifies():
    """States.Timeout carries NO Cause key at all."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, action="delete"), None)
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "States.Timeout" not in message
    assert 'We couldn\'t delete the shared workspace "sales"' in message


def test_a_prose_cause_leaks_nothing():
    fake = _arm()
    nf.handler(_event({"Error": "Lambda.Unknown", "Cause": "Unhandled error: RuntimeError"}), None)
    message = fake.messages()[0]
    assert "Lambda.Unknown" not in message and "RuntimeError" not in message


def test_every_routed_action_has_its_own_vocabulary():
    """The ACTION is what carries the information here, because every reason that can
    reach this path is a raw engine name that must never be shown. So each action the
    Choice state routes must read as itself — a create failure and a leave failure are
    not the same event to the person who asked for one of them."""
    seen = set()
    for action in ("create", "add_members", "remove_members", "leave", "delete",
                   "forget", "acknowledge_membership"):
        fake = _arm()
        nf.handler(_event({"Error": "States.Timeout"}, action=action), None)
        message = fake.messages()[0]
        assert "sales" in message, f"{action} did not name the space"
        seen.add(message)
    assert len(seen) == 7, "two actions produced the same sentence"


def test_an_unknown_action_names_nothing_rather_than_guessing():
    """The router's Default seeds this: an action the Choice has no branch for. Naming
    nothing beats naming the wrong thing, and the fallback phrase takes no space name
    because it is not written to have one appended."""
    fake = _arm()
    nf.handler(_event({"Error": "UnknownAction"}, action="teleport"), None)
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "sales" not in message
    assert "UnknownAction" not in message
    assert "shared workspace request" in message


# ── The duplicate collapse (FR-002) ───────────────────────────────────────────


def test_the_dedup_token_matches_the_create_verbs_own_emit():
    """THE SUPPRESSION MECHANISM ON THIS PLANE, and the only thing that stops create's
    handled failure being reported twice. create_space emits
    `{requestId}:create-failed:{actor}` and SQS drops the second message under the
    identical id. If this drifts, the pair stops collapsing silently."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, action="create"), None)
    assert fake.calls[0]["MessageDeduplicationId"] == "r-1:create-failed:alice"
    assert fake.calls[0]["MessageGroupId"] == "alice"


def test_the_dedup_token_matches_the_delete_verbs_own_emit():
    """delete_space keys its token on the registry OWNER while this verb keys on the
    validated ACTOR. They are the same string only because delete is owner-only — so that
    premise is asserted here rather than left in a comment. If delete ever widens to
    non-owners the pair stops collapsing, which is a duplicate rather than a silence, but
    it should be a visible decision and not a surprise."""
    import config as ss_config

    assert "delete" in ss_config.OWNER_ONLY_ACTIONS, (
        "delete is no longer owner-only, so delete_space's owner-keyed token and this "
        "verb's actor-keyed token can diverge"
    )
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, action="delete"), None)
    assert fake.calls[0]["MessageDeduplicationId"] == "r-1:delete-failed:alice"


def test_an_action_that_never_notifies_itself_is_not_suppressed():
    """Five of seven verbs emit NO failure message, which is why this plane suppresses by
    dedup token rather than by 'did a verb run': a Python guard would restore their
    silence, which is the whole bug."""
    for action in ("add_members", "remove_members", "leave", "forget", "acknowledge_membership"):
        fake = _arm()
        nf.handler(_event({"Error": "AuthorizationError"}, action=action), None)
        assert len(fake.calls) == 1, f"{action} was silenced"


def test_no_request_id_falls_back_to_content_dedup():
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, request_id=None), None)
    assert len(fake.calls) == 1
    assert "MessageDeduplicationId" not in fake.calls[0]


# ── Recipient trust (FR-002, the SPEC-126 rule) ───────────────────────────────


def test_a_pre_validation_failure_never_falls_back_to_a_body_supplied_username():
    """ValidateFailureSeed seeds actor=null for a garbage token. THIS ASSERTS THE FALLBACK,
    NOT THE EMPTY SEND: emit_notification already no-ops on an empty username, so the
    failure that matters is a handler reaching for some OTHER field — which would let
    anyone who can enqueue deliver text to any inbox."""
    fake = _arm()
    event = _event({"Error": "States.Timeout"}, actor=None)
    event["username"] = "victim"
    event["user"] = "victim"
    event["owner"] = "victim"
    nf.handler(event, None)
    assert fake.calls == [], "a recipient was derived from something other than `actor`"


# ── Totality: it never raises, whatever it is handed (FR-002) ─────────────────


def test_every_malformed_error_payload_still_notifies():
    for shape in (None, {}, "a string", 7, [], {"Cause": "no Error key"}):
        fake = _arm()
        nf.handler(_event(shape), None)
        assert len(fake.calls) == 1, f"no notification for error payload {shape!r}"
        assert "something went wrong" in fake.messages()[0].lower()


def test_an_absent_space_degrades_rather_than_quoting_nothing():
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, space=None), None)
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert '""' not in message
    assert "We couldn't create shared workspace:" in message


def test_the_handler_never_raises_on_a_junk_event():
    _arm()
    for junk in (None, [], "nonsense", 7, {"error": "not-a-dict"}):
        nf.handler(junk, None)


def test_the_handler_never_raises_when_sqs_is_down():
    class _Boom:
        def send_message(self, **kwargs):
            raise RuntimeError("sqs is down")

    cpconfig.NOTIFICATIONS_QUEUE_URL = QUEUE
    clients._sqs = _Boom()
    nf.handler(_event({"Error": "States.Timeout"}), None)


def test_the_request_object_is_threaded_through_unchanged():
    _arm()
    event = _event({"Error": "States.Timeout"})
    assert nf.handler(event, None) == event


def test_traced_is_the_only_decorator():
    import inspect

    source = inspect.getsource(nf)
    assert '@observability.traced("notify-failure")' in source
    assert "notifies_on_failure(" not in source


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
