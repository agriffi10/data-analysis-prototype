"""Unit tests for the table-share notify-failure handler (SPEC-152 FR-002/FR-004).

The state this covers fires when NO VERB CODE RAN — a Lambda import failure, a Step
Functions-level error — so its input is whatever RecordFailure could shape, and its job is
to still put a friendly sentence in the sender's inbox.

Every assertion is on the NOTIFICATION BODY the sender would receive rather than on a
mock's call args (FR-004).

Runnable under pytest or directly: python3 test_ts_notify_failure.py.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, os.path.join(_HERE, "..", "table-share-common"))
sys.path.insert(0, _HERE)

import pytest
import ts_notify_failure as nf
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
    return {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorType": "TerminalError", "errorMessage": f"{reason}: {detail}"}
        ),
    }


def _event(error, actor="alice", source_table="sales"):
    """RecordFailure's output shape (state-machine.asl.json.tftpl)."""
    return {
        "actor": actor,
        "source": {"database": "alice", "table": source_table},
        "tableName": "sales_copy",
        "status": "failed",
        "error": error,
    }


# ── The failures no verb can catch (FR-004) ───────────────────────────────────


def test_an_engine_error_notifies_without_leaking_its_name():
    """An error no verb raised — no decoded reason, so the generic sentence, and never the
    raw Step Functions name in a user's inbox.

    ``States.Timeout`` is the payload here for historical reasons and is now a **stand-in for
    any engine error**, not a scenario: SPEC-161 established that a top-level timeout bypasses
    every catcher, so it cannot reach this door at all. The EventBridge tests below cover the
    real timeout path. Renamed rather than deleted — the assertion is still the right one for
    the class of error that does arrive here.
    """
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "States.Timeout" not in message
    assert 'Couldn\'t share "sales"' in message


def test_a_lambda_import_failure_reaches_the_sender():
    """THE SPEC-137 SHAPE — a verb that cannot import, so no handler code runs."""
    fake = _arm()
    nf.handler(
        _event(
            {
                "Error": "Runtime.ImportModuleError",
                "Cause": json.dumps(
                    {
                        "errorType": "Runtime.ImportModuleError",
                        "errorMessage": "Unable to import module 'table_share_copy_objects': No module named 'tscommon'",
                    }
                ),
            }
        ),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "tscommon" not in message and "copy_objects" not in message
    assert "something went wrong" in message.lower()


def test_a_map_payload_overflow_still_notifies():
    """States.DataLimitExceeded on the Map's collected results is THE realistic
    execution-level failure on this plane — it is why cpcommon bounds every
    TerminalError detail — and its Cause is prose, not JSON."""
    fake = _arm()
    nf.handler(
        _event({"Error": "States.DataLimitExceeded", "Cause": "The state output exceeded 262144 bytes"}),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "262144" not in message
    assert "States.DataLimitExceeded" not in message


# ── The duplicate a verb already sent (FR-002) ────────────────────────────────


def test_a_verbs_own_terminal_error_is_suppressed():
    fake = _arm()
    nf.handler(_event(_terminal_cause("source_is_view")), None)
    assert fake.calls == []


# ── The whole-request phrasing (FR-002) ───────────────────────────────────────


def test_the_message_names_the_source_table():
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, source_table="q3_returns"), None)
    assert "q3_returns" in fake.messages()[0]


# ── Recipient trust (FR-002, the SPEC-126 rule) ───────────────────────────────


# ── Totality: it never raises, whatever it is handed (FR-002) ─────────────────


def test_every_malformed_error_payload_still_notifies():
    for shape in (None, {}, "a string", 7, [], {"Cause": "no Error key"}):
        fake = _arm()
        nf.handler(_event(shape), None)
        assert len(fake.calls) == 1, f"no notification for error payload {shape!r}"
        assert "something went wrong" in fake.messages()[0].lower()


# ── the EventBridge door: a run the machine's own timeout stopped (SPEC-161) ──


def _timeout_event(body=None, *, included=True, input_override=None):
    """EventBridge's Step Functions Execution Status Change event for a TIMED_OUT run.

    ``detail.input`` is the EXECUTION input, which on this plane is what the Pipe forwarded —
    the raw SQS batch — so the body sits inside a record inside a JSON string inside the event.
    Built here the same way rather than hand-flattened, because the nesting is the part of this
    path most likely to be got wrong.
    """
    if input_override is not None:
        raw = input_override
    else:
        record_body = body if body is not None else {
            "actor": "token-for-alice",
            "source": {"database": "alice", "table": "sales"},
            "tableName": "sales_copy",
        }
        raw = json.dumps([{"body": json.dumps(record_body)}])
    return {
        "source": "aws.states",
        "detail-type": "Step Functions Execution Status Change",
        "detail": {
            "executionArn": "arn:aws:states:us-east-1:1:execution:m:e",
            "stateMachineArn": "arn:aws:states:us-east-1:1:stateMachine:m",
            "status": "TIMED_OUT",
            "input": raw,
            "inputDetails": {"included": included},
        },
    }


def _verified(monkeypatch, username="alice"):
    """Stubs the token verification the timeout door depends on."""
    monkeypatch.setattr(
        nf.auth, "verified_username_ignoring_expiry", lambda token, **kw: username
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
