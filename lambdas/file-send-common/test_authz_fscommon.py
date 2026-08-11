"""Source authorization: may the verified sender read what they are sending?

The recipient side is deliberately not an authorization question — see the verb's suite — so
everything here is about the SOURCE.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon.errors import TerminalError

# Importing the messages table is what REGISTERS this plane's reason codes, and TerminalError
# validates its reason at the raise site — so without this an authorization refusal raises
# ValueError instead. Every verb gets the registration transitively through fscommon.notify;
# this file exercises authz alone, so it imports it directly rather than relying on an import
# it does not make.
from fscommon import authz, messages  # noqa: F401


def _spaces(records):
    authz.reg.load = lambda name: records.get(name)


def _refused(username, space, records=None):
    _spaces(records or {})
    with pytest.raises(TerminalError) as caught:
        authz.authorize_source(username, space)
    return caught.value.reason


def _active(members):
    return {"status": "active", "members": members}


# ── Personal sources ─────────────────────────────────────────────────────────


def test_a_personal_source_resolves_to_the_user_space_bucket():
    _spaces({})

    assert authz.authorize_source("alice", {"kind": "personal", "name": "alice"}) == {
        "bucket": "user-bkt",
        "root": "alice/",
    }


def test_a_personal_source_is_never_looked_up():
    """The username IS the prefix, so ownership is an equality and not a registry read. A
    lookup here would be a second source of truth for something the token already settled."""
    authz.reg.load = lambda name: pytest.fail(f"registry consulted for personal space {name!r}")

    assert authz.authorize_source("alice", {"kind": "personal", "name": "alice"})["root"] == "alice/"


def test_another_users_personal_space_is_refused():
    assert _refused("alice", {"kind": "personal", "name": "bob"}) == "forbidden"


def test_a_personal_space_whose_name_merely_starts_the_same_is_refused():
    assert _refused("alice", {"kind": "personal", "name": "alice2"}) == "forbidden"


# ── Shared sources ───────────────────────────────────────────────────────────


def test_a_shared_source_resolves_for_an_active_member():
    _spaces({"sales": _active(["alice", "bob"])})

    assert authz.authorize_source("alice", {"kind": "shared", "name": "sales"}) == {
        "bucket": "shared-bkt",
        "root": "sales/",
    }


def test_a_non_member_is_refused():
    assert _refused("carol", {"kind": "shared", "name": "sales"}, {"sales": _active(["alice"])}) == "forbidden"


def test_an_unregistered_space_is_refused():
    assert _refused("alice", {"kind": "shared", "name": "ghost"}, {}) == "forbidden"


@pytest.mark.parametrize("status", ["provisioning", "deleting", "failed"])
def test_a_space_that_is_not_active_is_refused(status):
    """These are the statuses that actually exist on a registry record. FR-003 AC4 was written
    as "pending, leaving, absent" and was amended (2026-08-11) to name them: `leaving` is not a
    status anywhere in this repo, and reading `pending` as the per-member join chip would have
    reversed SPEC-073, under which access is granted at add time and the chip is display only.
    A member who has not yet acknowledged the space can browse, download and table-share from
    it; refusing only the send would be an inconsistency with no security benefit."""
    records = {"sales": {"status": status, "members": ["alice"]}}

    assert _refused("alice", {"kind": "shared", "name": "sales"}, records) == "forbidden"


def test_a_member_who_has_not_acknowledged_the_space_is_authorized():
    """The other half of the amendment, asserted rather than implied: the roster is what grants
    access, and an unacknowledged member is on it."""
    _spaces({"sales": {"status": "active", "members": ["alice"], "acknowledged": []}})

    assert authz.authorize_source("alice", {"kind": "shared", "name": "sales"})["root"] == "sales/"


# ── Shape ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("space", [None, "alice", {}, {"kind": "personal"}, {"name": "alice"}])
def test_a_malformed_space_is_refused(space):
    assert _refused("alice", space) == "forbidden"


def test_an_unknown_kind_is_refused():
    assert _refused("alice", {"kind": "archive", "name": "alice"}) == "forbidden"


# ── The results folder ───────────────────────────────────────────────────────


def test_the_results_folder_itself_is_refused():
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_results_folder("alice/", "alice/athenaresults/")

    assert caught.value.reason == "results_not_sendable"


def test_the_results_folder_without_its_trailing_slash_is_refused():
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_results_folder("alice/", "alice/athenaresults")

    assert caught.value.reason == "results_not_sendable"


def test_a_file_beneath_the_results_folder_is_refused():
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_results_folder("alice/", "alice/athenaresults/abc.csv")

    assert caught.value.reason == "results_not_sendable"


def test_a_nested_folder_of_the_same_name_is_allowed():
    """Anchored at the space root, so a folder the user made themselves stays theirs to send."""
    key = "alice/reports/athenaresults/x.csv"

    assert authz.assert_not_results_folder("alice/", key) == key


def test_a_name_that_merely_starts_with_it_is_allowed():
    key = "alice/athenaresults-archive/x.csv"

    assert authz.assert_not_results_folder("alice/", key) == key


def test_the_rule_holds_identically_in_a_shared_space():
    with pytest.raises(TerminalError):
        authz.assert_not_results_folder("sales/", "sales/athenaresults/x.csv")
