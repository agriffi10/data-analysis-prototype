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
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
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
        lambda user, message, dedup_id=None, link=None: captured.append((user, message, link)),
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

    user, message, _ = sent[0]
    assert user == "alice"
    assert "12 files" in message
    assert "3.0 MB" in message
    assert _ARCHIVE_ID in message


def test_the_archived_message_says_the_files_have_left_the_space(sent):
    """The consequence a button label cannot carry, and the one thing a user reading this
    message hours later needs to be sure of."""
    m._notify(_event("archived"))

    assert "removed from your space" in sent[0][1]


def test_the_archived_link_lands_in_the_folder_holding_the_receipt(sent):
    """The prefix is the FULL KEY including the space root: FilesPage keeps a `?prefix=` only
    when it starts with the resolved space's own root, so a root-relative one is silently
    discarded and the user lands at their space root with no idea why."""
    m._notify(_event("archived"))

    assert sent[0][2] == f"/files?prefix=alice/archive/{_ARCHIVE_ID}/"


def test_a_shared_space_link_carries_the_space_query(sent):
    """Without it the route resolves the PERSONAL space and then discards a prefix that does not
    start with it — landing the user in their own files while the message says otherwise."""
    m._notify(_event("archived", space={"kind": "shared", "name": "finance"}))

    assert sent[0][2] == f"/files?space=finance&prefix=finance/archive/{_ARCHIVE_ID}/"


def test_a_link_that_cannot_be_built_is_omitted_rather_than_guessed(sent):
    """FR-006 AC6. The notification still says what happened; it just cannot offer a link."""
    m._notify(_event("archived", space={"kind": "personal", "name": "../evil"}))

    _, message, link = sent[0]
    assert link is None
    assert _ARCHIVE_ID in message


# ── restore_started ──────────────────────────────────────────────────────────


def test_the_started_message_states_the_duration_and_promises_a_second_one(sent):
    """FR-006 AC2. The only START notification in this app, and the reason is that three to five
    hours of silence is indistinguishable from a request that was dropped."""
    m._notify(_event("restore_started"))

    _, message, link = sent[0]
    assert "several hours" in message
    assert "another notification" in message
    assert link is None


def test_the_started_message_says_nothing_has_changed_yet(sent):
    """The guard has passed and the retrieval is running, but not one byte has moved into the
    user's space — and a user who went looking would find exactly what was there before."""
    m._notify(_event("restore_started"))

    assert "Nothing has changed" in sent[0][1]


# ── restored ─────────────────────────────────────────────────────────────────


def test_the_restored_message_names_the_count_and_the_size(sent):
    m._notify(_event("restored"))

    _, message, _ = sent[0]
    assert "12 files" in message
    assert "3.0 MB" in message


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


def test_an_unseeded_outcome_notifies_nobody_and_does_not_raise(sent):
    """The ASL seeds the outcome, so an absent one is a machine defect — but this verb runs on a
    run that has otherwise succeeded, and raising would report a completed archive as a failure."""
    assert m._notify({**_event("archived"), "outcome": None}) == {}
    assert m._notify({"outcome": "hopeful"}) == {}
    assert m._notify("not a dict") == {}
    assert sent == []


def test_no_actor_means_no_addressee_rather_than_a_message_to_nobody(sent):
    m._notify(_event("archived", actor=""))

    assert sent == []


def test_a_raising_emitter_cannot_fail_the_run(monkeypatch, sent):
    """THE ONE THAT MATTERS. By this state the source is deleted; a raise here would replace a
    completed archive with a reported failure, and the data would still be gone."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("queue exploded")

    monkeypatch.setattr(notify, "emit_archived", boom)

    assert m._notify(_event("archived")) == {}


def test_the_verb_carries_no_failure_decorator(monkeypatch):
    """`@notifies_on_failure` here would report a failure of the NOTIFIER as a failure of the
    archive — the same reasoning file-send's producer records, and the reason the handler has
    `@traced` and nothing else."""
    import inspect

    decorators = [line.strip() for line in inspect.getsource(m).splitlines() if line.startswith("@")]

    assert decorators == ['@observability.traced("notify")']


def test_the_handler_returns_an_empty_dict_and_threads_nothing_onward(monkeypatch, sent):
    """Every invoking state carries `ResultPath: null`, so what this returns never reaches the
    running object — and returning the event would suggest otherwise to the next reader."""
    assert m.handler(_event("restored"), None) == {}
    assert len(sent) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
