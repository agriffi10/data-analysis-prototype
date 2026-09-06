"""The file-operations lists, member for member, now that three of their names are shared."""

from focommon import config, delete


def test_the_picker_locked_folders_are_exactly_these_eight():
    """Spelled out, in order: three members now come from cpcommon and must not move a seat."""
    assert config.PICKER_LOCKED_FOLDERS == (
        "athenaresults",
        "user_settings",
        "_data-quality-reports",
        "_directory",
        "_config",
        "shared_tables",
        "archive",
        "system_settings",
    )


def test_the_undeletable_root_folders_are_exactly_these_four():
    """Spelled out, in order."""
    assert config.UNDELETABLE_ROOT_FOLDERS == ("athenaresults", "saved_queries", "archive", "system_settings")


def test_the_any_depth_undeletable_folders_are_exactly_these_three():
    """The delete module's own any-depth list, spelled out."""
    assert delete._UNDELETABLE_FOLDERS == ("athenaresults", "user_settings", "archive")
