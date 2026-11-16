"""A moving folder is refused at its ONE home, and the home it left is ordinary again.

The rules stay parametrised over the two locations after the narrowing, and the expectations now
differ per row. Collapsing to a single row would have been the cheaper edit and a worse test: it
would go green just as happily against a rule that still refused at depth one, which is the exact
regression the narrowing can introduce and the only one a reader of this file would want caught.

Two of these rules build their prefix from a PARAMETER (``_is_root_folder`` and
``_is_under_root_folder``), which is why the path sweep cannot see them and why the coverage has
to be a test rather than a lint.
"""

import pytest
from focommon import messages
from focommon.protected import (
    derived_destination_refusal,
    destination_refusal,
    settings_source_refusal,
    source_refusal,
)

BOTH_HOMES = pytest.mark.parametrize(
    ("home", "refused"),
    [("alice/{}/", False), ("alice/system_settings/{}/", True)],
    ids=["the-home-it-left", "the-app-managed-home"],
)


@BOTH_HOMES
def test_a_paste_is_refused_at_the_app_managed_home_and_nowhere_else(home, refused):
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
    refusal = destination_refusal("alice/", home.format("athenaresults"))

    if not refused:
        assert refusal is None
        return
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
    refusal = destination_refusal("alice/", "alice/shared_tables/")

    assert refusal is not None
    assert refusal.reason == "destination_folder_locked"
    assert refusal.detail.startswith("shared_tables/")


@BOTH_HOMES
def test_a_move_of_the_results_folder_is_refused_at_its_home_only(home, refused):
    """``_is_root_folder``, the undeletable-roots rule, which matches the folder itself only."""
    refusal = source_refusal("alice/", home.format("athenaresults"), "move", "personal")

    if not refused:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.reason == "source_folder_undeletable"
    assert refusal.detail.startswith("athenaresults/")


@BOTH_HOMES
def test_a_receipt_is_read_only_at_its_home_and_the_old_one_is_ordinary(home, refused):
    """``_is_at_or_below``'s anchored arm, in a personal space, where it is the only arm."""
    refusal = source_refusal("alice/", f"{home.format('archive')}r.txt", "delete", "personal")

    if not refused:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.reason == "archive_read_only"


@BOTH_HOMES
def test_the_shared_any_depth_arm_follows_the_folder_rather_than_its_name(home, refused):
    """The shared arm scans SEGMENTS, and the narrowing changed which segments it scans for.

    **The key sits one segment BELOW the root**, which is what makes this about the shared arm at
    all: a key at the root-anchored home is caught by the anchored arm whichever space it is in, so
    a fixture there passes with the shared arm deleted outright — measured, and true at base too.

    The retired row is the one that earns this test its place now. ``finance/projects/archive/``
    is a folder a user made, in a shared space, and the Deny that used to reach it is gone — so an
    arm still keyed on the bare name refuses a delete IAM permits, and only a row expecting ``None``
    can see that.
    """
    key = f"finance/projects/{home.format('archive').split('/', 1)[1]}r.txt"

    refusal = source_refusal("finance/", key, "delete", "shared")

    if not refused:
        assert refusal is None
        return
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
    destination = destination_refusal("alice/", "alice/system_settings/")
    source = source_refusal("alice/", "alice/system_settings/", "move", "personal")

    assert destination is not None and destination.reason == "destination_folder_locked"
    assert source is not None and source.reason == "source_folder_undeletable"


def test_a_users_own_nested_folder_of_the_same_name_stays_ordinary():
    """The anchoring did not widen: only the two ROOT-anchored homes match, in a personal space."""
    assert source_refusal("alice/", "alice/backups/archive/", "delete", "personal") is None
    assert destination_refusal("alice/", "alice/reports/shared_tables/") is None


def test_the_any_depth_delete_rule_reaches_the_new_home_without_being_re_pointed():
    """``focommon.delete``'s rule mirrors IAM, not the browser, and its wildcard already matches.

    Named by the spec among the rules that are NOT re-pointed. It reads folder SEGMENTS, so
    ``system_settings/`` in the middle of a key changes nothing — but that is a claim about
    behaviour and it is asserted here rather than assumed, which is what the spec asks for.
    """
    from cpcommon.errors import TerminalError
    from focommon import delete

    try:
        delete.assert_item_deletable(["alice/system_settings/archive/r.txt"], "alice/")
    except TerminalError as exc:
        assert exc.reason == "delete_refused"
        assert "archive" in exc.detail
    else:
        raise AssertionError("the app-managed receipt key was accepted for deletion")

    # And the home it left is deletable again, which is the half the narrowing added.
    delete.assert_item_deletable(["alice/archive/r.txt"], "alice/")


