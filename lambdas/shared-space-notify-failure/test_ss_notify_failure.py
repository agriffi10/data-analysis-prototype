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


# ── The duplicate collapse (FR-002) ───────────────────────────────────────────


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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
