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


def test_an_exhausted_transient_retry_now_notifies():
    """@notifies_on_failure passes a TransientError through UN-notified on purpose — a
    retry was still pending. When the Retry list is exhausted nothing told the sender."""
    fake = _arm()
    nf.handler(_event({"Error": "TransientError", "Cause": "listing objects"}), None)
    assert len(fake.calls) == 1
    assert "listing objects" not in fake.messages()[0]


# ── The duplicate a verb already sent (FR-002) ────────────────────────────────


def test_a_verbs_own_terminal_error_is_suppressed():
    fake = _arm()
    nf.handler(_event(_terminal_cause("source_is_view")), None)
    assert fake.calls == []


def test_an_init_phase_runtime_error_is_never_suppressed():
    """THE REGRESSION THAT KILLED THE FIRST VERSION OF THIS GUARD. `tscommon.config` and
    `cpcommon.config` both call `_require` at MODULE SCOPE and raise a bare `RuntimeError`
    — PR #196's shape. A discriminator reading "a bare class name means a handler ran"
    would have suppressed it, silencing the class SPEC-152 exists to report."""
    fake = _arm()
    nf.handler(_event({"Error": "RuntimeError", "Cause": "required environment variable is unset"}), None)
    assert len(fake.calls) == 1, "an import-time RuntimeError was silenced"


def test_an_unexpected_in_verb_exception_is_allowed_to_duplicate():
    """FR-002 settles the tie: 'a duplicate notification is preferable to none'."""
    fake = _arm()
    nf.handler(_event({"Error": "ClientError", "Cause": "An error occurred (AccessDenied)"}), None)
    assert len(fake.calls) == 1
    assert "AccessDenied" not in fake.messages()[0]


def test_an_engine_name_is_never_mistaken_for_a_verb_exception():
    for engine in ("States.Timeout", "States.DataLimitExceeded", "Lambda.Unknown",
                   "Runtime.ImportModuleError", "Lambda.ServiceException"):
        fake = _arm()
        nf.handler(_event({"Error": engine}), None)
        assert len(fake.calls) == 1, f"{engine} was suppressed as if a verb had notified"


# ── The whole-request phrasing (FR-002) ───────────────────────────────────────


def test_the_message_uses_the_whole_request_phrasing_not_a_recipient_one():
    """Naming a recipient here would be a GUESS: the failure ended the request before any
    per-recipient outcome existed. tscommon.failure_message omits the recipient clause
    when it is given no kind/name, and that omission is the assertion."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    message = fake.messages()[0]
    assert message.startswith('Couldn\'t share "sales":')
    assert " to " not in message


def test_the_message_names_the_source_table():
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, source_table="q3_returns"), None)
    assert "q3_returns" in fake.messages()[0]


def test_no_dedup_id_is_sent_matching_the_rest_of_the_plane():
    """Every other emitter on this plane relies on the queue's content-based dedup."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    assert "MessageDeduplicationId" not in fake.calls[0]
    assert fake.calls[0]["MessageGroupId"] == "alice"


# ── Recipient trust (FR-002, the SPEC-126 rule) ───────────────────────────────


def test_a_pre_identity_failure_never_falls_back_to_a_body_supplied_username():
    """THIS ASSERTS THE FALLBACK, NOT THE EMPTY SEND: emit_notification already no-ops on
    an empty username, so the failure that matters is a handler reaching for some OTHER
    field, which would let anyone who can enqueue deliver text to any inbox."""
    fake = _arm()
    event = _event({"Error": "States.Timeout"}, actor=None)
    event["username"] = "victim"
    event["user"] = "victim"
    event["requestedBy"] = "victim"
    nf.handler(event, None)
    assert fake.calls == [], "a recipient was derived from something other than `actor`"


# ── Totality: it never raises, whatever it is handed (FR-002) ─────────────────


def test_every_malformed_error_payload_still_notifies():
    for shape in (None, {}, "a string", 7, [], {"Cause": "no Error key"}):
        fake = _arm()
        nf.handler(_event(shape), None)
        assert len(fake.calls) == 1, f"no notification for error payload {shape!r}"
        assert "something went wrong" in fake.messages()[0].lower()


def test_a_malformed_source_still_notifies():
    """`source` is a nested object, so it is one more shape that can arrive wrong."""
    for shape in (None, "sales", [], 7):
        fake = _arm()
        event = _event({"Error": "States.Timeout"})
        event["source"] = shape
        nf.handler(event, None)
        assert len(fake.calls) == 1
        assert "your table" in fake.messages()[0]


def test_the_handler_never_raises_on_a_junk_event():
    _arm()
    for junk in (None, [], "nonsense", 7, {"error": "not-a-dict"}):
        nf.handler(junk, None)


def test_the_handler_never_raises_when_sqs_is_down():
    class _Boom:
        def send_message(self, **kwargs):
            raise RuntimeError("sqs is down")

    config.NOTIFICATIONS_QUEUE_URL = QUEUE
    clients._sqs = _Boom()
    nf.handler(_event({"Error": "States.Timeout"}), None)


def test_the_request_object_is_threaded_through_unchanged():
    _arm()
    event = _event({"Error": "States.Timeout"})
    assert nf.handler(event, None) == event


def test_traced_is_the_outermost_and_only_decorator():
    import inspect

    source = inspect.getsource(nf)
    assert '@observability.traced("notify-failure")' in source
    assert "@notify.notifies_on_failure" not in source


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


