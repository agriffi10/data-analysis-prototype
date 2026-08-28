"""Unit tests for the table-builder notify-failure handler (SPEC-152 FR-002/FR-004).

The state this covers fires when NO VERB CODE RAN — a Lambda import failure, a Step
Functions-level error — so its input is whatever RecordFailure could shape, and its job is
to still put a friendly sentence in the actor's inbox.

Every assertion is on the NOTIFICATION BODY the user would receive rather than on a mock's
call args (FR-004): what is being protected is what the message says, and a test that
pins the arguments passes just as happily when the wording is wrong.

Runnable under pytest or directly: python3 test_tb_notify_failure.py.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, os.path.join(_HERE, "..", "table-builder-common"))
sys.path.insert(0, _HERE)

import tb_notify_failure as nf
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


def _event(error, actor="alice", request_id="r-1", table="sales", mode="create"):
    """RecordFailure's output shape (state-machine.asl.json.tftpl)."""
    return {
        "requestId": request_id,
        "actor": actor,
        "database": "alice",
        "tableName": table,
        "mode": mode,
        "status": "failed",
        "error": error,
    }


# ── The failures no verb can catch (FR-004) ───────────────────────────────────


def test_a_step_functions_timeout_still_notifies():
    """States.Timeout carries NO Cause key at all — the shape that used to kill the
    execution in an ASL States.StringToJson before it could reach this function."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "States.Timeout" not in message
    assert 'Couldn\'t create table "sales"' in message


def test_a_lambda_import_failure_reaches_the_user():
    """THE SPEC-137 SHAPE. Three singleton Lambdas raised ModuleNotFoundError at cold
    start for nine days; a table-builder verb failing the same way is this event."""
    fake = _arm()
    nf.handler(
        _event(
            {
                "Error": "Runtime.ImportModuleError",
                "Cause": json.dumps(
                    {
                        "errorType": "Runtime.ImportModuleError",
                        "errorMessage": "Unable to import module 'infer_schema': No module named 'tbcommon'",
                    }
                ),
            }
        ),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "infer_schema" not in message and "tbcommon" not in message
    assert "something went wrong" in message.lower()


# ── The duplicate a verb already sent (FR-002) ────────────────────────────────


def test_a_verbs_own_terminal_error_is_suppressed():
    """The decorator already notified, with a BETTER message: it carries err.tokens, which
    this path cannot reconstruct."""
    fake = _arm()
    nf.handler(_event(_terminal_cause("table_exists")), None)
    assert fake.calls == []


# ── The instrumentation rules (FR-002) ────────────────────────────────────────


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
