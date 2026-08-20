"""Choosing the wording by the operation, on the path where everything else has already failed.

Every other plane has one verb and so one prefix. This one serves three, and the emitters run
where the request may be malformed enough that its operation is missing or the wrong type — so the
lookup has to be defensive without being silent.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon.errors import TerminalError
from focommon import notify


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    log = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: log.append((user, text)))
    return log


def _pipe(operation="delete"):
    return [{"body": json.dumps({"requestId": "r", "actor": "tok", "operation": operation})}]


def test_the_operation_is_read_from_the_running_event():
    assert notify.operation_of({"operation": "move"}) == "move"


def test_the_operation_is_recovered_from_the_PIPE_BATCH_when_the_event_lost_it():
    """The pre-identity failure path carries the original request under `raw` and nowhere else —
    the recorded failure has no `operation` of its own, so without this every early failure would
    be worded as a copy."""
    assert notify.operation_of({"raw": _pipe("delete")}) == "delete"


@pytest.mark.parametrize(
    "event",
    [None, "string", {}, {"operation": 3}, {"raw": "not-a-list"}, {"raw": []}, {"raw": [{"body": "{"}]}],
)
def test_an_unrecoverable_operation_is_None_rather_than_a_raise(event):
    """These emitters run on the failure path. Raising here would replace a friendly sentence with
    an unhandled error on the one path whose whole job is reporting a failure."""
    assert notify.operation_of(event) is None


def test_each_operation_gets_its_own_sentence(sent):
    for operation in ("copy", "move", "delete"):
        notify.emit_failure(
            {"actor": {"username": "alice"}, "operation": operation},
            TerminalError("marker_not_deletable", "operator text"),
            "validate",
        )

    assert [text.split(":")[0] for _, text in sent] == [
        "Couldn't copy that",
        "Couldn't move that",
        "Couldn't delete that",
    ]


def test_the_operator_DETAIL_never_reaches_the_user(sent):
    """A detail can quote a folder name the actor supplied and exists for the logs and the Step
    Functions record. Tokens are the opposite channel — values a raise site provides precisely
    because a body names a marker for them."""
    notify.emit_failure(
        {"actor": {"username": "alice"}, "operation": "copy"},
        TerminalError("marker_not_deletable", "alice/secret-project/DO_NOT_DELETE.txt"),
        "validate",
    )

    assert "secret-project" not in sent[0][1]


def test_a_token_DOES_reach_the_user_where_a_body_names_one(sent):
    notify.emit_failure(
        {"actor": {"username": "alice"}, "operation": "copy"},
        TerminalError("colliding_item_names", "x.csv", tokens={"itemName": "x.csv"}),
        "validate",
    )

    assert '"x.csv"' in sent[0][1]


def test_an_unexpected_exception_gets_the_generic_sentence_and_leaks_nothing(sent):
    """The path the acquire verb's decorator takes, and the one nothing else exercised."""
    notify.emit_unexpected({"actor": {"username": "alice"}, "operation": "move"}, "acquire-lock")

    assert sent[0][0] == "alice"
    assert sent[0][1].startswith("Couldn't move that: ")
    assert "Traceback" not in sent[0][1] and "Error" not in sent[0][1]


def test_a_failure_with_no_bound_actor_is_a_no_op_rather_than_a_lost_message(sent):
    """The body's own actor field is attacker-controlled; notifying it would let anyone deliver
    text to any inbox."""
    notify.emit_unexpected({"operation": "copy"}, "validate")

    assert sent == [] or sent[0][0] == ""