def test_a_timed_out_execution_notifies_the_verified_sender(monkeypatch):
    """SPEC-161 FR-003 AC2 — the criterion, on the ONLY path that can deliver it.

    A top-level TimeoutSeconds expiry terminates the execution outright; Step Functions
    catchers do not cover top-level execution failures, so the machine's own NotifyFailure
    state is unreachable here. This door is what keeps "it just never came back" unreachable.
    """
    fake = _arm()
    _verified(monkeypatch)

    nf.handler(_timeout_event(), None)

    assert len(fake.calls) == 1
    message = fake.messages()[0]
    assert "sales" in message
    assert "ran for too long" in message
    assert json.loads(fake.calls[0]["MessageBody"])["username"] == "alice"


def test_the_timeout_message_warns_that_data_may_be_partial(monkeypatch):
    """Not the generic failure sentence, and the difference is advice.

    A timeout is the one whole-request failure that can leave a recipient holding PART of a
    dataset — the copy may have run and the create may not — so "just try again" would be
    wrong. Asserted on the body the sender reads, not on the reason code.
    """
    fake = _arm()
    _verified(monkeypatch)

    nf.handler(_timeout_event(), None)

    message = fake.messages()[0]
    assert "part of the data" in message
    assert "Administrator" in message


def test_the_sender_comes_from_the_TOKEN_not_the_body(monkeypatch):
    """The body is a queue message; its own actor field is attacker-controlled.

    The `actor` field HOLDS the ID token on this plane, and the username is the verified claim
    inside it. A body claiming to be someone else must not redirect the notification.
    """
    fake = _arm()
    monkeypatch.setattr(
        nf.auth, "verified_username_ignoring_expiry", lambda token, **kw: "alice"
    )

    nf.handler(_timeout_event({"actor": "token", "username": "mallory", "source": {}}), None)

    assert json.loads(fake.calls[0]["MessageBody"])["username"] == "alice"


def test_expiry_is_not_enforced_on_the_timeout_door(monkeypatch):
    """By construction the token IS expired — the timeout fires hours after it was minted.

    Pinned by which entry point is called, because calling the strict one would make this path
    notify nobody, ever, and it would look like it worked.
    """
    _arm()
    called = []
    monkeypatch.setattr(
        nf.auth,
        "verified_username_ignoring_expiry",
        lambda token, **kw: (called.append(token) or "alice"),
    )
    monkeypatch.setattr(
        nf.auth,
        "verified_username",
        lambda token, **kw: pytest.fail("the strict verifier would reject every timed-out run"),
    )

    nf.handler(_timeout_event(), None)

    assert called == ["token-for-alice"]


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"included": False}, "input omitted from the event"),
        ({"input_override": ""}, "no input at all"),
        ({"input_override": "{not json"}, "input is not JSON"),
        ({"input_override": "[]"}, "empty SQS batch"),
    ],
)
def test_an_unattributable_timeout_is_a_logged_no_op(monkeypatch, kwargs, why):
    """Nobody can be notified, so nobody is — never a message to a guessed inbox.

    EventBridge caps an event at 256 KB and Step Functions omits an input too large for it, so
    `included: false` is a real shape, not a hypothetical.
    """
    fake = _arm()
    _verified(monkeypatch)

    nf.handler(_timeout_event(**kwargs), None)

    assert fake.calls == [], f"notified someone despite {why}"


def test_a_malformed_detail_notifies_nobody_and_does_not_raise(monkeypatch):
    """Not raising is the assertion, and it is not politeness.

    ``_on_execution_timed_out`` does ``event.get("detail") or {}``, which passes a truthy
    non-dict straight through. An ``AttributeError`` on ``detail.get`` would surface as an
    async Lambda failure, and **EventBridge retries those twice** — turning one unattributable
    event into three invocations.
    """
    fake = _arm()
    _verified(monkeypatch)

    for detail in ("a string", ["a", "list"], 7):
        event = {**_timeout_event(), "detail": detail}
        assert nf.handler(event, None) == {}

    assert fake.calls == []


def test_an_unverifiable_token_notifies_nobody(monkeypatch):
    """A verification failure must not fall back to the body's own claim."""
    fake = _arm()

    def _reject(token, **kw):
        raise nf.TerminalError("unauthorized", "bad signature")

    monkeypatch.setattr(nf.auth, "verified_username_ignoring_expiry", _reject)

    nf.handler(_timeout_event(), None)

    assert fake.calls == []


def test_the_asl_door_still_works_and_the_two_cannot_double_notify(monkeypatch):
    """The doors are disjoint, and it matters: matching FAILED as well as TIMED_OUT would send
    a second notification for EVERY whole-request failure the Catch path already handles."""
    fake = _arm()

    nf.handler(_event({"Error": "States.Timeout"}), None)
    assert len(fake.calls) == 1, "the ASL door regressed"

    assert not nf._is_execution_timeout(_event({"Error": "States.Timeout"}))
    assert nf._is_execution_timeout(_timeout_event())


def test_the_rule_matches_timed_out_only_and_targets_this_notifier():
    """The infra half of the criterion, read from the deployed template.

    Two things would silently break it: matching FAILED too (a duplicate notification for every
    caught failure), and pointing the target at a different function.
    """
    import re

    tf = os.path.join(_HERE, "..", "..", "infra", "modules", "table-share", "stepfunction.tf")
    with open(tf) as handle:
        text = handle.read()

    assert re.search(r'status\s*=\s*\["TIMED_OUT"\]', text), "the rule no longer matches TIMED_OUT"
    assert '"FAILED"' not in text, "matching FAILED would double-notify every caught failure"
    assert re.search(
        r'aws_cloudwatch_event_target"\s+"execution_timed_out"\s*\{[^}]*functions\["notify-failure"\]',
        text,
        re.DOTALL,
    ), "the timeout rule does not target notify-failure"
    assert 'principal     = "events.amazonaws.com"' in text, "the rule cannot invoke the function"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
