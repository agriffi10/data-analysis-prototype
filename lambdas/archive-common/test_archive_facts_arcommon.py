"""The three facts the word ``archive`` names, and the lists this layer builds from the shared names.

Two of the three constants live in ``cpcommon.app_managed`` because two packages need each; the
third is this plane's own admin-bucket scratch prefix and stays here. A tripwire pins all three
equal TODAY, because they are equal by coincidence of naming rather than by rule, and the one that
moves must not drag the other two with it.
"""

from arcommon import config, plan
from cpcommon import app_managed


def test_ACCEPTED_the_three_archive_facts_are_spelled_the_same_today():
    """A tripwire, not a requirement: pins today's coincidence so the move has to look at it.

    ``RECEIPT_FOLDER`` (the user's receipt folder, space bucket) is the one that moves under
    ``system_settings/``. ``VAULT_ARCHIVE_SEGMENT`` (the Glacier vault key segment, hashed into
    FIFO group ids) and ``plan.PREFIX`` (admin-bucket scratch, pinned against an IAM grant and a
    lifecycle rule) do not. When the receipt folder moves, REVISIT this decision — the three will
    legitimately differ, and this assertion should be rewritten to say which two still agree — but
    do not delete the test.
    """
    assert app_managed.RECEIPT_FOLDER == app_managed.VAULT_ARCHIVE_SEGMENT == plan.PREFIX == "archive"


def test_the_reserved_source_roots_are_exactly_these_five():
    """Spelled out, in order: the browser mirrors this tuple, so a seat moving is a divergence."""
    assert config.RESERVED_SOURCE_ROOTS == (
        "archive",
        "athenaresults",
        "user_settings",
        "_data-quality-reports",
        "shared_tables",
    )


def test_the_any_depth_undeletable_folders_are_exactly_these_three():
    """The plan module's own any-depth list, spelled out."""
    assert plan._UNDELETABLE_FOLDERS == ("archive", "athenaresults", "user_settings")
