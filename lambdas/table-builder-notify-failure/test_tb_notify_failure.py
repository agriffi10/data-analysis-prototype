"""Unit tests for the table-builder notify-failure handler (SPEC-152 FR-002/FR-004).

The state this covers fires when NO VERB CODE RAN — a Lambda import failure, a Step
Functions-level error — so its input is whatever RecordFailure could shape, and its job is
to still put a friendly sentence in the actor's inbox.

Every assertion is on the NOTIFICATION BODY the user would receive rather than on a mock's
call args (FR-004): what is being protected is what the message says, and a test that
pins the arguments passes just as happily when the wording is wrong.
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


# ── The EventBridge door: a run the machine's own TimeoutSeconds stopped ───────


def _timed_out(body):
    """An EventBridge status-change event carrying the Pipe's forwarded SQS batch."""
    return {
        "detail-type": "Step Functions Execution Status Change",
        "detail": {
            "status": "TIMED_OUT",
            "inputDetails": {"included": True},
            "input": json.dumps([{"body": json.dumps(body)}]),
        },
    }


def test_a_timed_out_execution_notifies_the_actor_from_the_identity_block():
    """The paired positive. Without it the refusal below would pass just as happily with the
    door notifying nobody at all, which is the state this plane shipped in."""
    fake = _arm()
    nf.handler(
        _timed_out(
            {
                "identity": {"actor": "alice", "delegated_by": None, "assurance": "interactive"},
                "requestId": "r-1",
                "tableName": "sales",
                "space": {"database": "alice"},
                "mode": "create",
            }
        ),
        None,
    )
    message = fake.messages()[0]
    assert len(fake.calls) == 1
    assert 'Couldn\'t create table "sales"' in message
    assert "ran for too long" in message
    assert "Nothing was changed" not in message
    assert "may or may not" in message
    assert "few minutes" in message


def test_a_timed_out_refresh_says_refresh():
    """The mode picks the verb, and this layer's own docstring calls getting it wrong worse
    than generic. A create-only line would tell a user they cannot create the table they were
    refreshing — and the mode survives only because the door reads it off the body."""
    fake = _arm()
    nf.handler(
        _timed_out(
            {
                "identity": {"actor": "alice", "delegated_by": None, "assurance": "interactive"},
                "requestId": "r-2",
                "tableName": "sales",
                "space": {"database": "alice"},
                "mode": "refresh",
            }
        ),
        None,
    )
    assert 'Couldn\'t refresh table "sales"' in fake.messages()[0]


def test_a_timed_out_execution_with_no_identity_block_notifies_nobody():
    """The door cannot raise: a raise is an async Lambda failure and EventBridge retries those,
    turning one unattributable event into three. It must also refuse to fall back to the
    producer-supplied top-level actor, which is the field the identity block replaced."""
    fake = _arm()
    nf.handler(_timed_out({"actor": "mallory", "tableName": "sales"}), None)
    assert fake.calls == []


def test_the_timeout_sentence_repairs_its_own_prefix_and_names_the_wait():
    """Two clauses, each answering a way the plain sentence would be false.

    The resolver's prefix says "Couldn't create table" and that alone is wrong: ExecuteDdl runs
    before the deadline, and the verbs emit their SUCCESS notification inline with ReleaseRefreshLock
    and RecordSuccess still to run — so a timeout in that tail window sends "ready to query" and this
    message for one run, and only "may or may not" keeps the pair coherent.

    And a top-level timeout runs neither lock release, so the lock is stranded until
    STALE_LOCK_SECONDS. Without the wait clause the advice earns a refresh_already_running refusal
    claiming a refresh "is already running" when nothing is.
    """
    from tbcommon import messages as m
    from tbcommon.table_lock import MACHINE_TIMEOUT_SECONDS, STALE_LOCK_SECONDS

    assert STALE_LOCK_SECONDS > MACHINE_TIMEOUT_SECONDS, (
        "the wait clause is only honest while the lock outlives the machine timeout"
    )
    for mode, verb in (("create", "create"), ("refresh", "refresh")):
        text = m.failure_message("build_timed_out", "sales", "alice", mode)
        assert f'Couldn\'t {verb} table "sales"' in text
        assert "may or may not" in text, "the prefix asserts the build did not happen; repair it"
        assert "few minutes" in text, "a stranded lock makes an immediate retry fail"


def test_an_omitted_input_notifies_nobody():
    """inputDetails.included is False is EventBridge dropping an oversized input, not a bug.

    Distinct from a missing key: the field is present and false, which the door must read rather
    than treating the absent `input` as merely falsy.
    """
    fake = _arm()
    nf.handler(
        {
            "detail-type": "Step Functions Execution Status Change",
            "detail": {"status": "TIMED_OUT", "inputDetails": {"included": False}, "input": ""},
        },
        None,
    )
    assert fake.calls == []


def test_a_non_string_table_name_does_not_raise():
    """A raise here is an async Lambda failure EventBridge retries, turning one malformed body
    into three notifications. failure_message reaches str.replace, which raises TypeError on a
    non-string whether or not the marker occurs — so the leaves are narrowed, not just the space."""
    fake = _arm()
    nf.handler(
        _timed_out(
            {
                "identity": {"actor": "alice", "delegated_by": None, "assurance": "interactive"},
                "requestId": "r-3",
                "tableName": {"not": "a string"},
                "space": {"database": ["nor", "this"]},
                "mode": "create",
            }
        ),
        None,
    )
    assert len(fake.calls) == 1
    assert "may or may not" in fake.messages()[0]
