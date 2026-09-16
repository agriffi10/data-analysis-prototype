"""The app-managed folder names and the builders every anchored rule goes through."""

import pytest
from cpcommon import app_managed, s3_listing


def test_the_three_moving_folders_resolve_to_todays_names():
    """The names every anchored rule now spells through this module, as the strings IAM knows."""
    assert (
        app_managed.ATHENA_RESULTS_FOLDER,
        app_managed.RECEIPT_FOLDER,
        app_managed.SHARED_TABLES_FOLDER,
    ) == ("athenaresults", "archive", "shared_tables")


def test_the_data_quality_reports_folder_is_declared_here_and_stays_at_the_space_root():
    """The plane writes it and every refusal reads it from here, so this is the one spelling left.

    Pinned as a literal because the value is what IAM and the objects already written know, and
    no refusal can tell a renamed constant from a correct one — each would follow it. The prefix
    row is the other half: the folder never moved, so its write home is depth one.
    """
    assert app_managed.DATA_QUALITY_REPORTS_FOLDER == "_data-quality-reports"
    assert (
        app_managed.app_managed_prefix("alice/", app_managed.DATA_QUALITY_REPORTS_FOLDER)
        == "alice/_data-quality-reports/"
    )
    assert app_managed.DATA_QUALITY_REPORTS_FOLDER not in app_managed.MOVING_FOLDERS


def test_a_moving_folder_anchors_under_system_settings_and_nothing_else_does():
    """Where a WRITE goes, after the switch — and the two facts that did not move with it.

    ``user_settings`` is the guard on the branch: the singular takes a folder name from a domain
    list as well as from this module's constants, and a caller loops it over eight names of which
    five stay where they are. Unconditional, this row would read
    ``alice/system_settings/user_settings/`` — a prefix nothing is stored under, and one whose
    refusal would keep working by accident because the caller's second leg matches the bare name at
    any depth.

    ``vault_archive_prefix`` is fact 2 of ``archive``: a different bucket, and it does not move.
    """
    assert app_managed.app_managed_prefix("alice/", "user_settings") == "alice/user_settings/"
    assert app_managed.athena_results_prefix("finance/") == "finance/system_settings/athenaresults/"
    assert app_managed.receipt_folder_prefix("alice/") == "alice/system_settings/archive/"
    # shared_tables does NOT move: those tables were sent to the space and are the user's to
    # edit, so filing them under the app's folder would say the opposite of what is true.
    assert app_managed.shared_tables_prefix("finance/") == "finance/shared_tables/"
    assert app_managed.vault_archive_prefix("personal", "alice/", "abc") == "personal/alice/archive/abc/"


def test_the_plural_builder_gives_every_folder_exactly_one_home():
    """Spelled out as literals: the second home is gone, and no name kept a phantom one."""
    assert app_managed.app_managed_prefixes("alice/", "archive") == (
        "alice/system_settings/archive/",
    )
    assert app_managed.app_managed_prefixes("alice/", "user_settings") == ("alice/user_settings/",)
    assert app_managed.app_managed_prefixes("alice/", "system_settings") == ("alice/system_settings/",)
    # Two, not four. SPACE_FOLDERS holds every app-managed folder declared here; this asks which
    # of them MOVED, and shared_tables and the reports folder did not — which is why the two are
    # separate tuples rather than one aliased to the other, and the difference is observable
    # rather than coincidental.
    assert app_managed.MOVING_FOLDERS == ("athenaresults", "archive")
    assert app_managed.SPACE_FOLDERS == ("athenaresults", "archive", "shared_tables", "_data-quality-reports")
    # Two separate declarations on purpose — one asks which folders the app manages in a space
    # bucket, the other which of them relocated — but a folder cannot relocate under a space's own
    # prefix without living in one, and nothing else states that direction.
    assert set(app_managed.MOVING_FOLDERS) <= set(app_managed.SPACE_FOLDERS)


def test_the_plural_builder_normalizes_nothing_either():
    """A caller's bytes come back unchanged, exactly as the singular's do."""
    assert app_managed.app_managed_prefixes("", "archive") == ("system_settings/archive/",)
    assert app_managed.app_managed_prefixes("alice//", "archive") == (
        "alice//system_settings/archive/",
    )


def test_the_plural_builder_now_DOES_call_the_singular_one(monkeypatch):
    """The inverse of what this asserted before the narrowing, and it is asserted for one reason.

    While both homes were admitted the plural spelled its elements out, because deriving them from
    the singular would have dragged every rule's second home to a third location the moment the
    write moved. With one home left, the duplication would be a rule written twice — the shape
    where one copy drifts and nothing notices — so the plural delegates, and this is what holds
    the delegation in place.

    Spelled-out equality cannot see the difference: a derived value and a literal one agree
    exactly. Replacing the singular with something recognisable is what tells them apart, and
    Python resolves a module global at CALL time, so a plural that had kept its literals would
    return the real prefix instead of the sentinel.
    """
    monkeypatch.setattr(app_managed, "app_managed_prefix", lambda root, folder: "SENTINEL/")

    assert app_managed.app_managed_prefixes("alice/", "archive") == ("SENTINEL/",)
    assert app_managed.app_managed_prefixes("alice/", "user_settings") == ("SENTINEL/",)


