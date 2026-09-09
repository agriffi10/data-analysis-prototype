"""Unit tests for the file-send notify Lambda (SPEC-167 FR-004/FR-005).

Who is told what, and who is NOT told: the three ways an outcome producer goes wrong are telling
the wrong person, telling somebody twice, and failing a delivered send because a message did not
go out.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_notify as m
import pytest
from fscommon import notify


@pytest.fixture
def sent(monkeypatch):
    """Every message the producer emitted, as ``(recipient, body, link)``."""
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, dedup_id=None, link=None: captured.append((user, message, link)),
    )
    return captured


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    """A registry whose spaces have an owner, unless a test says otherwise."""
    monkeypatch.setattr(notify.reg, "load", lambda name: {"owner": f"{name}-owner"})


def _ok(kind="user", name="bob"):
    return {"kind": kind, "name": name, "status": "ok", "reason": "", "detail": "", "failedItems": 0}


def _failed(reason, kind="user", name="carol", detail="", failed_items=0):
    return {
        "kind": kind,
        "name": name,
        "status": "failed",
        "reason": reason,
        "detail": detail,
        "failedItems": failed_items,
    }


def _summary(recipients, sender="alice", item_names=("reports", "notes.txt"), objects=301):
    return {
        "requestId": "req-1",
        "sender": sender,
        "itemNames": list(item_names),
        "objectCount": objects,
        "recipients": recipients,
    }


def test_a_delivered_send_tells_the_sender_and_the_recipient(sent):
    m.handler(_summary([_ok()]), None)

    assert [user for user, _m, _l in sent] == ["alice", "bob"]


def test_a_failed_recipient_is_told_NOTHING(sent):
    """They have no part in the send, nothing to do about it, and being told would leak that the
    sender tried. FR-005: a recipient failure notifies the sender only."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_conflict_names_the_recipient_AND_the_colliding_item(sent):
    """FR-004. The item name is the one piece of context the sender can act on — and it survives
    as a FIELD from the guard, which is why that verb returns its refusals rather than raising."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    body = sent[0][1]
    assert 'user "carol"' in body
    assert '"reports"' in body
