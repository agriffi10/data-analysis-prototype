"""Two authorization questions, and one refusal that must not become an existence oracle.

This plane is the first to ask about a DESTINATION as an authorization rather than a lookup, so
the tests below check both sides by the same rules — and check that they refuse identically
whether a space is missing or merely closed to the actor.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon import config
from cpcommon.errors import TerminalError
from focommon import authz, messages


def _spaces(records):
    authz.reg.load = lambda name: records.get(name)


def _active(members):
    return {"status": "active", "members": members}


def _refused(fn, username, space, records=None):
    _spaces(records or {})
    with pytest.raises(TerminalError) as caught:
        fn(username, space)
    return caught.value


@pytest.mark.parametrize("authorize", [authz.authorize_source, authz.authorize_destination])
def test_a_personal_space_is_only_ever_the_actors_own(authorize):
    """Never a lookup: the username IS the prefix, so equality is the whole rule."""
    _spaces({})

    assert authorize("alice", {"kind": "personal", "name": "alice"}) == {
        "bucket": config.USER_SPACE_BUCKET,
        "root": "alice/",
    }
    assert _refused(authorize, "alice", {"kind": "personal", "name": "bob"}).reason == "forbidden"


@pytest.mark.parametrize("authorize", [authz.authorize_source, authz.authorize_destination])
def test_a_shared_space_authorizes_on_active_membership(authorize):
    """A space still provisioning, deleting or failed fails here, as does one the actor is not in."""
    _spaces({"sales": _active(["alice"]), "ops": {"status": "provisioning", "members": ["alice"]}})

    assert authorize("alice", {"kind": "shared", "name": "sales"}) == {
        "bucket": config.SHARED_SPACE_BUCKET,
        "root": "sales/",
    }
    assert _refused(
        authorize, "alice", {"kind": "shared", "name": "ops"}, {"ops": {"status": "provisioning"}}
    ).reason == "forbidden"


def test_membership_is_the_registry_list_and_the_chip_is_not_in_it():
    """A member whose join chip still reads pending is authorized, and the mechanism is that the
    chip is not part of this record at all.

    ``is_active_member`` gates on the SPACE's provisioning status and plain membership of a flat
    username list. The pending/active chip a member sees lives elsewhere — it is display and
    bookkeeping, and access is granted at add time — so there is nothing here that could deny it.
    Asserting the record shape is what keeps that true: a future record that grew per-member status
    would make the chip reachable from this rule for the first time, and refusing on it would make
    this the only plane where such a member cannot touch files they can already browse.
    """
    _spaces({"sales": {"status": "active", "members": ["alice", "bob"]}})

    assert authz.authorize_source("alice", {"kind": "shared", "name": "sales"})["root"] == "sales/"
    assert _refused(
        authz.authorize_source,
        "carol",
        {"kind": "shared", "name": "sales"},
        {"sales": {"status": "active", "members": ["alice", "bob"]}},
    ).reason == "forbidden"


def test_the_destination_is_authorized_independently_of_the_source():
    """A request may name two different spaces, and authorizing only the one it reads from would
    let an actor write into a space they may read nothing of."""
    _spaces({"sales": _active(["alice"])})

    assert authz.authorize_source("alice", {"kind": "personal", "name": "alice"})["root"] == "alice/"
    assert (
        _refused(authz.authorize_destination, "alice", {"kind": "shared", "name": "secret"}).reason
        == "forbidden"
    )


def test_a_missing_space_and_an_unreachable_one_refuse_BYTE_IDENTICALLY():
    """No existence oracle, asserted by rendering both and comparing.

    Without this the plane answers "is there a shared space called X?" for any name a caller cares
    to try, one request at a time — and the answer is free, because a refusal costs nothing. It is
    asserted on the rendered SENTENCE rather than the reason code, because the code being equal
    proves nothing about what the user is shown.
    """
    absent = _refused(authz.authorize_destination, "alice", {"kind": "shared", "name": "ghost"}, {})
    closed = _refused(
        authz.authorize_destination,
        "alice",
        {"kind": "shared", "name": "sales"},
        {"sales": _active(["bob"])},
    )

    assert absent.reason == closed.reason
    assert absent.detail == closed.detail
    assert messages.failure_message("copy", absent.reason, absent.detail) == messages.failure_message(
        "copy", closed.reason, closed.detail
    )


def test_a_personal_space_that_is_not_the_actors_refuses_the_same_way_too():
    """The third door into the same question: naming someone else's personal space must not read
    differently from naming a shared space that does not exist."""
    other = _refused(authz.authorize_destination, "alice", {"kind": "personal", "name": "bob"})
    ghost = _refused(authz.authorize_destination, "alice", {"kind": "shared", "name": "ghost"}, {})

    assert other.detail == ghost.detail


@pytest.mark.parametrize(
    "space",
    [None, "sales", {}, {"kind": "team", "name": "sales"}, {"kind": "shared"}, {"kind": "shared", "name": "  "}],
)
def test_a_malformed_space_is_refused_rather_than_defaulted(space):
    """Guessing a bucket writes one person's files into another's space, so a shape this does not
    recognise fails rather than falling back to a default."""
    assert _refused(authz.authorize_source, "alice", space).reason == "forbidden"
