"""Both homes of the results folder are unsendable, and only the results folder gains a second one.

The send plane excludes exactly two folders from an expansion, and the two are treated differently
on purpose: the results folder is the one that moves, so it has two locations, while
``user_settings/`` keeps the one it has. A rule that gave every excluded folder a second home would
make a receipt under the new prefix unsendable, which is a narrowing this spec does not make.
"""

import pytest
from cpcommon.errors import TerminalError
from fscommon.authz import assert_not_results_folder
from fscommon.expand import _excluder

BOTH_HOMES = pytest.mark.parametrize("home", ["alice/{}/", "alice/system_settings/{}/"])


@BOTH_HOMES
def test_either_home_of_the_results_folder_is_refused_as_a_source(home):
    """The folder itself and anything beneath it, at both locations, with the same reason."""
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

    Three prefixes, not four: the results folder moves and has two, ``user_settings`` does not and
    keeps one. Giving every excluded name a second home would make a receipt unsendable after the
    move, which is a narrowing.
    """
    ignore = _excluder("alice/")

    assert ignore("alice/athenaresults/q.csv", 1, "alice/") is True
    assert ignore("alice/system_settings/athenaresults/q.csv", 1, "alice/") is True
    assert ignore("alice/user_settings/inbox.json", 1, "alice/") is True
    assert ignore("alice/system_settings/user_settings/inbox.json", 1, "alice/") is False
    assert ignore("alice/system_settings/archive/receipt.txt", 1, "alice/") is False
