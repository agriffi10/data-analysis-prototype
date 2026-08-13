"""The archive plane's links, and what may not end up in one (SPEC-172 FR-006).

A link is minted in Python and honoured by a TypeScript route rule, so nothing offline can prove
the pair works — what CAN be proved offline is that this half never mints something the browser
would silently discard, and never puts anything into a path that could change where it goes.
``isSafeInAppPath`` is the browser's gate; this is the producer's.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

from arcommon import notify, paths

_ARCHIVE_ID = "3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93"


# ── the archive folder link ──────────────────────────────────────────────────


def test_the_link_is_the_receipt_root_the_plane_actually_wrote():
    """Built from ``paths.receipt_root`` rather than reassembled here: the folder the user is
    sent to has to be the folder write-receipt used, and two constructions of one string is how
    a link starts pointing at an empty folder."""
    link = notify.archive_folder_link("personal", "alice", _ARCHIVE_ID)

    assert link == f"/files?prefix={paths.receipt_root('alice', _ARCHIVE_ID)}"


def test_the_prefix_includes_the_space_root():
    """FilesPage keeps a `?prefix=` only when it starts with the resolved space's own root, so a
    root-relative `archive/{uuid}/` is silently discarded and the user lands at their space root
    with no idea why — a link that looks like it worked and did not (SPEC-167's finding)."""
    link = notify.archive_folder_link("personal", "alice", _ARCHIVE_ID)

    assert "prefix=alice/archive/" in link


def test_a_shared_space_link_names_the_space():
    """Worse than a dead end without it: the route resolves the PERSONAL space, discards the
    prefix for the reason above, and lands the user in their own files while the message tells
    them where to look."""
    link = notify.archive_folder_link("shared", "finance", _ARCHIVE_ID)

    assert link.startswith("/files?space=finance&prefix=finance/archive/")


def test_a_personal_link_carries_no_space_query():
    """Gating a personal link on the shared-workspaces flag would drop a working link — which is
    why `NotificationRow` keys that clause on `?space=` and this one must not emit it."""
    assert "space=" not in notify.archive_folder_link("personal", "alice", _ARCHIVE_ID)


@pytest.mark.parametrize(
    "kind,name,request_id",
    [
        ("personal", "../evil", _ARCHIVE_ID),
        ("personal", "alice/bob", _ARCHIVE_ID),
        ("personal", "alice?x=1", _ARCHIVE_ID),
        ("shared", "", _ARCHIVE_ID),
        ("wat", "alice", _ARCHIVE_ID),
        ("personal", "alice", "../../etc"),
        ("personal", "alice", ""),
    ],
)
def test_nothing_that_could_change_a_url_is_ever_interpolated(kind, name, request_id):
    """It rejects nothing the pipeline legitimately produces — usernames, space names and request
    ids are already constrained — so this is here so a future change to any of those formats
    cannot quietly put a traversal or a query string into somebody's inbox."""
    assert notify.archive_folder_link(kind, name, request_id) is None


def test_an_id_that_is_plain_but_not_a_UUID_returns_None_rather_than_raising():
    """`_plain` and `validated_request_id` do not agree — the first accepts any plain segment, the
    second only a UUID v4 — and the gap between them used to RAISE. Unreachable today, but this
    function's contract is "None when no working link can be minted", and the caller's caller
    would otherwise lose the whole `archived` message to its blanket except: the only message
    carrying the archive id, on the arm where the source is already deleted."""
    assert notify.archive_folder_link("personal", "alice", "abc") is None
    assert notify.archive_folder_link("personal", "alice", "not-a-uuid") is None


# ── the restore link ─────────────────────────────────────────────────────────


def test_the_restore_link_is_the_space_root():
    """A restore puts every object back where it came from, which for any selection of more than
    one folder is several places at once. There is no single restored path to point at."""
    assert notify.space_link("personal", "alice") == "/files?prefix=alice/"
    assert notify.space_link("shared", "finance") == "/files?space=finance&prefix=finance/"


def test_the_restore_link_refuses_the_same_segments():
    assert notify.space_link("personal", "../evil") is None
    assert notify.space_link("wat", "alice") is None


# ── what the emitters address, and what they carry ───────────────────────────


@pytest.fixture
def sent(monkeypatch):
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, dedup_id=None, link=None: captured.append(
            (user, message, link, dedup_id)
        ),
    )
    return captured


def test_every_outcome_addresses_the_actor_and_nobody_else(sent):
    """An archive has ONE actor, one source and one destination — there is no second party to
    tell, and no per-recipient outcome for a producer to get wrong (file-send's shape, which this
    plane deliberately does not have)."""
    space = {"kind": "personal", "name": "alice"}
    notify.emit_archived("alice", space, _ARCHIVE_ID, 2, 10)
    notify.emit_restore_started("alice", "run-1", 2)
    notify.emit_restored("alice", space, "run-1", 2, 10)

    assert [row[0] for row in sent] == ["alice", "alice", "alice"]


def test_each_success_outcome_carries_a_token_that_is_PER_RUN(sent):
    """SPEC-114's rule read literally: one token per outcome. Two of these three bodies have no
    discriminator in them at all — `restore_started` names a count and nothing else — so the
    queue's content dedup would collapse two restores of the same folder started together into
    ONE inbox row, and the user would see a response to one of two requests with no way to tell
    which. The token keeps the retry-safety content dedup was providing, because a re-invocation
    of the same state composes the same one."""
    space = {"kind": "personal", "name": "alice"}
    notify.emit_restore_started("alice", "run-1", 2)
    notify.emit_restore_started("alice", "run-2", 2)
    notify.emit_restored("alice", space, "run-1", 2, 10)

    assert sent[0][1] == sent[1][1], "the two bodies really are identical — that is the hazard"
    tokens = [row[3] for row in sent]
    assert all(tokens), "a success outcome with no token falls back to content dedup"
    assert len(set(tokens)) == 3


def test_the_token_is_stable_for_one_run_and_one_outcome(sent):
    """Which is what makes a state's `Retry` safe: a re-invocation after a transient Lambda fault
    composes the same token and the queue drops the second copy."""
    notify.emit_restore_started("alice", "run-1", 2)
    notify.emit_restore_started("alice", "run-1", 2)

    assert sent[0][3] == sent[1][3]


def test_a_kept_archive_is_reported_as_kept(sent):
    """The emitter's half of the conditional sentence. `archive_swept=False` is the route through
    `CleanupIncomplete`, which is a SUCCESSFUL run whose vault sweep did not happen."""
    space = {"kind": "personal", "name": "alice"}
    notify.emit_restored("alice", space, "run-1", 2, 10, archive_swept=False)
    notify.emit_restored("alice", space, "run-2", 2, 10)

    assert "cleaned up" not in sent[0][1]
    assert "cleaned up" in sent[1][1]


def test_a_started_notification_offers_no_link(sent):
    """Nothing has arrived yet. A link to an unchanged space would suggest there is something to
    look at, three hours before there is."""
    notify.emit_restore_started("alice", "run-1", 2)

    assert sent[0][2] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
