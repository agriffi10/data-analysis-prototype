"""Unit tests for the file-operations notify Lambda.

Three ways an outcome producer goes wrong: telling the wrong person, telling somebody twice, and
failing a completed operation because a message did not go out. The third is the one that matters
most here — by the time this verb runs, a ``move`` has already deleted its sources.

Runnable under pytest or directly: python3 test_file_ops_notify.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_notify as m
import pytest
from focommon import notify


@pytest.fixture
def sent(monkeypatch):
    """Every message the producer emitted, as ``(recipient, body, kwargs)``."""
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, **kwargs: captured.append((user, message, kwargs)),
    )
    return captured


def _terminal(records=None, operation="move"):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "summary": {
            "operation": operation,
            "source": {"kind": "personal", "name": "alice"},
            "destination": {"kind": "personal", "name": "alice", "prefix": "alice/out/"},
            "items": [{"itemKey": "alice/reports/", "kind": "folder", "targetName": None}],
            "counts": [{"itemKey": "alice/reports/", "objects": 12, "failed": 0}],
        },
        "outcomes": records
        if records is not None
        else [{"itemKey": "alice/reports/", "label": "reports", "outcome": "moved"}],
    }


def test_one_message_names_the_actor_the_run_and_where_the_result_is(sent):
    m.handler(_terminal(), None)

    assert len(sent) == 1
    user, message, kwargs = sent[0]
    assert user == "alice"
    assert message == 'Moved 1 item to "out".'
    assert kwargs["link"] == "/files?prefix=alice/out/"
    assert kwargs["payload"]["requestId"] == "req-1"


def test_the_terminal_is_threaded_onward_UNCHANGED(sent):
    """The execution's output stays what the machine shaped rather than whatever this verb
    happened to return — the state carries ``ResultPath: null`` for the same reason."""
    terminal = _terminal()

    assert m.handler(terminal, None) == terminal


def test_a_message_that_cannot_be_composed_never_fails_the_RUN(monkeypatch, sent):
    """THE PROPERTY THIS VERB EXISTS UNDER. ``emit_notification`` already swallows, but composing
    the sentence, minting the link and building the payload do not — and by the time any of them
    runs, a move has already deleted its sources. A raise here would report a completed operation
    as a failed one."""
    monkeypatch.setattr(notify, "emit_outcomes", _explode)
    terminal = _terminal()

    assert m.handler(terminal, None) == terminal


def _explode(_event):
    raise RuntimeError("the wording blew up")


def test_a_terminal_with_no_outcomes_is_a_LOGGED_NO_OP_rather_than_an_invented_failure(sent):
    """Unreachable through the finaliser, which returns a record per selected item. Inventing a
    failure here would report a completed operation as a broken one."""
    assert m.handler(_terminal(records=[]), None) == _terminal(records=[])
    assert sent == []


def test_a_mixed_run_produces_ONE_message_naming_both_halves(sent):
    """Not one message per item: a selection at the item cap would flood an inbox capped at 200
    rows and read whole on every poll."""
    m.handler(
        _terminal(
            records=[
                {"itemKey": "alice/reports/", "label": "reports", "outcome": "moved"},
                {
                    "itemKey": "alice/q1.csv",
                    "label": "q1.csv",
                    "outcome": "conflict",
                    "reason": "destination_occupied",
                    "sample": ["out/q1.csv"],
                },
            ]
        ),
        None,
    )

    assert len(sent) == 1
    message = sent[0][1]
    assert "Moved 1 of 2 items" in message and '"q1.csv"' in message


def test_the_producer_reads_the_STATE_and_opens_no_client(monkeypatch, sent):
    """It reads no plan and no results document, and that is a constraint rather than an
    observation: a verb that held the plan would join the set whose smallest memory sizes the
    object cap, shrinking a cap that has nothing to do with notifying."""
    from cpcommon import clients

    monkeypatch.setattr(clients, "s3", _no_client)
    m.handler(_terminal(), None)

    assert len(sent) == 1


def _no_client():
    raise AssertionError("the producer opened an S3 client")


def test_the_module_never_reaches_for_the_plan():
    """Asserted on the SOURCE as well as by behaviour, because a plan read on a branch this suite
    does not take would still shrink the cap."""
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_ops_notify.py")
    with open(source) as handle:
        text = handle.read()

    assert "plan.load" not in text and "plan.write" not in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
