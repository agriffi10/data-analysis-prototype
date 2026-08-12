"""Source authorization: may the verified actor read — and DELETE — what they are archiving?

Archiving is the only operation in this repo that deletes a user's data as a side effect of a
copy, so the check here must be at least as strict as delete's already is. There is no second
party: an archive always lands under the space it came from.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

# Importing the messages table is what REGISTERS this plane's reason codes, and TerminalError
# validates its reason at the raise site — so without this a refusal raises ValueError instead.
from arcommon import authz, messages  # noqa: F401
from arcommon.config import RESERVED_SOURCE_ROOTS
from cpcommon.errors import TerminalError


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
        "kind": "personal",
        "name": "alice",
    }


def test_the_kind_and_name_are_carried_forward_rather_than_re_derived():
    """The archive key layout needs both, and re-deriving them downstream is how a PERSONAL
    archive comes to be written under `shared/` — where a space of the same name would then
    be able to restore it."""
    _spaces({})
    resolved = authz.authorize_source("alice", {"kind": "personal", "name": "alice"})

    assert (resolved["kind"], resolved["name"]) == ("personal", "alice")


def test_a_personal_source_is_never_looked_up():
    """The username IS the prefix, so ownership is an equality and not a registry read."""
    authz.reg.load = lambda name: pytest.fail(f"registry consulted for personal space {name!r}")

    assert authz.authorize_source("alice", {"kind": "personal", "name": "alice"})["root"] == "alice/"


def test_a_user_may_not_archive_from_someone_elses_personal_space():
    assert _refused("alice", {"kind": "personal", "name": "bob"}) == "forbidden"


# ── Shared sources ───────────────────────────────────────────────────────────


def test_an_active_member_may_archive_from_a_shared_space():
    _spaces({"marketing": _active(["alice"])})

    assert authz.authorize_source("alice", {"kind": "shared", "name": "marketing"}) == {
        "bucket": "shared-bkt",
        "root": "marketing/",
        "kind": "shared",
        "name": "marketing",
    }


def test_any_active_member_may_archive_not_just_an_owner():
    """Deliberate rather than permissive: every member already holds DeleteObject across the
    whole space prefix, so a member who wanted to destroy the folder can do it today, one
    object at a time, with no receipt. An owner-only rule would add a restriction the bucket
    policy does not have and would prevent nothing."""
    _spaces({
        "marketing": {
            "status": "active",
            "owner": "bob",
            "members": ["alice"],
        }
    })

    assert authz.authorize_source("alice", {"kind": "shared", "name": "marketing"})["root"] == "marketing/"


def test_a_non_member_may_not_archive_from_a_shared_space():
    assert _refused(
        "mallory",
        {"kind": "shared", "name": "marketing"},
        {"marketing": _active(["alice"])},
    ) == "forbidden"


def test_a_space_that_does_not_exist_fails():
    assert _refused("alice", {"kind": "shared", "name": "ghost"}) == "forbidden"


@pytest.mark.parametrize("status", ["provisioning", "deleting", "failed"])
def test_a_space_that_is_not_active_fails(status):
    assert _refused(
        "alice",
        {"kind": "shared", "name": "marketing"},
        {"marketing": {"status": status, "members": ["alice"]}},
    ) == "forbidden"


# ── Malformed space blocks ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "space",
    [None, "marketing", {}, {"kind": "team", "name": "x"}, {"kind": "personal"}, {"kind": "personal", "name": "  "}],
)
def test_a_malformed_source_space_is_refused(space):
    assert _refused("alice", space) == "forbidden"


# ── The reserved roots, each with its own case ───────────────────────────────


@pytest.mark.parametrize("folder", RESERVED_SOURCE_ROOTS)
def test_each_reserved_folder_is_refused_as_the_selection_itself(folder):
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_reserved("alice/", f"alice/{folder}/")

    assert caught.value.reason == "reserved_folder"


@pytest.mark.parametrize("folder", RESERVED_SOURCE_ROOTS)
def test_each_reserved_folder_is_refused_without_its_trailing_slash(folder):
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_reserved("alice/", f"alice/{folder}")

    assert caught.value.reason == "reserved_folder"


@pytest.mark.parametrize("folder", RESERVED_SOURCE_ROOTS)
def test_anything_BENEATH_a_reserved_folder_is_refused(folder):
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_reserved("alice/", f"alice/{folder}/2026/q1.csv")

    assert caught.value.reason == "reserved_folder"


def test_selecting_the_space_ROOT_is_refused_because_it_CONTAINS_them():
    """THE THIRD WAY TO SELECT ONE, and the one an obvious two-rule check misses. SPEC-169
    expands a folder by listing its prefix, so the space root would carry user_settings/ out
    with everything else AND THEN DELETE IT."""
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_reserved("alice/", "alice/")

    assert caught.value.reason == "reserved_folder"


def test_an_ordinary_folder_the_user_made_with_a_reserved_NAME_is_archivable():
    """The rules are anchored at the SPACE ROOT, the same anchoring isUndeletableRootFolder
    uses in the browser. `alice/reports/archive/` is the user's own folder."""
    assert authz.assert_not_reserved("alice/", "alice/reports/archive/") == "alice/reports/archive/"
    assert authz.assert_not_reserved("alice/", "alice/reports/user_settings/") is not None


