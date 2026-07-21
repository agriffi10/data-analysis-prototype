"""Unit tests for the data-quality notify-failure handler (SPEC-114 FR-004).

The state this covers is the one that fires when NO VERB CODE RAN — a Lambda import
failure, a Step Functions-level error — so its input is whatever RecordFailure could
shape, and its job is to still put a friendly sentence in the actor's inbox.

Runnable under pytest or directly: python3 test_dq_notify_failure.py.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, os.path.join(_HERE, "..", "data-quality-common"))
sys.path.insert(0, _HERE)

import dq_notify_failure as nf  # noqa: E402
from cpcommon import clients, config  # noqa: E402

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
    config.NOTIFICATIONS_QUEUE_URL = QUEUE
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


def _terminal_cause(reason, detail="boom"):
    """What Lambda hands Step Functions when a verb raises TerminalError."""
    return {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorType": "TerminalError", "errorMessage": f"{reason}: {detail}"}
        ),
    }


def _event(error, actor="alice", request_id="r-1", location="alice/sales"):
    return {
        "requestId": request_id,
        "actor": actor,
        "location": location,
        "status": "failed",
        "error": error,
    }


def test_a_verb_terminal_is_decoded_to_its_own_reason():
    fake = _arm()
    nf.handler(_event(_terminal_cause("query_timeout")), None)
    assert "too large" in fake.messages()[0]


def test_the_dedup_id_matches_the_decorators():
    """FR-004's collapse: this emit and the decorator's must be indistinguishable to SQS."""
    fake = _arm()
    nf.handler(_event(_terminal_cause("query_failed")), None)
    assert fake.calls[0]["MessageDeduplicationId"] == "r-1:failure"
    assert fake.calls[0]["MessageGroupId"] == "alice"


def test_a_step_functions_timeout_still_notifies():
    """States.Timeout carries NO Cause key at all — the shape that used to kill the
    execution in an ASL States.StringToJson before it could reach this function."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    assert len(fake.calls) == 1
    assert "States.Timeout" not in fake.messages()[0]


def test_a_prose_cause_still_notifies_and_leaks_nothing():
    """States.DataLimitExceeded / Lambda.Unknown carry a plain sentence, not JSON."""
    fake = _arm()
    nf.handler(
        _event({"Error": "Lambda.Unknown", "Cause": "Unhandled error: ImportModuleError polars"}),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "polars" not in message
    assert "ImportModuleError" not in message


def test_a_lambda_import_failure_reaches_the_user():
    """FR-004: the class @notifies_on_failure structurally cannot catch — no verb ran."""
    fake = _arm()
    nf.handler(
        _event(
            {
                "Error": "Runtime.ImportModuleError",
                "Cause": json.dumps(
                    {
                        "errorType": "Runtime.ImportModuleError",
                        "errorMessage": "Unable to import module 'dq_byte_scan'",
                    }
                ),
            }
        ),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "dq_byte_scan" not in message
    assert "something went wrong" in message.lower()


def test_a_missing_error_object_still_notifies():
    fake = _arm()
    nf.handler(_event(None), None)
    assert len(fake.calls) == 1


def test_the_message_names_the_checked_location():
    """A user who started three checks cannot act on 'your check failed'."""
    fake = _arm()
    nf.handler(_event(_terminal_cause("query_failed"), location="alice/q3-sales"), None)
    assert "alice/q3-sales" in fake.messages()[0]


def test_a_pre_identity_failure_never_falls_back_to_a_body_supplied_username():
    """ValidateFailureSeed seeds actor=null for a garbage token, and the ONLY trustworthy
    recipient field is `actor` — which the state machine sets from the verified claim.

    THIS ASSERTS THE FALLBACK, NOT THE EMPTY SEND, and the distinction is why the test looks
    like this: `emit_notification` already no-ops on an empty username, so a version of this
    test that merely dropped `actor` would pass even if the handler's own guard were deleted
    — it would be measuring cpcommon's guard, not this one. The failure that actually
    matters is a handler that reaches for some OTHER field when `actor` is missing, which
    would let anyone who can enqueue deliver text to any inbox. So the event carries
    plausible attacker-controlled alternatives and none of them may be used.
    """
    fake = _arm()
    event = _event(_terminal_cause("unauthorized"), actor=None)
    event["username"] = "victim"
    event["user"] = "victim"
    event["requestedBy"] = "victim"
    nf.handler(event, None)
    assert fake.calls == [], "a recipient was derived from something other than `actor`"


def test_access_denied_leaks_no_path_or_space_name():
    fake = _arm()
    nf.handler(_event(_terminal_cause("forbidden"), location="finance/salaries"), None)
    assert "salaries" not in fake.messages()[0]


def test_the_request_object_is_threaded_through_unchanged():
    _arm()
    event = _event(_terminal_cause("query_failed"))
    assert nf.handler(event, None) == event


def test_the_handler_never_raises_on_a_junk_event():
    """The execution has already failed; a crash here replaces a message with nothing."""
    _arm()
    for junk in (None, [], "nonsense", 7, {"error": "not-a-dict"}):
        nf.handler(junk, None)


def test_the_handler_never_raises_when_sqs_is_down():
    class _Boom:
        def send_message(self, **kwargs):
            raise RuntimeError("sqs is down")

    config.NOTIFICATIONS_QUEUE_URL = QUEUE
    clients._sqs = _Boom()
    nf.handler(_event(_terminal_cause("query_failed")), None)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all notify-failure tests passed")
