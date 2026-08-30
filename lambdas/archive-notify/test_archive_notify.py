"""Unit tests for the archive notify Lambda (SPEC-172 FR-006).

The three ways an outcome producer goes wrong are saying the wrong thing, saying it to the wrong
person, and failing a run that had already succeeded because a message did not go out. The third
is the one that matters most here: on the archive arm the source is DELETED by the time this verb
runs. Runnable under pytest or directly: python3 test_archive_notify.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_notify as m
import pytest
from arcommon import notify

_ARCHIVE_ID = "3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93"


@pytest.fixture
def sent(monkeypatch):
    """Every message the producer emitted, as ``(recipient, body, link)``."""
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, dedup_id=None, link=None: captured.append(
            (user, message, link, dedup_id)
        ),
    )
    return captured


def _event(outcome, **overrides):
    base = {
        "outcome": outcome,
        "requestId": _ARCHIVE_ID,
        "actor": "alice",
        "space": {"kind": "personal", "name": "alice"},
        "objectCount": 12,
        "totalBytes": 3 * 1024**2,
    }
    return {**base, **overrides}


# ── archived ─────────────────────────────────────────────────────────────────


def test_the_archived_message_names_the_count_the_size_and_the_id(sent):
    """FR-006 AC3. The id is the load-bearing one: the archived objects sit in a bucket the
    browser has no relationship with, so it is the user's only route back to them."""
    m._notify(_event("archived"))

    user, message = sent[0][0], sent[0][1]
    assert user == "alice"
    assert "12 files" in message
    assert "3.0 MB" in message
    assert _ARCHIVE_ID in message


# ── restored ─────────────────────────────────────────────────────────────────


def test_the_restored_link_is_the_SPACE_ROOT_and_not_a_folder(sent):
    """A restore puts every object back where it came from, which for any selection of more than
    one folder is several places at once. Picking the first would send the user to a folder
    holding part of what they asked for."""
    m._notify(_event("restored"))

    assert sent[0][2] == "/files?prefix=alice/"


# ── the shape of the contract ────────────────────────────────────────────────


def test_exactly_one_message_is_sent_per_invocation(sent):
    """One notification per outcome (SPEC-114's rule). Two here would be two inbox rows for one
    event, which is the failure a per-verb producer creates."""
    for outcome in ("archived", "restore_started", "restored"):
        sent.clear()
        m._notify(_event(outcome))
        assert len(sent) == 1, outcome


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