def test_a_file_whose_name_merely_STARTS_like_a_reserved_folder_is_archivable():
    """The ancestor test applies to PREFIXES only, which is why the key is compared in its
    trailing-slash form rather than raw. `alice/archived-notes.txt` is an ordinary file."""
    assert authz.assert_not_reserved("alice/", "alice/archived-notes.txt") == "alice/archived-notes.txt"
    assert authz.assert_not_reserved("alice/", "alice/athenaresults-old.csv") is not None


def test_the_reserved_list_is_archives_OWN_and_not_the_browsers_three_lists_unioned():
    """`protectedFolders.ts` keeps three deliberately divergent lists answering three
    different questions, and its own header warns that unioning them is the wrong repair.
    The question here is a FOURTH one no existing list answers: may this be moved out of the
    space and DELETED? So `saved_queries/` is archivable (an ordinary folder of the user's own
    files) while `shared_tables/` is not (a Glue table would be left pointing at nothing)."""
    assert "saved_queries" not in RESERVED_SOURCE_ROOTS
    assert "shared_tables" in RESERVED_SOURCE_ROOTS
    assert "_directory" not in RESERVED_SOURCE_ROOTS  # a bucket-root prefix, not inside a space


# ── The prefix marker refuses the WHOLE request ──────────────────────────────


def test_selecting_a_prefix_marker_refuses_the_whole_request():
    """Both bucket policies deny DeleteObject on */DO_NOT_DELETE.txt and `*` matches `/`, so
    a marker at any depth is already undeletable. Archiving deletes the source, so the run
    would copy the object into Glacier and then fail on the delete — after some of the user's
    data had already moved."""
    with pytest.raises(TerminalError) as caught:
        authz.assert_not_protected_marker("alice/reports/DO_NOT_DELETE.txt")

    assert caught.value.reason == "protected_marker"


def test_the_marker_rule_matches_at_any_depth():
    for key in ("alice/DO_NOT_DELETE.txt", "alice/a/b/c/DO_NOT_DELETE.txt"):
        with pytest.raises(TerminalError):
            authz.assert_not_protected_marker(key)


def test_a_file_merely_NAMED_like_the_marker_is_archivable():
    assert authz.assert_not_protected_marker("alice/DO_NOT_DELETE.txt.bak") is not None
    assert authz.assert_not_protected_marker("alice/my-DO_NOT_DELETE.txt") is not None


def test_a_FOLDER_containing_a_marker_is_still_archivable():
    """A different question, answered by SPEC-169's expansion excluding markers the way
    file-send excludes user_settings/. If a folder containing one were refused, a marker at
    the space root would make the whole space un-archivable."""
    assert authz.assert_not_protected_marker("alice/reports/") == "alice/reports/"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