def test_the_plural_and_the_singular_now_answer_the_same_thing():
    """One home each, for every name — the property the narrowing was for.

    This replaces the assertion that pinned the plural's FIRST element to the depth-one path while
    the objects were still there. They have moved, the old prefixes are proved empty and their
    fences are gone, so a depth-one ``alice/archive/`` is an ordinary user folder and the two
    builders agree everywhere.
    """
    for root in ("", "alice/", "finance/"):
        for folder in ("athenaresults", "archive", "shared_tables", "user_settings", "system_settings"):
            assert app_managed.app_managed_prefixes(root, folder) == (
                app_managed.app_managed_prefix(root, folder),
            )


def test_the_builders_normalize_nothing():
    """A caller's bytes come back unchanged, so a digest over the result cannot move."""
    assert app_managed.app_managed_prefix("", "archive") == "system_settings/archive/"
    assert app_managed.vault_archive_prefix("personal", "", "x") == "personal/archive/x/"
    assert app_managed.vault_archive_prefix("personal", "alice//", "x") == "personal/alice//archive/x/"


def test_the_listing_ignores_exactly_these_two_subtrees():
    """The listing's own first-segment rule, spelled out; the results folder has one home again."""
    assert s3_listing._IGNORED_SUBTREES == (
        "system_settings/athenaresults/",
        "user_settings/",
    )


SEGMENT_CASES = [
    # (segments, folder, held, why this row is in the table)
    ([], "archive", False, "an empty list — the loop must not read past the end"),
    (["system_settings", "archive"], "archive", True, "the pair, exactly"),
    (["a", "system_settings", "archive"], "archive", True, "the pair, below a user folder"),
    (["system_settings", "archive", "b"], "archive", True, "the pair, above a user folder"),
    (["archive"], "archive", False, "the NAME the folder left — the whole narrowing"),
    (["a", "archive", "b"], "archive", False, "the name it left, nested"),
    (["system_settings"], "archive", False, "the parent alone is not the folder"),
    (["system_settings", "x", "archive"], "archive", False, "a SPLIT pair is not the folder"),
    (["archive", "system_settings"], "archive", False, "the pair reversed is not the pair"),
    (["system_settings", "system_settings", "archive"], "archive", True, "a doubled parent"),
    (["user_settings"], "user_settings", True, "a folder that did NOT move, at depth one"),
    # TRUE, and this row was written expecting False. A non-moving folder's Deny did not move
    # either: the shared one is still `*/user_settings/*`, and an S3 wildcard matches `/`, so it
    # reaches that name at ANY depth including under the new prefix. The mirror has to answer what
    # the Deny answers, not what the browser's root-anchored rule answers — those are different
    # questions, and `_is_under_root_folder` is the one that asks the other.
    (["system_settings", "user_settings"], "user_settings", True, "a non-moving name, at any depth"),
    (["archived"], "archive", False, "segment equality, never a substring"),
]


@pytest.mark.parametrize(("segments", "folder", "held", "why"), SEGMENT_CASES)
def test_the_segment_predicate_answers_each_boundary_case(segments, folder, held, why):
    """``segments_hold_app_managed``'s own table, rather than one borrowed from a caller.

    It had none when it landed: four of its five call sites' suites reddened when it was broken,
    but only ONE assertion anywhere discriminated a SPLIT pair, and it lived in an API test. A
    predicate that five rules delegate to owes its own boundary table, because a caller's suite
    tests the caller.

    Args:
      segments: The key's segments below the space root.
      folder: The folder name asked about.
      held: What the predicate must answer.
      why: The property this row is here for, so a deleted row is a visible loss.

    Returns:
      None.

    Raises:
      AssertionError: When the predicate disagrees.
    """
    assert app_managed.segments_hold_app_managed(segments, folder) is held, why


def test_the_segments_builder_pairs_only_the_folders_that_moved():
    """The two tuples the predicate is built on, spelled out."""
    assert app_managed.app_managed_segments("archive") == ("system_settings", "archive")
    assert app_managed.app_managed_segments("athenaresults") == ("system_settings", "athenaresults")
    assert app_managed.app_managed_segments("user_settings") == ("user_settings",)
    assert app_managed.app_managed_segments("shared_tables") == ("shared_tables",)
