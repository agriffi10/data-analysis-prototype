"""The app-managed folder names and the builders every anchored rule goes through."""

from cpcommon import app_managed, s3_listing


def test_the_three_moving_folders_resolve_to_todays_names():
    """The names every anchored rule now spells through this module, as the strings IAM knows."""
    assert (
        app_managed.ATHENA_RESULTS_FOLDER,
        app_managed.RECEIPT_FOLDER,
        app_managed.SHARED_TABLES_FOLDER,
    ) == ("athenaresults", "archive", "shared_tables")


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


def test_the_plural_builder_gives_a_moving_folder_two_homes_and_everything_else_one():
    """Spelled out as literals: a non-moving name must never acquire a phantom second home."""
    assert app_managed.app_managed_prefixes("alice/", "archive") == (
        "alice/archive/",
        "alice/system_settings/archive/",
    )
    assert app_managed.app_managed_prefixes("alice/", "user_settings") == ("alice/user_settings/",)
    assert app_managed.app_managed_prefixes("alice/", "system_settings") == ("alice/system_settings/",)
    # Two, not three. SPACE_FOLDERS still holds all three app-managed folders; this asks which of
    # them MOVE, and shared_tables does not — which is why the two are separate tuples rather than
    # one aliased to the other, and the difference is now observable rather than coincidental.
    assert app_managed.MOVING_FOLDERS == ("athenaresults", "archive")
    assert app_managed.SPACE_FOLDERS == ("athenaresults", "archive", "shared_tables")
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


def test_the_plural_still_answers_the_old_home_the_singular_has_left():
    """The two now legitimately differ, and the old home is where the data still IS.

    This replaces the equality assertion that pinned them together while the write was still at
    depth one. Re-pointing that one to the new value would have been the wrong repair — it would
    restore exactly the coupling the plural's literals exist to avoid. What matters after the
    switch is the opposite property: the plural's FIRST element is still the depth-one path, so
    every rule built on it keeps refusing where the objects have not moved from yet.
    """
    for root in ("", "alice/", "finance/"):
        for folder in ("athenaresults", "archive"):
            homes = app_managed.app_managed_prefixes(root, folder)
            assert homes[0] == f"{root}{folder}/"
            assert homes[1] == app_managed.app_managed_prefix(root, folder)
            assert homes[0] != homes[1]
        for stays in ("shared_tables", "user_settings", "system_settings"):
            assert app_managed.app_managed_prefixes(root, stays) == (
                app_managed.app_managed_prefix(root, stays),
            )


def test_the_builders_normalize_nothing():
    """A caller's bytes come back unchanged, so a digest over the result cannot move."""
    assert app_managed.app_managed_prefix("", "archive") == "system_settings/archive/"
    assert app_managed.vault_archive_prefix("personal", "", "x") == "personal/archive/x/"
    assert app_managed.vault_archive_prefix("personal", "alice//", "x") == "personal/alice//archive/x/"


def test_the_listing_ignores_exactly_these_three_subtrees():
    """The listing's own first-segment rule, spelled out; the results folder has two homes now."""
    assert s3_listing._IGNORED_SUBTREES == (
        "athenaresults/",
        "system_settings/athenaresults/",
        "user_settings/",
    )
