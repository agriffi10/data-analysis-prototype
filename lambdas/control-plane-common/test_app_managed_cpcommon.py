"""The app-managed folder names and the builders every anchored rule goes through."""

from cpcommon import app_managed, s3_listing


def test_the_three_moving_folders_resolve_to_todays_names():
    """The names every anchored rule now spells through this module, as the strings IAM knows."""
    assert (
        app_managed.ATHENA_RESULTS_FOLDER,
        app_managed.RECEIPT_FOLDER,
        app_managed.SHARED_TABLES_FOLDER,
    ) == ("athenaresults", "archive", "shared_tables")


def test_the_builders_anchor_directly_under_the_root_they_are_handed():
    """Depth one, today: the move is a change to these outputs and to nothing else."""
    assert app_managed.app_managed_prefix("alice/", "user_settings") == "alice/user_settings/"
    assert app_managed.athena_results_prefix("finance/") == "finance/athenaresults/"
    assert app_managed.receipt_folder_prefix("alice/") == "alice/archive/"
    assert app_managed.shared_tables_prefix("finance/") == "finance/shared_tables/"
    assert app_managed.vault_archive_prefix("personal", "alice/", "abc") == "personal/alice/archive/abc/"


def test_the_builders_normalize_nothing():
    """A caller's bytes come back unchanged, so a digest over the result cannot move."""
    assert app_managed.app_managed_prefix("", "archive") == "archive/"
    assert app_managed.vault_archive_prefix("personal", "", "x") == "personal/archive/x/"
    assert app_managed.vault_archive_prefix("personal", "alice//", "x") == "personal/alice//archive/x/"


def test_the_listing_ignores_exactly_these_two_subtrees():
    """The listing's own first-segment rule, spelled out; it is anchored without the builder."""
    assert s3_listing._IGNORED_SUBTREES == ("athenaresults/", "user_settings/")
