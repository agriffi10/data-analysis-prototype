"""The file-send folder names, member for member, now that one of them is shared."""

from fscommon import config, expand


def test_the_results_folder_resolves_to_todays_name():
    """The re-export from cpcommon resolves to the string the IAM Deny is written against."""
    assert config.ATHENA_RESULTS_FOLDER == "athenaresults"


def test_the_portal_managed_folders_are_exactly_these_two():
    """The two folders a send never carries out, spelled out."""
    assert expand._PORTAL_MANAGED_FOLDERS == ("athenaresults", "user_settings")
