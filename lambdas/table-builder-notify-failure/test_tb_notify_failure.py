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


def test_a_prose_cause_still_notifies_and_leaks_nothing():
    """States.DataLimitExceeded / Lambda.Unknown carry a plain sentence, not JSON."""
    fake = _arm()
    nf.handler(
        _event({"Error": "Lambda.Unknown", "Cause": "Unhandled error: RequestEntityTooLarge"}),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert "RequestEntityTooLarge" not in message
    assert "Lambda.Unknown" not in message


def test_an_exhausted_transient_retry_now_notifies():
    """A GAP THIS SPEC CLOSES, not a coincidence. @notifies_on_failure passes a
    TransientError through UN-notified on purpose — a retry was still pending when the
    decorator saw it. When the Retry list is exhausted the execution fails anyway, and
    before SPEC-152 nothing told the user."""
    fake = _arm()
    nf.handler(_event({"Error": "TransientError", "Cause": "listing objects"}), None)
    assert len(fake.calls) == 1
    assert "listing objects" not in fake.messages()[0]


# ── The duplicate a verb already sent (FR-002) ────────────────────────────────


def test_a_verbs_own_terminal_error_is_suppressed():
    """The decorator already notified, with a BETTER message: it carries err.tokens, which
    this path cannot reconstruct."""
    fake = _arm()
    nf.handler(_event(_terminal_cause("table_exists")), None)
    assert fake.calls == []


def test_the_suppression_covers_the_decorators_generic_emit_too():
    """An unexpected (non-Terminal) exception notifies through emit_unexpected. Lambda
    reports it under its BARE class name, which is the same evidence that a handler ran."""
    fake = _arm()
    nf.handler(_event({"Error": "ClientError", "Cause": "An error occurred (AccessDenied)"}), None)
    assert fake.calls == []


def test_an_engine_name_is_never_mistaken_for_a_verb_exception():
    """The whole discriminator in one assertion: a dot means the engine named it, and no
    handler code ran. If this ever inverts, every pre-verb failure goes silent again —
    which is the bug SPEC-152 exists to fix."""
    for engine in ("States.Timeout", "States.DataLimitExceeded", "Lambda.Unknown",
                   "Runtime.ImportModuleError", "Lambda.ServiceException"):
        fake = _arm()
        nf.handler(_event({"Error": engine}), None)
        assert len(fake.calls) == 1, f"{engine} was suppressed as if a verb had notified"


def test_columns_removed_is_suppressed_so_the_named_columns_are_not_lost():
    """THE CASE THAT MAKES SUPPRESSION LOAD-BEARING RATHER THAN TIDY. SPEC-144's refusal
    IS the warning, and it is only useful because it names the columns — which live in
    err.tokens and reach the decorator's emit alone. A second, generic message here would
    be the one the user reads last."""
    fake = _arm()
    nf.handler(_event(_terminal_cause("columns_removed")), None)
    assert fake.calls == []


# ── The plane's own vocabulary (FR-002) ───────────────────────────────────────


def test_a_refresh_failure_does_not_say_create():
    """RecordFailure carries $.mode for exactly this. Telling a user they can't CREATE a
    table they were trying to REFRESH is about the most confusing thing this layer can
    say (tbcommon.messages)."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, mode="refresh"), None)
    message = fake.messages()[0]
    assert 'Couldn\'t refresh table "sales"' in message
    assert "create" not in message


def test_an_absent_mode_reads_as_create():
    fake = _arm()
    event = _event({"Error": "States.Timeout"})
    del event["mode"]
    nf.handler(event, None)
    assert 'Couldn\'t create table "sales"' in fake.messages()[0]


def test_the_message_names_the_table():
    """A user who started three builds cannot act on 'your table failed'."""
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}, table="q3_returns"), None)
    assert "q3_returns" in fake.messages()[0]


def test_the_dedup_id_is_one_token_per_outcome():
    fake = _arm()
    nf.handler(_event({"Error": "States.Timeout"}), None)
    assert fake.calls[0]["MessageDeduplicationId"] == "r-1:failure"
    assert fake.calls[0]["MessageGroupId"] == "alice"


# ── Recipient trust (FR-002, the SPEC-126 rule) ───────────────────────────────


def test_a_pre_identity_failure_never_falls_back_to_a_body_supplied_username():
    """ValidateFailureSeed seeds actor=null for a garbage token, and the ONLY trustworthy
    recipient field is `actor` — which the state machine sets from the verified claim.

    THIS ASSERTS THE FALLBACK, NOT THE EMPTY SEND. `emit_notification` already no-ops on an
    empty username, so a version of this test that merely dropped `actor` would pass even
    if the handler's own guard were deleted — it would be measuring cpcommon's guard. The
    failure that matters is a handler reaching for some OTHER field, which would let anyone
    who can enqueue deliver text to any inbox. So the event carries plausible
    attacker-controlled alternatives and none of them may be used.
    """
    fake = _arm()
    event = _event({"Error": "States.Timeout"}, actor=None)
    event["username"] = "victim"
    event["user"] = "victim"
    event["requestedBy"] = "victim"
    nf.handler(event, None)
    assert fake.calls == [], "a recipient was derived from something other than `actor`"


# ── Totality: it never raises, whatever it is handed (FR-002) ─────────────────


def test_every_malformed_error_payload_still_notifies():
    """A malformed or absent error must produce a message, not an exception: the execution
    has already failed and this is the user's only channel."""
    for shape in (None, {}, "a string", 7, [], {"Cause": "no Error key"}):
        fake = _arm()
        nf.handler(_event(shape), None)
        assert len(fake.calls) == 1, f"no notification for error payload {shape!r}"
        assert "something went wrong" in fake.messages()[0].lower()


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


# ── The instrumentation rules (FR-002) ────────────────────────────────────────


def test_traced_is_the_outermost_and_only_decorator():
    """@notifies_on_failure would be circular on the notification of last resort."""
    import inspect

    source = inspect.getsource(nf)
    assert '@observability.traced("notify-failure")' in source
    assert "@notify.notifies_on_failure" not in source


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
