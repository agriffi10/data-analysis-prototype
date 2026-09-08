"""Both homes of a moving folder answer the same, on every rule this plane anchors at a root.

The rules are parametrised over the two locations rather than written twice, because the failure
this guards against is a rule that learned one home and not the other — which reads as working
code and refuses nothing where the data actually is.

Two of these rules build their prefix from a PARAMETER (``_is_root_folder`` and
``_is_under_root_folder``), which is why the path sweep cannot see them and why the coverage has
to be a test rather than a lint.
"""

import pytest
from focommon.protected import (
    destination_refusal,
    settings_source_refusal,
    source_refusal,
)

BOTH_HOMES = pytest.mark.parametrize("home", ["alice/{}/", "alice/system_settings/{}/"])


@BOTH_HOMES
def test_a_paste_into_either_home_of_a_locked_folder_is_refused_alike(home):
    """``_is_under_root_folder``, the picker mirror — the folder itself and anything under it.

    **The DETAIL is asserted, not just the reason.** ``system_settings`` is itself in this list, so
    a rule that learned only the depth-one home still refuses ``alice/system_settings/athenaresults/``
    — as the settings prefix, with the same reason code. Measured: reverting the rule to the
    singular builder leaves a reason-only assertion green, which is the shape of a test that
    covers nothing.

    The subject is ``athenaresults`` because it is one of the two folders that MOVE, so it genuinely
    has both homes to be refused at. ``shared_tables`` stays at the space root — the tables in it
    were sent to this space and are the user's to edit — so it has one home, asserted below.
    """
    refusal = destination_refusal("alice/", home.format("athenaresults"), "personal")

    assert refusal is not None
    assert refusal.reason == "destination_folder_locked"
    assert refusal.detail.startswith("athenaresults/")


def test_shared_tables_is_refused_as_a_paste_target_at_its_one_home():
    """It does not move, and it is still not a paste target.

    Those are separate facts and it is worth keeping both visible. The folder stays at the space
    root because a shared table is data another space sent this one, and the user may edit it; it
    is refused as a PASTE destination for a different reason entirely — the share pipeline owns the
    layout, and a table's files acquiring neighbours is how a later projection read starts returning
    rows nobody wrote.
    """
    refusal = destination_refusal("alice/", "alice/shared_tables/", "personal")

    assert refusal is not None
    assert refusal.reason == "destination_folder_locked"
    assert refusal.detail.startswith("shared_tables/")


@BOTH_HOMES
def test_a_move_of_either_home_of_the_results_folder_is_refused_alike(home):
    """``_is_root_folder``, the undeletable-roots rule, which matches the folder itself only."""
    refusal = source_refusal("alice/", home.format("athenaresults"), "move", "personal")

    assert refusal is not None
    assert refusal.reason == "source_folder_undeletable"
    assert refusal.detail.startswith("athenaresults/")


@BOTH_HOMES
def test_a_receipt_in_either_home_is_read_only_alike(home):
    """``_is_at_or_below``'s anchored arm, in a personal space, where it is the only arm."""
    refusal = source_refusal("alice/", f"{home.format('archive')}r.txt", "delete", "personal")

    assert refusal is not None
    assert refusal.reason == "archive_read_only"


@BOTH_HOMES
def test_a_receipt_in_either_home_is_read_only_in_a_shared_space_too(home):
    """The shared arm is any-depth and reaches both homes without being re-pointed.

    **The key sits one segment BELOW the root**, which is what makes this about the shared arm at
    all: a key at the root-anchored home is caught by the anchored arm whichever space it is in, so
    a fixture there passes with the shared arm deleted outright — measured, and true at base too.
    """
    key = f"finance/projects/{home.format('archive').split('/', 1)[1]}r.txt"

    refusal = source_refusal("finance/", key, "delete", "shared")

    assert refusal is not None
    assert refusal.reason == "archive_read_only"


def test_the_settings_folder_gains_no_second_home():
    """The Out of Scope promise, executable: a non-moving folder is refused at depth one only.

    ``alice/system_settings/user_settings/`` is not the settings folder — what refuses a source
    beneath the new prefix is the ``system_settings`` rule itself, by that name, and this plane's
    settings rule must not claim it.
    """
    assert settings_source_refusal("alice/", "alice/user_settings/x") is not None
    assert settings_source_refusal("alice/", "alice/system_settings/user_settings/x") is None


def test_the_settings_prefix_itself_is_refused_as_a_destination_and_a_source():
    """The prefix joined both lists, so it is neither a paste target nor movable at the root."""
    destination = destination_refusal("alice/", "alice/system_settings/", "personal")
    source = source_refusal("alice/", "alice/system_settings/", "move", "personal")

    assert destination is not None and destination.reason == "destination_folder_locked"
    assert source is not None and source.reason == "source_folder_undeletable"


def test_a_users_own_nested_folder_of_the_same_name_stays_ordinary():
    """The anchoring did not widen: only the two ROOT-anchored homes match, in a personal space."""
    assert source_refusal("alice/", "alice/backups/archive/", "delete", "personal") is None
    assert destination_refusal("alice/", "alice/reports/shared_tables/", "personal") is None


def test_the_any_depth_delete_rule_reaches_the_new_home_without_being_re_pointed():
    """``focommon.delete``'s rule mirrors IAM, not the browser, and its wildcard already matches.

    Named by the spec among the rules that are NOT re-pointed. It reads folder SEGMENTS, so
    ``system_settings/`` in the middle of a key changes nothing — but that is a claim about
    behaviour and it is asserted here rather than assumed, which is what the spec asks for.
    """
    from cpcommon.errors import TerminalError
    from focommon import delete

    for key in ("alice/archive/r.txt", "alice/system_settings/archive/r.txt"):
        try:
            delete.assert_item_deletable([key], "alice/")
        except TerminalError as exc:
            assert exc.reason == "delete_refused", key
            assert "archive" in exc.detail, key
        else:
            raise AssertionError(f"{key} was accepted for deletion")


def test_a_file_named_like_a_folder_under_the_new_prefix_is_still_deletable():
    """The segment rule needs a segment AFTER the name, so a FILE called `archive` is a file."""
    from focommon import delete

    delete.assert_item_deletable(["alice/system_settings/archive"], "alice/")


def test_which_rule_answers_first_in_a_SHARED_space_changed_and_is_pinned_here():
    """A moving folder's new home in a shared space is now named by the ROOT-ANCHORED rule.

    **Inherited, not chosen, and recorded because it is invisible until the folder is real.** In a
    shared space these keys used to fall through the root-anchored rules — which did not know the
    second home — and be caught by the any-depth arms, answering ``archive_read_only`` and
    ``destination_archive_read_only``. The re-pointed rules now match first, so the reason code and
    its wording change even though the ANSWER (refused, and why a user cannot do it) does not.

    Nothing user-visible moves today: nothing is written under the prefix. It becomes visible when
    the migration writes there, and a reader then deserves to find that it changed here rather than
    to discover it as an unexplained difference.
    """
    source = source_refusal("finance/", "finance/system_settings/archive/", "delete", "shared")
    destination = destination_refusal("finance/", "finance/system_settings/archive/", "shared")

    assert source is not None and source.reason == "source_folder_undeletable"
    assert destination is not None and destination.reason == "destination_folder_locked"

    # The DEPTH-ONE home is untouched: it was named by the root-anchored rules before and still is.
    old_home = source_refusal("finance/", "finance/archive/", "delete", "shared")
    assert old_home is not None and old_home.reason == "source_folder_undeletable"
