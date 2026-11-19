"""Unit tests for file-ops notify-failure (the spec on this plane).

This is the notification of last resort — the one that fires when no verb's decorator could,
because no verb code ran. The tests that matter are the three ways it can go wrong: telling
nobody when it should, telling somebody twice, and telling the wrong person.
"""

import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import asl_failure_path
import fo_notify_failure as n
from token_shapes import JWT_SHAPED


def _capture():
    sent = []
    n.notify.emit_notification = lambda user, message, **kw: sent.append((user, message))
    return sent


def _payloads():
    sent = []
    n.notify.emit_notification = lambda user, message, **kw: sent.append(kw.get("payload"))
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


_JWT = JWT_SHAPED


def _raw(actor="alice", identity=True):
    """The Pipe's forwarded batch, as the failure seed reads it from $$.Execution.Input.

    The flat ``actor`` carries the raw token that a message enqueued before the API stopped
    sending one still has, and is kept here for that reason: the recovery must come from the
    block beside it, and dropping the field would stop this fixture proving so.

    Args:
      actor: The verified username the identity block names.
      identity: Whether to carry the block at all — False is the pre-cutover envelope.

    Returns:
      The forwarded SQS batch.

    Raises:
      None.
    """
    body = {"requestId": "req-1", "actor": _JWT}
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    return [{"body": json.dumps(body)}]


def test_an_engine_failure_notifies_the_actor():
    sent = _capture()

    n.handler(_request({"Error": "States.Timeout", "Cause": None}), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"


def test_a_reused_request_id_a_verb_raised_is_told_to_nobody_here_either(caplog):
    """The verb's decorator keeps this reason quiet because the run holding the id reports, and
    this state is the other half of that silence: it drops every ``TerminalError`` as already
    handled. Were it to let this one through, its ``{requestId}`` row would settle the browser's
    card as a refusal for an operation that may have finished.

    The engine failure after it is the positive control: the same actor IS told.
    """
    sent = _capture()
    reused = {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorType": "TerminalError", "errorMessage": "request_id_reused: another run's plan"}
        ),
    }

    with caplog.at_level(logging.INFO):
        n.handler(_request(reused), None)
    silent = list(sent)
    n.handler(_request({"Error": "States.Timeout", "Cause": None}), None)

    assert silent == []
    assert "request_id_reused is told to nobody" in caplog.text
    assert [user for user, _ in sent] == ["alice"]


def test_the_actor_is_recovered_from_the_request_when_no_verb_produced_one():
    """THE CASE THIS STATE ACTUALLY SEES. Every failure it exists for — a cold-start import
    error, a state timeout, a task that could not be invoked — happens before an actor exists,
    so the recorded object carries actor: null. Recovering the actor from the identity block
    in the captured request is the difference between "every failure notifies" holding here and
    reading as satisfied while telling nobody anything."""
    sent = _capture()

    n.handler(_request({"Error": "RuntimeError", "Cause": "ModuleNotFoundError"}, actor=None, raw=_raw()), None)

    assert [user for user, _ in sent] == ["alice"]


def test_the_door_degrades_when_the_request_carries_no_identity_block():
    """The pre-cutover envelope, and the one shape this door must NOT raise on.

    A raise here is an async Lambda failure EventBridge retries, so one unattributable event
    becomes three. The honest outcome is a logged no-op and no notification: there is no
    trustworthy recipient, and the flat ``actor`` beside the missing block is a raw token.
    """
    sent = _capture()

    n.handler(_request({"Error": "RuntimeError", "Cause": None}, actor=None, raw=_raw(identity=False)), None)

    assert sent == []


# ── The timeout door: the second door ────────────────────────────────────────


def _timed_out(input_json=None, included=True):
    """An EventBridge Step Functions status-change event for a timed-out execution.

    The execution's input is what the Pipe forwarded — the raw SQS batch — so the actor comes
    from the identity block in it, exactly as the ASL door's fallback does.
    """
    detail = {"status": "TIMED_OUT", "inputDetails": {"included": included}}
    if input_json is not None:
        detail["input"] = input_json
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def test_a_timed_out_execution_notifies_the_actor():
    """The failure the ASL door CANNOT reach. Step Functions catchers cover Task, Parallel and
    Map states but not top-level execution failures, so a run that exhausts TimeoutSeconds is
    terminated outright: no state runs, no Catch fires, and without this door the actor is told
    nothing at all — the exact silence the spec exists to close."""
    sent = _capture()

    n.handler(_timed_out(json.dumps(_raw())), None)

    assert len(sent) == 1
    assert sent[0][0] == "alice"


@pytest.mark.parametrize(
    "event",
    [
        _request({"Error": "States.Timeout", "Cause": None}),
        {**_request({"Error": "Runtime.ImportModuleError", "Cause": None}, actor=None, raw=_raw()), "requestId": None},
        _timed_out(json.dumps(_raw())),
    ],
    ids=["id-on-the-state", "seed-nulled-the-id", "timeout-door"],
)
def test_every_door_names_the_request_id_the_browser_is_waiting_on(event):
    """The browser settles its in-flight card by matching ``payload.requestId``, and nothing
    reaches the outcome producer after a failure lands here — so a message without it leaves the
    card, and the space's submit gate, held until the card's own expiry.

    The second case is the one a top-level read misses: a validator fault replaces the state, so
    the seed nulls the id and only the forwarded request beside it still names the run.
    """
    sent = _payloads()

    n.handler(event, None)

    assert sent == [{"requestId": "req-1"}]


# ── A fault after the copy began ─────────────────────────────────────────────


