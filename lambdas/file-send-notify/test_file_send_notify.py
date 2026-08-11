"""Unit tests for the file-send notify Lambda (SPEC-167 FR-004/FR-005).

Who is told what, and who is NOT told: the three ways an outcome producer goes wrong are telling
the wrong person, telling somebody twice, and failing a delivered send because a message did not
go out. Runnable under pytest or directly: python3 test_file_send_notify.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_notify as m
import pytest
from cpcommon import clients
from cpcommon import config as cpconfig
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


def test_the_senders_message_names_the_recipient_and_what_was_sent(sent):
    m.handler(_summary([_ok()]), None)

    body = sent[0][1]
    assert 'user "bob"' in body
    assert '"reports"' in body and "301 files" in body


def test_the_recipients_message_names_the_sender_and_where_it_landed(sent):
    """The destination is the one thing the recipient cannot guess: a send arrives under
    ``shared_files/{sender}/``, which is not where they were last working."""
    m.handler(_summary([_ok()]), None)

    body = sent[1][1]
    assert body.startswith("alice sent you")
    assert "shared_files/alice/" in body


def test_the_recipients_link_carries_the_FULL_key_including_their_own_root(sent):
    """FR-005. ``FilesPage`` keeps a ``?prefix=`` only when it starts with the resolved space's
    rootPrefix, so a root-relative ``shared_files/{sender}/`` is silently discarded and the
    recipient lands at their space root with no idea why — a link that looks like it worked."""
    m.handler(_summary([_ok()]), None)

    assert sent[1][2] == "/files?prefix=bob/shared_files/alice/"


def test_a_space_recipient_is_announced_to_its_OWNER_only(sent):
    """Never its membership, matching table share. The owner's link carries ``?space=`` as well,
    or the browser resolves the personal space and discards the prefix for the same reason."""
    m.handler(_summary([_ok("space", "finance")]), None)

    assert [user for user, _m, _l in sent] == ["alice", "finance-owner"]
    assert sent[1][2] == "/files?space=finance&prefix=finance/shared_files/alice/"
    assert 'your space "finance"' in sent[1][1]


def test_a_space_with_no_resolvable_owner_still_tells_the_sender(sent, monkeypatch):
    """The two messages are independent, and the sender's is the one that always applies."""
    monkeypatch.setattr(notify.reg, "load", lambda name: None)

    m.handler(_summary([_ok("space", "finance")]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_failed_owner_lookup_does_not_take_the_senders_message_with_it(sent, monkeypatch):
    def _boom(name):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(notify.reg, "load", _boom)

    m.handler(_summary([_ok("space", "finance")]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_failed_recipient_is_told_NOTHING(sent):
    """They have no part in the send, nothing to do about it, and being told would leak that the
    sender tried. FR-005: a recipient failure notifies the sender only."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_FAILED_space_leaves_its_owner_untold_too(sent):
    """The owner path has its own branch, so the "a failed recipient is told nothing" rule is
    asserted on both kinds rather than on the easy one: a space whose copy failed must not
    announce an arrival to the person who owns it."""
    m.handler(_summary([_failed("copy_failed", kind="space", name="finance", failed_items=3)]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_partial_delivery_is_a_failure_and_nobody_is_told_it_arrived(sent):
    """A recipient short of even one object is ``failed`` upstream, and the rule that follows is
    the one that matters: they are not told a send arrived, because part of one did not."""
    m.handler(_summary([_failed("copy_failed", name="bob", failed_items=1)]), None)

    assert [user for user, _m, _l in sent] == ["alice"]
    assert "sent you" not in sent[0][1]


def test_a_conflict_names_the_recipient_AND_the_colliding_item(sent):
    """FR-004. The item name is the one piece of context the sender can act on — and it survives
    as a FIELD from the guard, which is why that verb returns its refusals rather than raising."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    body = sent[0][1]
    assert 'user "carol"' in body
    assert '"reports"' in body


@pytest.mark.parametrize(
    "reason", ["copy_failed", "unknown_user", "unknown_space", "transfer_results_unreadable"]
)
def test_every_other_outcome_says_what_happened_in_plain_words(sent, reason):
    m.handler(_summary([_failed(reason)]), None)

    body = sent[0][1]
    assert reason not in body
    assert body.startswith("Couldn't send to user \"carol\":")
    assert "{" not in body


def test_no_raw_aws_text_reaches_any_message(sent):
    """SPEC-106. The reason code is a domain code; nothing from the engine is interpolated."""
    m.handler(_summary([_ok(), _failed("copy_failed", name="dave")]), None)

    for _user, body, _link in sent:
        assert "arn:aws" not in body and "s3://" not in body


def test_one_message_per_outcome_and_never_two_about_one(sent):
    """The reason no verb upstream emits: every per-recipient outcome reaches one flat list, so
    saying each thing once from one place is possible — and a decorator on the guard would make a
    conflict two messages."""
    m.handler(_summary([_ok("user", "bob"), _failed("conflict", name="carol", detail="reports")]), None)

    to_sender = [body for user, body, _l in sent if user == "alice"]
    assert len(to_sender) == 2
    assert len(set(to_sender)) == 2


def test_a_summary_with_nothing_in_it_is_a_no_op_rather_than_an_error(sent):
    """Not reachable through validate-authorize, which refuses an empty recipient list. Inventing
    a failure here would fail a send that had already worked."""
    assert m.handler(_summary([], sender=""), None)["requestId"] == "req-1"
    assert sent == []


def test_the_summary_is_threaded_onward_unchanged(sent):
    """The execution's output stays the terminal the machine shaped, not whatever this verb
    happened to return."""
    summary = _summary([_ok()])

    assert m.handler(summary, None) == summary


def test_one_bad_outcome_does_not_cost_the_others_their_message(sent, monkeypatch):
    """The emit already swallows, but composing a message and minting a link do not — and one
    raise partway through would drop every remaining recipient while the execution still
    succeeded through the state's Catch: nothing notified and nothing recorded."""
    real = notify.received_files_link

    def _explode(kind, name, sender):
        if name == "bob":
            raise RuntimeError("unanticipated")
        return real(kind, name, sender)

    monkeypatch.setattr(notify, "received_files_link", _explode)

    m.handler(_summary([_ok("user", "bob"), _ok("user", "carol")]), None)

    assert "carol" in [user for user, _m, _l in sent]


def test_a_non_dict_event_does_not_raise(sent):
    assert m.handler(None, None) == {}


def test_a_broken_QUEUE_never_fails_the_send(monkeypatch):
    """The property the missing decorator exists for, exercised through the REAL emitter rather
    than by replacing it: ``cpcommon.notify.emit_notification`` catches, logs and never raises,
    and this drives the whole handler with an SQS client that throws.

    By the time this verb runs the copy has happened and the execution is otherwise successful,
    so a raise here would replace a delivered send with a failed one — and the machine's Catch on
    this state goes to Succeeded for the same reason.
    """

    class _BrokenSqs:
        def __init__(self):
            self.attempts = 0

        def send_message(self, **kwargs):
            self.attempts += 1
            raise RuntimeError("SQS is down")

    broken = _BrokenSqs()
    monkeypatch.setattr(clients, "_sqs", broken)
    monkeypatch.setattr(cpconfig, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/q.fifo")

    assert m.handler(_summary([_ok()]), None)["requestId"] == "req-1"
    assert broken.attempts == 2, (
        "the producer stopped trying rather than swallowing — this test would pass against one "
        "that emitted nothing at all"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
