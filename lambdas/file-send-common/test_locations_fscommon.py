"""The results folder is unsendable at its one home, and the name it left is a user's folder.

The send plane excludes exactly two folders from an expansion, and the two sit at different depths
on purpose: the results folder moved under ``system_settings/``, while ``user_settings/`` did not.
A rule that gave every excluded folder the new prefix would make a receipt unsendable, and one
still keyed on the old depth makes a user's own ``athenaresults/`` unsendable — the narrowing can
go wrong in both directions, so both are asserted.
"""

import pytest
from cpcommon.errors import TerminalError
from fscommon.authz import assert_not_results_folder
from fscommon.expand import _excluder

BOTH_HOMES = pytest.mark.parametrize(
    ("home", "refused"),
    [("alice/{}/", False), ("alice/system_settings/{}/", True)],
    ids=["the-home-it-left", "the-app-managed-home"],
)


@BOTH_HOMES
def test_the_results_folder_is_refused_as_a_source_at_its_home_only(home, refused):
    """The folder itself and anything beneath it — and neither, at the name it vacated."""
    if not refused:
        assert_not_results_folder("alice/", home.format("athenaresults"))
        assert_not_results_folder("alice/", f"{home.format('athenaresults')}q.csv")
        return
    with pytest.raises(TerminalError) as folder:
        assert_not_results_folder("alice/", home.format("athenaresults"))
    with pytest.raises(TerminalError) as inside:
        assert_not_results_folder("alice/", f"{home.format('athenaresults')}q.csv")

    assert folder.value.reason == "results_not_sendable"
    assert inside.value.reason == "results_not_sendable"


def test_the_settings_prefix_is_refused_as_containing_the_results_folder():
    """Correct, and worth pinning because the message names the folder INSIDE, not the one picked.

    ``alice/system_settings/`` matches no direct arm — it is neither results home — and then meets
    the ancestor arm, which is true of it: the results folder is beneath it. So the refusal is
    right and its wording is about the results folder rather than the prefix the user selected.
    """
    with pytest.raises(TerminalError) as caught:
        assert_not_results_folder("alice/", "alice/system_settings/")

    assert caught.value.reason == "results_not_sendable"
    assert "contains the results folder" in caught.value.detail


def test_a_users_own_nested_results_folder_still_sends():
    """The anchoring did not widen: only the two root-anchored homes are refused."""
    assert assert_not_results_folder("alice/", "alice/reports/athenaresults/") == "alice/reports/athenaresults/"
    assert assert_not_results_folder("alice/", "alice/athena-notes.txt") == "alice/athena-notes.txt"


def test_the_expansion_excludes_both_results_homes_and_one_settings_home():
    """The Out of Scope promise, executable, and the asymmetry is the whole assertion.

    Two prefixes, at different depths: the results folder moved and ``user_settings`` did not.
    Giving every excluded name the new prefix would make a receipt unsendable; leaving the results
    folder at the old one makes a user's own ``athenaresults/`` unsendable. Both are asserted.
    """
    ignore = _excluder("alice/")

    assert ignore("alice/system_settings/athenaresults/q.csv", 1, "alice/") is True
    assert ignore("alice/athenaresults/q.csv", 1, "alice/") is False
    assert ignore("alice/user_settings/inbox.json", 1, "alice/") is True
    assert ignore("alice/system_settings/user_settings/inbox.json", 1, "alice/") is False
    assert ignore("alice/system_settings/archive/receipt.txt", 1, "alice/") is False
