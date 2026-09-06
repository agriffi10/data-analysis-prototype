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


def test_the_plural_builder_gives_a_moving_folder_two_homes_and_everything_else_one():
    """Spelled out as literals: a non-moving name must never acquire a phantom second home."""
    assert app_managed.app_managed_prefixes("alice/", "archive") == (
        "alice/archive/",
        "alice/system_settings/archive/",
    )
    assert app_managed.app_managed_prefixes("alice/", "user_settings") == ("alice/user_settings/",)
    assert app_managed.app_managed_prefixes("alice/", "system_settings") == ("alice/system_settings/",)
    assert app_managed.MOVING_FOLDERS == ("athenaresults", "archive", "shared_tables")
    # Two separate declarations on purpose — one asks which folders the app manages in a space
    # bucket, the other which of them relocate — but a folder cannot relocate under a space's own
    # prefix without living in one, and nothing else states that direction.
    assert set(app_managed.MOVING_FOLDERS) <= set(app_managed.SPACE_FOLDERS)


def test_the_plural_builder_normalizes_nothing_either():
    """A caller's bytes come back unchanged, at both homes, exactly as the singular's do."""
    assert app_managed.app_managed_prefixes("", "archive") == ("archive/", "system_settings/archive/")
    assert app_managed.app_managed_prefixes("alice//", "archive") == (
        "alice//archive/",
        "alice//system_settings/archive/",
    )


def test_the_plural_builder_does_not_CALL_the_singular_one(monkeypatch):
    """The duplication is the point, and until now nothing enforced it.

    Both docstrings state in bold that neither element is derived from ``app_managed_prefix``,
    because the singular is where a write goes and the migration moves it: derived, the second home
    would become ``{root}system_settings/system_settings/{folder}/`` the moment it does. The
    literals-spelled-out test above cannot see the difference, since a derived value and a literal
    one agree exactly while the singular is still depth-one — which is every day until the move.

    Replacing the singular with something recognisable is what tells them apart. Python resolves a
    module global at CALL time, so a plural that reached for it would return the sentinel.
    """
    monkeypatch.setattr(app_managed, "app_managed_prefix", lambda root, folder: "SENTINEL/")

    assert app_managed.app_managed_prefixes("alice/", "archive") == (
        "alice/archive/",
        "alice/system_settings/archive/",
    )
    assert app_managed.app_managed_prefixes("alice/", "user_settings") == ("alice/user_settings/",)


def test_the_plural_builders_first_element_is_the_singular_TODAY():
    """The one assertion tying the two together, and SPEC-220 FR-001 DELETES it.

    The plural spells both homes as literals precisely so the singular can move without dragging
    them; this pins that they agree while the write still goes to depth one. When the singular
    moves, this is the test that is expected to fail, and deleting it is the right response —
    not re-pointing it, which would restore the coupling the literals exist to avoid.
    """
    for root in ("", "alice/", "finance/"):
        for folder in ("athenaresults", "archive", "shared_tables", "user_settings", "system_settings"):
            assert app_managed.app_managed_prefixes(root, folder)[0] == app_managed.app_managed_prefix(root, folder)


def test_the_builders_normalize_nothing():
    """A caller's bytes come back unchanged, so a digest over the result cannot move."""
    assert app_managed.app_managed_prefix("", "archive") == "archive/"
    assert app_managed.vault_archive_prefix("personal", "", "x") == "personal/archive/x/"
    assert app_managed.vault_archive_prefix("personal", "alice//", "x") == "personal/alice//archive/x/"


def test_the_listing_ignores_exactly_these_three_subtrees():
    """The listing's own first-segment rule, spelled out; the results folder has two homes now."""
    assert s3_listing._IGNORED_SUBTREES == (
        "athenaresults/",
        "system_settings/athenaresults/",
        "user_settings/",
    )