def test_a_file_named_like_a_folder_under_the_new_prefix_is_still_deletable():
    """The segment rule needs a segment AFTER the name, so a FILE called `archive` is a file."""
    from focommon import delete

    delete.assert_item_deletable(["alice/system_settings/archive"], "alice/")


def test_which_rule_answers_first_in_a_SHARED_space_changed_and_is_pinned_here():
    """A moving folder's new home in a shared space is now named by the ROOT-ANCHORED rule.

    **Inherited, not chosen, and recorded because it is invisible until the folder is real.** In a
    shared space these keys used to fall through the root-anchored rules — which did not know the
    second home — and be caught by the any-depth arms, answering with those arms' own reasons. The
    re-pointed rules now match first, so the reason code and its wording change even though the
    ANSWER (refused, and why a user cannot do it) does not.

    Nothing user-visible moves today: nothing is written under the prefix. It becomes visible when
    the migration writes there, and a reader then deserves to find that it changed here rather than
    to discover it as an unexplained difference.
    """
    source = source_refusal("finance/", "finance/system_settings/archive/", "delete", "shared")
    destination = destination_refusal("finance/", "finance/system_settings/archive/")

    assert source is not None and source.reason == "source_folder_undeletable"
    assert destination is not None and destination.reason == "destination_folder_locked"

    # The DEPTH-ONE home is ordinary now — the narrowing removed the last rule that named it.
    assert source_refusal("finance/", "finance/archive/", "delete", "shared") is None


_LOCKED = "destination_name_reserved"
_KEPT = "destination_name_kept_for_app"


@pytest.mark.parametrize(
    ("root", "key", "folder", "reason"),
    [
        ("sales/", "sales/_data-quality-reports/", "_data-quality-reports/", _LOCKED),
        ("alice/", "alice/shared_tables/", "shared_tables/", _LOCKED),
        ("finance/", "finance/projects/system_settings/archive/", "archive/", _KEPT),
        ("alice/", "alice/projects/system_settings/archive/", "archive/", _KEPT),
        ("alice/", "alice/stage/user_settings/", "user_settings/", _KEPT),
        ("alice/", "alice/_data-quality-reports", None, None),
        ("sales/", "sales/stage/_data-quality-reports/", None, None),
        ("alice/", "alice/stage/user_settings", None, None),
    ],
    ids=[
        "reports-folder",
        "shared-tables",
        "shared-any-depth-archive",
        "personal-any-depth-archive",
        "nested-settings-folder",
        "a-file-so-named",
        "nested-reports-folder",
        "a-file-named-like-the-settings-folder",
    ],
)
def test_a_derived_key_is_refused_where_the_prefix_rule_refuses_and_names_the_folder(
    root, key, folder, reason
):
    """The item's own landing key, judged by the prefix's two rules, each under its own reason code.

    Two codes because what can truthfully be said differs: a picker-locked name is the app's own
    folder at that root, so another destination is a step worth offering; one of the role's names is
    refused wherever it lands, often for a folder the user made, so its sentence names no step at
    all — a rename is itself refused for a folder that already sits inside one.

    The archive row is the one the prefix rule alone cannot reach even in principle: its parent
    ``finance/projects/system_settings/`` holds no ``system_settings/archive`` pair, so only the
    derived key does. The ``None`` rows are what keeps it from refusing a user's own folder, or a file
    that only shares a folder's name. The personal archive row was accepted while the rule followed
    the portal role's policies rather than the execution role that does the write.
    """
    refusal = derived_destination_refusal(root, key)

    if folder is None:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.reason == reason
    assert refusal.detail.startswith(folder)