def _running(operation="copy", target_name=None, prefix="alice/out/", stage=None):
    """The running request object and the execution input a fault on the failure path carries.

    Args:
      operation: The request's operation.
      target_name: The one item's new name, for a rename-shaped request.
      prefix: The destination folder.
      stage: The mark ``BeginTransfer``/``BeginDeletion`` leave on a run that reached them.

    Returns:
      ``(state, execution_input)``: the request as validate-authorize shaped it, and the Pipe's
      batch carrying the request as the browser sent it.
    """
    item = {"kind": "file", "key": "alice/in/a.csv"}
    if target_name:
        item["targetName"] = target_name
    space = {"kind": "personal", "name": "alice"}
    state = {
        "traceparent": None,
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "source": {**space, "bucket": "user-bkt", "root": "alice/", "items": [item]},
        "destination": {**space, "bucket": "user-bkt", "root": "alice/", "prefix": prefix},
    }
    if stage:
        state["stage"] = stage
    body = json.loads(_raw()[0]["body"])
    body.update(
        operation=operation,
        source={"space": space, "items": [item]},
        destination={"space": space, "prefix": prefix},
    )
    return state, [{"body": json.dumps(body)}]


def _fault_in(state_name, operation="copy", target_name=None, prefix="alice/out/", stage=None):
    """What this notifier receives when ``state_name`` fails with a fault no verb classified.

    Args:
      state_name: The state whose Catch fires.
      operation: The request's operation.
      target_name: The one item's new name, for a rename-shaped request.
      prefix: The destination folder.
      stage: The mark the run carries, as the machine left it on the way to that state.

    Returns:
      The notifier's input, walked through the plane's own failure path.
    """
    state, execution_input = _running(operation, target_name, prefix, stage)
    return asl_failure_path.notify_failure_input(
        "file-ops", state_name, state, {"Error": "RuntimeError", "Cause": "boom"}, execution_input
    )


@pytest.mark.parametrize(
    "state_name", ["TransferObjects", "CollectTransferResults", "DeleteSource", "FinaliseOutcomes"]
)
def test_a_fault_after_the_copy_began_says_some_of_it_may_have_happened(state_name):
    """The machine's mark reaches this notifier, and the notice stops promising a clean retry.

    A retry after a partial copy collides with what landed, so the notice must say to look first.
    """
    sent = _capture()

    n.handler(_fault_in(state_name, stage="transfer"), None)

    assert sent == [
        (
            "alice",
            (
                "Couldn't copy that: something went wrong part-way through, so some of it may "
                "have happened and some may not. Please look at the folder before trying again."
            ),
        )
    ]


@pytest.mark.parametrize("state_name", ["InspectSource", "CollectTransferResults"])
def test_a_fault_in_a_run_that_changed_nothing_keeps_todays_sentence(state_name):
    """Before the copy, and in a run with nothing to copy, which reaches CollectTransferResults
    without passing BeginTransfer — every item refused, say. Nothing happened, so nothing is said
    to have."""
    sent = _capture()

    n.handler(_fault_in(state_name), None)

    assert sent == [("alice", "Couldn't copy that: something went wrong.")]


def test_the_verb_and_this_notifier_send_one_body_for_one_fault_after_the_copy():
    """Both doors notify an unexpected in-verb fault; after the copy began they compose the same
    body, so the notifications queue's content dedup can collapse the pair into one."""
    seen = []
    n.notify.emit_notification = lambda user, message, **kw: seen.append((user, message, kw))
    state, _ = _running(stage="transfer")

    @n.notify.notifies_on_failure("collect-transfer-results")
    def faulting(event, context):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        faulting(state, None)
    n.handler(_fault_in("CollectTransferResults", stage="transfer"), None)

    assert len(seen) == 2
    (verb_user, verb_message, verb_kw), (door_user, door_message, door_kw) = seen
    assert (verb_user, verb_message, verb_kw.get("payload")) == (
        door_user,
        door_message,
        door_kw.get("payload"),
    )
    assert "may have happened" in verb_message
    assert verb_kw.get("link") is None and door_kw.get("link") is None


def test_a_superseded_plan_after_the_copy_does_not_say_nothing_was_changed():
    sent = []
    n.notify.emit_notification = lambda user, message, **kw: sent.append(message)
    before, _ = _running(operation="move")
    after, _ = _running(operation="move", stage="transfer")

    @n.notify.notifies_on_failure("delete-source")
    def superseded(event, context):
        raise n.TerminalError("plan_superseded", "another run's plan")

    for state in (before, after):
        with pytest.raises(n.TerminalError):
            superseded(state, None)

    assert sent == [
        (
            "Couldn't move that: another request for that space was already in flight. Nothing "
            "was changed. Please try again."
        ),
        (
            "Couldn't move that: another request for that space got in the way part-way through, so "
            "some of it may have happened and some may not. Please look at the folder before trying "
            "again."
        ),
    ]


# ── A rename is told as a rename ─────────────────────────────────────────────


def test_a_failed_rename_is_told_as_a_rename_and_a_move_with_a_new_name_elsewhere_is_not():
    """A rename is a move of one item with a new name into the folder it already sits in; a
    hand-built move that also renames into ANOTHER folder did move something."""
    sent = _capture()

    n.handler(_fault_in("InspectSource", "move", target_name="b.csv", prefix="alice/in/"), None)
    n.handler(_fault_in("InspectSource", "move", target_name="b.csv", prefix="alice/out/"), None)

    assert [message for _, message in sent] == [
        "Couldn't rename that: something went wrong.",
        "Couldn't move that: something went wrong.",
    ]
