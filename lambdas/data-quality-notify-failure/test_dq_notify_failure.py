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

import dq_notify_failure as nf
from cpcommon import clients, config

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


def test_access_denied_leaks_no_path_or_space_name():
    fake = _arm()
    nf.handler(_event(_terminal_cause("forbidden"), location="finance/salaries"), None)
    assert "salaries" not in fake.messages()[0]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all notify-failure tests passed")


