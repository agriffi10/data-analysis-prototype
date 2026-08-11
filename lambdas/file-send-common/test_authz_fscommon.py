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

# Importing the messages table is what REGISTERS this plane's reason codes, and TerminalError
# validates its reason at the raise site — so without this an authorization refusal raises
# ValueError instead. Every verb gets the registration transitively through fscommon.notify;
# this file exercises authz alone, so it imports it directly rather than relying on an import
# it does not make.
from cpcommon import config
from cpcommon.errors import TerminalError
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


def test_selecting_the_space_root_is_refused_because_it_CONTAINS_the_results_folder():
    """THE ANCESTOR CASE, and it is the one the first two rules miss entirely.

    Selecting `sales/` as a folder passes containment and passes "is it the results folder or
    under it" — and then SPEC-165 expands the folder by listing its prefix, carrying
    `sales/athenaresults/` out with everything else. In a shared space that is other members'
    query results reaching a recipient who is not in the space.
    """
    for root in ("alice/", "sales/"):
        with pytest.raises(TerminalError) as caught:
            authz.assert_not_results_folder(root, root)
        assert caught.value.reason == "results_not_sendable"


def test_the_space_root_without_its_trailing_slash_is_refused_too():
    with pytest.raises(TerminalError):
        authz.assert_not_results_folder("alice/", "alice")


def test_a_file_whose_name_merely_starts_the_same_way_is_allowed():
    """The ancestor rule compares PREFIXES. `alice/a` is a file, not a folder containing
    `alice/athenaresults/`, and refusing it would refuse ordinary user data."""
    for key in ("alice/a", "alice/athena", "alice/athenaresults.csv"):
        assert authz.assert_not_results_folder("alice/", key) == key


def test_an_intermediate_folder_that_does_not_contain_it_is_allowed():
    key = "alice/reports/"

    assert authz.assert_not_results_folder("alice/", key) == key


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


# ── SPEC-165 FR-003 AC1: where a recipient's inbox lives ─────────────────────


def test_a_user_recipient_resolves_to_the_user_space_bucket():
    assert authz.recipient_location("user", "bob") == {
        "bucket": config.USER_SPACE_BUCKET,
        "root": "bob/",
    }


def test_a_space_recipient_resolves_to_the_shared_space_bucket():
    assert authz.recipient_location("space", "sales") == {
        "bucket": config.SHARED_SPACE_BUCKET,
        "root": "sales/",
    }


def test_the_two_buckets_are_not_the_same_one():
    """The whole content of AC1. A resolver that returned one bucket for both kinds would pass
    every shape assertion above and write every `space` send into a username's prefix."""
    user = authz.recipient_location("user", "x")
    space = authz.recipient_location("space", "x")

    assert user["bucket"] != space["bucket"]


def test_resolving_is_NOT_authorizing():
    """The asymmetry with `authorize_source`, asserted so it cannot be quietly closed: a
    recipient is any space by name and any name at all here, because the execution role does the
    write and whether the recipient exists is validate-authorize's per-recipient annotation."""
    assert authz.recipient_location("space", "a-space-nobody-is-in")["root"] == "a-space-nobody-is-in/"


@pytest.mark.parametrize(("kind", "name"), [("personal", "bob"), ("", "bob"), ("user", ""), ("user", "  "), ("user", None)])
def test_an_unusable_recipient_refuses_rather_than_defaulting_to_a_bucket(kind, name):
    """Neither can reach here through validate-authorize, which shape-checks both. It fails
    rather than defaulting because guessing wrong writes one person's files into another's
    space — and `personal` is in the list on purpose: it is a valid SOURCE kind and not a
    recipient kind, which is exactly the confusion a shared vocabulary invites."""
    with pytest.raises(TerminalError) as caught:
        authz.recipient_location(kind, name)

    assert caught.value.reason == "forbidden"
