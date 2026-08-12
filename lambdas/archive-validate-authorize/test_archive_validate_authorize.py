"""validate-authorize: the archive plane's front door.

Archiving is the only operation in this repo that DELETES a user's data as a side effect of a
copy, so everything here is about refusing the whole request rather than skipping a bad row —
a partial archive whose refused row was silently dropped is the failure this verb exists to
make unreachable.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in ("control-plane-common", "archive-common"):
    sys.path.insert(0, os.path.join(_HERE, "..", _p))

import archive_validate_authorize as verb
from arcommon import authz, notify
from arcommon.config import (
    ARCHIVE_MAX_ITEM_BYTES,
    ARCHIVE_MAX_ITEMS,
    RESERVED_SOURCE_ROOTS,
)
from cpcommon import auth
from cpcommon.errors import TerminalError

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


@pytest.fixture(autouse=True)
def _bind(monkeypatch):
    """The verified actor, an empty registry and a notification sink.

    The token is stubbed at ``cpcommon.auth.verified_username`` rather than by minting a real
    JWT: what this suite is about is what happens AFTER the actor is known, and the
    verification itself has its own suite in cpcommon.
    """
    monkeypatch.setattr(auth, "verified_username", lambda actor, **kw: "alice")
    monkeypatch.setattr(authz.reg, "load", lambda name: None)
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _event(**overrides):
    body = {
        "requestId": UUID,
        "mode": "archive",
        "actor": {"idToken": "eyJ-token"},
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/reports/q1.csv"}],
        },
    }
    body.update(overrides)
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _refused(**overrides):
    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(**overrides), None)
    return caught.value.reason


def _source(**overrides):
    space = {"kind": "personal", "name": "alice"}
    base = {"space": space, "items": [{"kind": "file", "key": "alice/reports/q1.csv"}]}
    base.update(overrides)
    return base


# ── The happy path, and what it resolves ─────────────────────────────────────


def test_a_valid_archive_request_resolves_its_source_and_its_destination():
    out = verb.handler(_event(), None)

    assert out["requestId"] == UUID
    assert out["mode"] == "archive"
    assert out["actor"] == {"username": "alice"}
    assert out["source"]["bucket"] == "user-bkt"
    assert out["source"]["root"] == "alice/"
    assert out["source"]["items"] == [{"kind": "file", "key": "alice/reports/q1.csv"}]


def test_the_archive_prefix_is_resolved_here_and_not_by_the_verb_that_copies():
    """It is a pure function of the request — kind, name and request id — so computing it once
    means the copier, the receipt writer and SPEC-170's restore read ONE string rather than
    three agreeing constructions of it."""
    out = verb.handler(_event(), None)

    assert out["archive"] == {
        "bucket": "archive-bkt",
        "root": f"personal/alice/archive/{UUID}/",
        "receiptBucket": "user-bkt",
        "receiptKey": f"alice/archive/{UUID}/receipt.txt",
    }


def test_a_shared_source_resolves_under_the_shared_namespace():
    """The kind segment is the whole defence against a user and a space of the same name
    sharing an archive prefix."""
    verb.authz.reg.load = lambda name: {"status": "active", "members": ["alice"]}
    out = verb.handler(
        _event(source={"space": {"kind": "shared", "name": "alice"},
                       "items": [{"kind": "file", "key": "alice/q1.csv"}]}),
        None,
    )

    assert out["archive"]["root"] == f"shared/alice/archive/{UUID}/"
    assert out["archive"]["receiptBucket"] == "shared-bkt"


def test_a_folder_key_is_normalised_to_a_trailing_slash_before_any_rule_runs():
    """SPEC-169 expands a folder with a prefix listing, so `alice/archiv` without one would
    match `alice/archive/` and carry the receipts of every past archive out through a door the
    reserved-root rule never sees."""
    out = verb.handler(_event(source=_source(items=[{"kind": "folder", "key": "alice/reports"}])), None)

    assert out["source"]["items"] == [{"kind": "folder", "key": "alice/reports/"}]


# ── The actor comes from the token and nowhere else ──────────────────────────


def test_nothing_from_the_untrusted_body_identifies_the_actor(monkeypatch):
    monkeypatch.setattr(auth, "verified_username", lambda actor, **kw: "alice")
    out = verb.handler(
        _event(actor={"idToken": "eyJ-token", "username": "root"}),
        None,
    )

    assert out["actor"] == {"username": "alice"}


def test_a_bad_token_fails_before_anything_is_authorized(monkeypatch):
    monkeypatch.setattr(
        auth, "verified_username", lambda actor, **kw: (_ for _ in ()).throw(TerminalError("unauthorized", "expired"))
    )
    verb.authz.reg.load = lambda name: pytest.fail("registry consulted before the token verified")

    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(), None)
    assert caught.value.reason == "unauthorized"


def test_a_pre_identity_failure_notifies_nobody(_bind, monkeypatch):
    """There is no trusted recipient in that window, and notifying the body's own claim would
    let anyone deliver text to any inbox."""
    monkeypatch.setattr(
        auth, "verified_username", lambda actor, **kw: (_ for _ in ()).throw(TerminalError("unauthorized", "x"))
    )

    with pytest.raises(TerminalError):
        verb.handler(_event(), None)
    assert _bind == []


def test_a_refusal_after_the_actor_is_known_notifies_them(_bind):
    with pytest.raises(TerminalError):
        verb.handler(_event(source=_source(items=[])), None)

    assert [user for user, _ in _bind] == ["alice"]


# ── The contract: unknown fields are REJECTED, not ignored ───────────────────


def test_an_unknown_top_level_field_is_rejected_rather_than_dropped():
    """A field the producer thinks it is sending and this verb silently drops is a contract
    break that shows up as behaviour nobody asked for."""
    assert _refused(recipients=[{"kind": "user", "name": "bob"}]) == "malformed_event"


@pytest.mark.parametrize("bad", [None, "", 42, "   "])
def test_a_missing_or_non_string_request_id_is_rejected(bad):
    assert _refused(requestId=bad) == "malformed_event"


def test_a_request_id_that_is_not_a_uuid_v4_is_refused_before_it_becomes_a_key():
    """FR-004: validated in arcommon.paths BEFORE it is ever concatenated into an S3 key. The
    id is browser-supplied and becomes a path segment in two buckets."""
    assert _refused(requestId="../../etc") == "invalid_request"


def test_a_mode_this_verb_does_not_implement_is_refused():
    assert _refused(mode="restore") == "malformed_event"


def test_a_body_that_is_not_an_object_is_refused():
    with pytest.raises(TerminalError) as caught:
        verb.handler([{"messageId": "m-1", "body": json.dumps(["not", "an", "object"])}], None)

    assert caught.value.reason == "malformed_event"


# ── Containment: the two rules, each with its own case (FR-005) ──────────────


def test_a_sibling_prefix_that_merely_starts_the_same_way_is_refused():
    """THE alice2/ CASE. A raw `key.startswith(root)` on the UNNORMALISED root accepts it, and
    the two usernames need not be related for one to be a prefix of the other."""
    assert _refused(source=_source(items=[{"kind": "file", "key": "alice2/reports/q1.csv"}])) == "forbidden"


def test_a_key_with_a_dot_dot_path_segment_is_refused():
    """THE alice/../bob/ CASE. Normalisation does nothing about dot segments, and
    "alice/../bob/secrets.csv".startswith("alice/") is True."""
    assert _refused(source=_source(items=[{"kind": "file", "key": "alice/../bob/secrets.csv"}])) == "forbidden"


def test_a_single_dot_path_segment_is_refused_too():
    assert _refused(source=_source(items=[{"kind": "file", "key": "alice/./q1.csv"}])) == "forbidden"


def test_an_out_of_root_key_fails_the_WHOLE_request_not_just_that_item():
    """A request naming a key outside the actor's own space is not a request with one bad row
    in it — and here, where the run deletes what it copies, dropping the row silently would
    archive and destroy a DIFFERENT selection from the one that was refused."""
    assert _refused(
        source=_source(items=[
            {"kind": "file", "key": "alice/reports/q1.csv"},
            {"kind": "file", "key": "bob/secrets.csv"},
        ])
    ) == "forbidden"


def test_a_source_space_that_is_not_the_actors_own_is_refused():
    assert _refused(
        source={"space": {"kind": "personal", "name": "bob"},
                "items": [{"kind": "file", "key": "bob/q1.csv"}]}
    ) == "forbidden"


# ── The reserved roots and the prefix marker (FR-005) ────────────────────────


@pytest.mark.parametrize("folder", RESERVED_SOURCE_ROOTS)
def test_each_reserved_root_is_refused_as_an_archive_source(folder):
    assert _refused(
        source=_source(items=[{"kind": "folder", "key": f"alice/{folder}/"}])
    ) == "reserved_folder"


def test_selecting_the_whole_space_is_refused_because_it_contains_them():
    assert _refused(source=_source(items=[{"kind": "folder", "key": "alice/"}])) == "reserved_folder"


def test_a_selection_containing_a_prefix_marker_refuses_the_whole_request():
    """An existing IAM Deny makes the marker undeletable, so the run would copy it into
    Glacier and then fail on the delete — after some of the user's data had already moved."""
    assert _refused(
        source=_source(items=[
            {"kind": "file", "key": "alice/reports/q1.csv"},
            {"kind": "file", "key": "alice/DO_NOT_DELETE.txt"},
        ])
    ) == "protected_marker"


