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

    ``RECEIPT_FOLDER`` (the user's receipt folder, space bucket) is the one that moved under
    ``system_settings/``. ``VAULT_ARCHIVE_SEGMENT`` (the Glacier vault key segment, hashed into
    FIFO group ids) and ``plan.PREFIX`` (admin-bucket scratch, pinned against an IAM grant and a
    lifecycle rule) did not.

    **REVISITED at the move, and the assertion stands unchanged.** It was expected to have to say
    which two still agree, and the answer is all three: this pins the folder NAMES, and the receipt
    folder kept its name — what changed is its parent. The three facts are still spelled the same
    and still mean three different things, which is exactly the coincidence worth pinning, so the
    tripwire is as valuable after the move as before it. The assertion that DID have to change is
    the one comparing the two path BUILDERS, which is a different test in a different layer.
    """
    assert app_managed.RECEIPT_FOLDER == app_managed.VAULT_ARCHIVE_SEGMENT == plan.PREFIX == "archive"


def test_the_reserved_source_roots_are_exactly_these_six():
    """Spelled out, in order: the browser mirrors this tuple, so a seat moving is a divergence."""
    assert config.RESERVED_SOURCE_ROOTS == (
        "archive",
        "athenaresults",
        "user_settings",
        "_data-quality-reports",
        "shared_tables",
        "system_settings",
    )


def test_the_any_depth_undeletable_folders_are_exactly_these_three():
    """The plan module's own any-depth list, spelled out."""
    assert plan._UNDELETABLE_FOLDERS == ("archive", "athenaresults", "user_settings")
