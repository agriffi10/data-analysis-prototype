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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