# ── The selection caps (FR-005) ──────────────────────────────────────────────


def test_more_than_the_item_cap_is_a_whole_request_failure_naming_the_count_and_the_cap():
    items = [{"kind": "file", "key": f"alice/f{i}.csv"} for i in range(ARCHIVE_MAX_ITEMS + 1)]
    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(source=_source(items=items)), None)

    assert caught.value.reason == "too_many_items"
    assert str(ARCHIVE_MAX_ITEMS + 1) in caught.value.detail
    assert str(ARCHIVE_MAX_ITEMS) in caught.value.detail


def test_the_item_cap_is_checked_before_the_per_item_loop_runs(monkeypatch):
    """The loop is work proportional to caller-supplied input; rejecting after doing it would
    defeat the point of having a cap."""
    monkeypatch.setattr(
        verb.authz, "assert_not_reserved", lambda root, key: pytest.fail("per-item work ran past the cap")
    )
    items = [{"kind": "file", "key": f"alice/f{i}.csv"} for i in range(ARCHIVE_MAX_ITEMS + 1)]

    with pytest.raises(TerminalError):
        verb.handler(_event(source=_source(items=items)), None)


def test_a_selection_over_the_byte_budget_is_refused():
    """A different quantity from the count: the count bounds the per-item work, this bounds
    what rides on the state and reaches the Pipe."""
    long_key = "alice/" + "k" * 1000
    items = [{"kind": "file", "key": f"{long_key}{i}"} for i in range(ARCHIVE_MAX_ITEMS)]
    assert len(json.dumps(items).encode()) > ARCHIVE_MAX_ITEM_BYTES

    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(source=_source(items=items)), None)
    assert caught.value.reason == "selection_too_large"


@pytest.mark.parametrize(
    ("items", "reason"),
    [
        (None, "no_items"),
        ([], "no_items"),
        ("alice/q1.csv", "invalid_items"),
        (["alice/q1.csv"], "invalid_items"),
        ([{"kind": "symlink", "key": "alice/q1.csv"}], "invalid_items"),
        ([{"kind": "file"}], "invalid_items"),
        ([{"kind": "file", "key": ""}], "invalid_items"),
    ],
)
def test_a_malformed_selection_is_refused_with_its_own_reason(items, reason):
    assert _refused(source=_source(items=items)) == reason


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