@pytest.mark.parametrize(
    ("key", "operation", "refused"),
    [
        ("sales/_data-quality-reports/req-1/report.json", "delete", True),
        ("sales/_data-quality-reports/", "move", True),
        ("sales/_data-quality-reports/req-1/report.json", "copy", False),
        ("sales/stage/_data-quality-reports/req-1/report.json", "delete", False),
        ("sales/_data-quality-reports", "delete", False),
    ],
    ids=["delete-a-report", "move-the-folder", "copy-out", "nested-folder", "a-file-so-named"],
)
def test_the_reports_folder_is_neither_deleted_nor_moved_and_copying_out_stays_free(
    key, operation, refused
):
    """Root-anchored in a SHARED space too, where one folder holds every member's reports."""
    refusal = source_refusal("sales/", key, operation, "shared")

    if not refused:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.reason == "reports_folder_not_deletable"


@pytest.mark.parametrize(
    ("prefix", "folder"),
    [
        ("alice/foo/user_settings/", "user_settings/"),
        ("alice/a/b/system_settings/athenaresults/q/", "athenaresults/"),
        ("alice/backups/system_settings/archive/", "archive/"),
        ("finance/foo/user_settings/", "user_settings/"),
        ("finance/foo/system_settings/athenaresults/", "athenaresults/"),
        ("finance/foo/system_settings/archive/", "archive/"),
        ("alice/foo/archive/", None),
        ("alice/foo/athenaresults/", None),
        ("alice/system_settings/x/archive/", "system_settings/"),
    ],
    ids=[
        "personal-settings",
        "personal-results-deep",
        "personal-archive",
        "shared-settings",
        "shared-results",
        "shared-archive",
        "a-users-own-archive",
        "a-users-own-athenaresults",
        "a-split-pair-is-locked-by-its-root-folder-only",
    ],
)
def test_a_destination_under_one_of_the_roles_folders_is_refused_below_the_root_in_either_space(
    prefix, folder
):
    """The execution role denies these writes at any depth, so the prefix is refused before a run.

    Every refused row but the shared archive row and the last was accepted while this rule followed
    the picker and the portal role's policies, and failed at the write with ``AccessDenied``.
    The reason is the any-depth arm's own, not the locked folder's, except on the last row:
    ``system_settings/`` at the root is picker-locked in its own right, and that rule answers first.
    """
    root = prefix.split("/", 1)[0] + "/"

    refusal = destination_refusal(root, prefix)

    if folder is None:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.detail.startswith(folder)
    assert refusal.reason == (
        "destination_folder_locked" if folder == "system_settings/" else "destination_folder_reserved"
    )


@pytest.mark.parametrize(
    ("operation", "refused"),
    [("move", True), ("delete", True), ("copy", False)],
)
def test_a_nested_role_folder_is_refused_as_a_move_or_delete_source_and_copying_out_stays_free(
    operation, refused
):
    """Refused at the front door, so a move is not first told its NAME is the problem.

    The manifest builder would refuse the same item before anything copied; judged there, a move of
    ``alice/f/user_settings/`` into ``alice/g/`` reached the derived-key rule first and was told to
    choose a different name, which no name fixes.
    """
    refusal = source_refusal("alice/", "alice/f/user_settings/", operation, "personal")

    if not refused:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.reason == "delete_refused"
    assert refusal.detail.startswith("user_settings/")


def test_both_new_refusals_reach_the_user_as_their_own_sentence_rather_than_the_fallback():
    """A reason with no body renders "something went wrong." — the code alone cannot show that."""
    reserved = messages.item_clause(
        "move", {"outcome": "protected", "reason": "destination_name_reserved"}
    )
    reports = messages.item_clause(
        "delete", {"outcome": "protected", "reason": "reports_folder_not_deletable"}
    )

    assert reserved.startswith("that name belongs to a folder the app manages there. Please choose")
    assert reports == "data-quality reports are managed for you and cannot be moved or deleted."


def test_the_role_folder_refusals_reach_the_user_as_their_own_sentence_rather_than_the_fallback():
    """The prefix's whole-request body, and the derived key's and the manifest's per-item bodies."""
    prefix = messages.copy_resolver.body("destination_folder_reserved")
    planned = messages.item_clause("copy", {"outcome": "protected", "reason": "write_refused"})
    kept = messages.item_clause(
        "copy", {"outcome": "protected", "reason": "destination_name_kept_for_app"}
    )

    assert prefix == (
        "that folder, or one it sits in, has a name the app keeps for its own folders, so folders "
        "and groups of files cannot be put into it."
    )
    assert planned == (
        "part of it would land in a folder with a name the app keeps for its own folders, so it "
        "was left alone."
    )
    assert kept == (
        "its name there is one the app keeps for its own folders, so it cannot be put there under "
        "that name."
    )
