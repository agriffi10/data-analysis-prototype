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
    fillable = {"maxItems", "itemName"}
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


def test_no_body_promises_a_partial_outcome():
    """Every refusal on this plane is a WHOLE-request refusal, which is what makes "nothing
    was archived" true in every sentence this table can produce. A body implying some of the
    selection went through would be wrong for every code here."""
    for reason, body in messages._BODIES.items():
        assert "some of" not in body.lower(), reason


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
