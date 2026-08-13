"""The archive plane's user-facing wording.

SPEC-106: raw AWS text is never shown. The detail on a terminal error is for the logs and the
Step Functions record; the sentence a user reads is composed here.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import config, messages
from cpcommon.errors import TerminalError


def test_every_reason_code_renders_a_sentence_with_the_planes_prefix():
    for reason in messages._BODIES:
        text = messages.failure_message(reason)

        assert text.startswith("Couldn't archive that: ")
        assert text.endswith((".", "!"))


def test_every_reason_code_is_a_valid_terminal_error_reason():
    """Importing the table is what REGISTERS these codes; TerminalError validates its reason
    at the RAISE site, so an unregistered one raises ValueError where a refusal was meant."""
    for reason in messages._BODIES:
        assert TerminalError(reason, "detail").reason == reason


def test_the_cap_sentence_is_filled_from_the_constant_that_enforces_it():
    """A number written into the wording is a number that drifts from the cap silently — the
    user is told a limit the code does not have."""
    text = messages.failure_message("too_many_items")

    assert str(config.ARCHIVE_MAX_ITEMS) in text
    assert "{maxItems}" not in text


def test_an_unknown_reason_falls_back_rather_than_leaking_the_code():
    text = messages.failure_message("some_code_nobody_registered")

    assert "some_code_nobody_registered" not in text
    assert text == "Couldn't archive that: something went wrong."


def test_no_body_leaves_an_unfilled_marker():
    """`blank_unfilled=True` blanks a marker nothing supplied, so a body whose token never
    arrives renders a gap rather than `{itemName}` — asserted across the whole table because
    the failure is per-body and invisible until that one reason fires."""
    for reason in messages._BODIES:
        assert "{" not in messages.failure_message(reason)


def test_a_raise_site_token_fills_its_marker():
    """`{itemName}` is the ONE marker this module cannot fill itself — it is the user's own
    file name, not a number from `config`. An earlier version of this test asserted only the
    shared prefix, which is true of every message here, and no body carried the marker at all.
    """
    assert "{itemName}" in messages._BODIES["protected_marker"]

    text = messages.failure_message("protected_marker", tokens={"itemName": "DO_NOT_DELETE.txt"})

    assert "DO_NOT_DELETE.txt" in text
    assert "{itemName}" not in text


def test_every_marker_in_every_body_can_be_filled_by_somebody():
    """A marker no caller supplies renders BLANK (`blank_unfilled=True`), which reads as a
    typo in the sentence rather than as a bug — so it must be caught here."""
    fillable = {
        "maxItems",
        "maxObjects",
        "itemName",
        "copied",
        "total",
        "failed",
        "residue",
        "requestId",
        "folderName",
        # SPEC-170's restore refusals. Every one is filled from its raise site — the id the user
        # pasted, the space they named, the two counts and the collision sample are all facts of
        # one request rather than properties this plane can know.
        "archiveId",
        "spaceName",
        "expected",
        "found",
        "sample",
        # SPEC-171's partial restore, filled by update-receipt from the collector's own
        # verdict — how many objects actually landed is a fact of one run, not of this plane.
        "restored",
    }
    for reason, body in messages._BODIES.items():
        for marker in re.findall(r"\{(\w+)\}", body):
            assert marker in fillable, f"{reason} names {{{marker}}}, which nothing supplies"


def test_the_trusted_context_wins_over_a_raise_sites_token():
    """The context is passed LAST so a raise site cannot misstate a cap to the user."""
    text = messages.failure_message("too_many_items", tokens={"maxItems": "999999"})

    assert "999999" not in text
    assert str(config.ARCHIVE_MAX_ITEMS) in text


def test_the_wording_is_ascii_and_carries_no_smart_quotes():
    for reason in messages._BODIES:
        text = messages.failure_message(reason)
        text.encode("ascii")
        assert "\u2018" not in text and "\u2019" not in text


#: The ONE outcome on this plane that is genuinely partial, and it is SPEC-171's asymmetry
#: rather than a slipped standard. Every other code here refuses whole because it CAN: the
#: archive's commit gate means nothing was deleted, and a refused restore has written nothing.
#: A partial RESTORE cannot be made whole in either direction — the user's space already holds
#: some of their own data, and deleting it to make the operation atomic would destroy the very
#: thing the restore was for — so its body has to say so.
_DELIBERATELY_PARTIAL = {"restore_incomplete"}


def test_no_body_promises_a_partial_outcome_except_the_one_that_is():
    """Every refusal on this plane but one is a WHOLE-request refusal, which is what makes
    "nothing was archived" and "nothing was changed in your space" true in almost every sentence
    this table can produce. A body implying part of the request went through would be wrong for
    every code outside the exemption.

    The exemption is a SET rather than a skipped assertion so that a second body drifting into
    partial wording has to be argued for here, beside the reasoning, rather than merely passing.
    """
    for reason, body in messages._BODIES.items():
        if reason in _DELIBERATELY_PARTIAL:
            continue
        assert "some of" not in body.lower(), reason
        assert "were restored" not in body.lower(), reason


def test_the_partial_restore_body_says_all_three_things_it_has_to():
    """SPEC-171 FR-004 AC3, and the third is the one an author would leave out. A user reading
    "the restore did not finish" will request it again; the destination guard will then refuse
    against the files that DID land, and without the last sentence that refusal reads like a new
    bug on top of the old one.
    """
    text = messages.failure_message(
        "restore_incomplete", tokens={"restored": "40", "total": "100"}, mode="restore"
    )

    assert "40 of 100" in text, "the count of what came back"
    assert "archive is still intact" in text and "same id" in text, "the archive is still there"
    assert "already there" in text and "request the restore again" in text, "what to do next"


# ── SPEC-172: the three outcomes a failure table cannot carry ────────────────


def test_the_success_bodies_are_not_in_the_failure_table():
    """They are composed, not registered. A success rendered through the resolver would come out
    as "Couldn't archive that: archived 12 files", and the resolver's codes double as
    ``TerminalError``'s raise-time validation set — so a success reason there would also make
    ``raise TerminalError("archived")`` a legal statement."""
    for name in ("archived", "restored", "restore_started"):
        assert name not in messages._BODIES


def test_the_archived_message_carries_the_id_the_restore_needs():
    """The archived objects are in a bucket the browser cannot reach, so this id is the user's
    only route back to them — and the receipt that repeats it lives inside the folder it names."""
    text = messages.archived_message("3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93", 12, 1536)

    assert "3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93" in text
    assert "12 files" in text and "1.5 KB" in text
    assert "removed from your space" in text


def test_the_size_renders_through_the_receipts_own_formatter():
    """One archive must not read as 3072.0 GB in its notification and 3.0 TB in its receipt —
    the shared TB ceiling, SPEC-155 FR-007."""
    from arcommon import receipt

    size = 3 * 1024**4
    assert receipt.human_bytes(size) in messages.archived_message("id", 1, size)


def test_the_started_message_says_the_duration_and_that_more_is_coming():
    """The only START notification in the app. Without the duration it reads as a completion that
    has not shown up yet, which is exactly the confusion three billed hours of silence creates."""
    text = messages.restore_started_message(12)

    assert "several hours" in text
    assert "another notification" in text
    assert "Nothing has changed" in text


def test_the_restored_message_only_claims_the_sweep_when_it_HAPPENED():
    """SPEC-171 made a failed vault sweep a FLAG on a successful run, not a failure of it — and
    `DeleteArchived`'s Catch reaches the same success terminal through `CleanupIncomplete`. Said
    unconditionally, "the archive has been cleaned up" turns that flag into a positive claim about
    the one route where it is false, and nothing else a user can see carries it."""
    swept = messages.restored_message(3, 10)
    kept = messages.restored_message(3, 10, archive_swept=False)

    assert "cleaned up" in swept
    assert "cleaned up" not in kept
    # What IS true on both routes is said on both routes.
    assert "Restored 3 files" in kept and "back where they came from" in kept


def test_the_unswept_wording_does_not_ask_the_user_to_do_anything():
    """There is nothing for them to do: the residue is billed at the 90-day minimum and swept by
    the bucket's own expiry rule. An "please contact an administrator" here would manufacture a
    support ticket out of a run that worked."""
    kept = messages.restored_message(3, 10, archive_swept=False)

    assert "administrator" not in kept
    assert "try again" not in kept


def test_every_outcome_message_stays_ascii():
    """The same rule the failure bodies follow: these are read in an inbox and, for the receipt's
    sake, in whatever the user opens a text file with."""
    for text in (
        messages.archived_message("id", 2, 10),
        messages.restore_started_message(2),
        messages.restored_message(2, 10),
        messages.restored_message(2, 10, archive_swept=False),
    ):
        assert text.isascii(), text


def test_one_object_reads_as_one_file_in_all_three():
    """A count phrase that says "1 files" is the sort of thing a user quotes back at you."""
    for text in (
        messages.archived_message("id", 1, 10),
        messages.restore_started_message(1),
        messages.restored_message(1, 10),
    ):
        assert "1 file " in text or "1 file(" in text, text
        assert "1 files" not in text, text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
