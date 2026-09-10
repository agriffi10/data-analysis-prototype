"""A reserved folder is refused as an archive source at its ONE home, and named for itself.

The refusal's wording is the point as much as its reason: a user who selects the receipt folder at
its new location must be told about the receipt folder, not about the prefix it now sits under.
That is what the two passes in ``assert_not_reserved`` buy, and it is why every assertion here
reads the detail rather than only the code.
"""

import pytest
from arcommon.authz import assert_not_reserved
from arcommon.plan import _excluder
from cpcommon.errors import TerminalError

BOTH_HOMES = pytest.mark.parametrize(
    ("home", "reserved"),
    [("alice/{}/", False), ("alice/system_settings/{}/", True)],
    ids=["the-home-it-left", "the-app-managed-home"],
)


@BOTH_HOMES
def test_the_reserved_folder_is_refused_at_its_home_and_names_that_folder(home, reserved):
    """The direct arms, before any ancestor arm runs — and the retired home is a user's folder."""
    if not reserved:
        assert_not_reserved("alice/", home.format("archive"))
        return
    with pytest.raises(TerminalError) as caught:
        assert_not_reserved("alice/", home.format("archive"))

    assert caught.value.reason == "reserved_folder"
    assert "'archive'" in caught.value.detail


@BOTH_HOMES
def test_a_file_inside_the_folder_is_refused_at_its_home_only(home, reserved):
    """Anything beneath the folder — and nothing beneath the name it vacated."""
    if not reserved:
        assert_not_reserved("alice/", f"{home.format('athenaresults')}q.csv")
        return
    with pytest.raises(TerminalError) as caught:
        assert_not_reserved("alice/", f"{home.format('athenaresults')}q.csv")

    assert caught.value.reason == "reserved_folder"
    assert "'athenaresults'" in caught.value.detail


def test_the_settings_prefix_itself_is_named_for_itself():
    """The bare prefix matches no folder's second home, so the list member catches it by name.

    With one combined loop this reported ``archive`` — the first list member whose location the
    prefix contains — which describes a selection of the whole settings folder as an archive.
    """
    with pytest.raises(TerminalError) as caught:
        assert_not_reserved("alice/", "alice/system_settings/")

    assert caught.value.reason == "reserved_folder"
    assert "'system_settings'" in caught.value.detail


def test_a_non_moving_folder_beneath_the_prefix_is_the_prefixs_own_rule():
    """The Out of Scope promise: no phantom home, and ``system_settings`` is what refuses it."""
    with pytest.raises(TerminalError) as caught:
        assert_not_reserved("alice/", "alice/system_settings/user_settings/")

    assert "'system_settings'" in caught.value.detail


def test_the_space_root_still_reports_the_folder_it_contains():
    """The ancestor arm, unchanged: today's answer for the one key that reaches it."""
    with pytest.raises(TerminalError) as caught:
        assert_not_reserved("alice/", "alice/")

    assert "contains 'archive'" in caught.value.detail


def test_an_ordinary_selection_and_a_lookalike_file_still_archive():
    """The anchoring did not widen, and a file whose name merely starts the same way is a file."""
    assert assert_not_reserved("alice/", "alice/backups/archive/") == "alice/backups/archive/"
    assert assert_not_reserved("alice/", "alice/archived-notes.txt") == "alice/archived-notes.txt"


def test_the_expansion_excludes_each_reserved_folder_at_its_one_home():
    """Every reserved location is excluded from an archive expansion, at either home.

    **This proves the LIST membership, not the re-pointing, and no fixture here could prove the
    latter.** Once ``system_settings`` joined ``RESERVED_SOURCE_ROOTS`` the excluder's tuple
    contains ``{root}system_settings/``, and every second home is a strict descendant of it — so
    no key can tell the singular tuple from the plural one through ``startswith``. Measured:
    reverting the excluder to the singular builder leaves this green, while dropping
    ``system_settings`` from the list reddens it, which is the positive control saying what it
    actually measures. The re-pointing is covered by ``assert_not_reserved``'s tests above, where
    the refusal NAMES the folder and the two tuples are distinguishable.
    """
    ignore = _excluder("alice/")

    assert ignore("alice/system_settings/archive/r.txt", 1, "alice/") is True
    assert ignore("alice/system_settings/", 1, "alice/") is True
    assert ignore("alice/reports/mine.csv", 1, "alice/") is False
    # The name it left: an ordinary folder, and its contents belong in the archive.
    assert ignore("alice/archive/r.txt", 1, "alice/") is False


def test_the_any_depth_deletability_rule_reaches_the_new_home_too():
    """``plan._assert_deletable_folder`` mirrors the IAM Deny, which matches at any depth.

    Named by the spec among the rules that are NOT re-pointed, and asserted rather than assumed.
    It refuses the WHOLE request rather than excluding, because archiving deletes the source and a
    silent exclusion drops the user's data out of an archive that reports success.
    """
    from arcommon import plan
    from cpcommon.errors import TerminalError

    for key in (
        "alice/projects/system_settings/archive/notes.txt",
        "alice/system_settings/archive/notes.txt",
    ):
        with pytest.raises(TerminalError) as caught:
            plan._assert_deletable_folder("alice/", key)
        assert caught.value.reason == "undeletable_folder", key
        assert caught.value.tokens == {"folderName": "archive"}, key

    # The name it left is deletable at any depth, which is what the narrowing bought.
    plan._assert_deletable_folder("alice/", "alice/projects/archive/notes.txt")
