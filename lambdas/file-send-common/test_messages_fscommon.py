"""The wording every file-send failure reaches the user through.

Two things are being pinned. **Every reason this plane can raise must be registered**, because
``TerminalError`` validates its reason at the raise site — an unregistered code turns a
friendly failure into a ``ValueError`` inside the verb, which is a different and worse
failure. And **no raw AWS text, and no key the sender supplied, may reach the sentence**
(SPEC-106): the detail on the exception is for the logs and the Step Functions record.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon import messages as cpmessages
from cpcommon.errors import TerminalError
from fscommon import config, messages, paths

#: Every reason code the layer or a verb raises today. Listed rather than derived from the
#: table, because the point is to catch a raise site whose code was never added TO the table.
_RAISED_BY_THE_PLANE = (
    "forbidden",
    "malformed_event",
    "unauthorized",
    "no_items",
    "invalid_items",
    "too_many_items",
    "no_recipients",
    "invalid_recipients",
    "too_many_recipients",
    "results_not_sendable",
    # SPEC-166. The transfer's own vocabulary: two per-recipient outcomes and one
    # whole-request one.
    "conflict",
    "copy_failed",
    "transfer_results_unreadable",
    "send_timed_out",
    "object_too_large",
    "too_many_transfer_items",
    "transfer_too_large",
)


@pytest.mark.parametrize("reason", _RAISED_BY_THE_PLANE)
def test_every_reason_the_plane_raises_is_registered(reason):
    assert cpmessages.is_known_reason(reason), (
        f"{reason!r} is raised somewhere on this plane but is not registered — TerminalError "
        f"validates at the raise site, so raising it would throw ValueError instead"
    )


@pytest.mark.parametrize("reason", _RAISED_BY_THE_PLANE)
def test_a_registered_reason_can_actually_be_raised(reason):
    """The guard the one above cannot give: registration is what makes the raise legal, so
    this exercises the real constructor rather than the predicate behind it."""
    assert TerminalError(reason, "detail").reason == reason


def test_the_caps_are_filled_from_config_and_not_written_into_the_sentence():
    """A cap named in prose drifts from the constant that enforces it. The marker means the
    sentence cannot say a number the code does not use."""
    assert str(config.SEND_MAX_ITEMS) in messages.failure_message("too_many_items")
    assert str(config.SEND_MAX_RECIPIENTS) in messages.failure_message("too_many_recipients")
    assert "{" not in messages.failure_message("too_many_items")


def test_a_whole_request_failure_names_no_recipient():
    text = messages.failure_message("no_items")

    assert text.startswith("Couldn't send: ")


def test_a_per_recipient_failure_names_the_recipient():
    text = messages.failure_message("unknown_user", kind="user", name="ghost")

    assert 'user "ghost"' in text


def test_a_space_recipient_reads_as_a_space():
    text = messages.failure_message("unknown_space", kind="space", name="finance")

    assert 'space "finance"' in text


def test_an_access_denial_names_no_resource():
    """It must not confirm what exists. `forbidden` resolves through the access-denied clause,
    which names nothing at all."""
    text = messages.failure_message("forbidden")

    assert text == "You don't have access to send those files."


def test_an_unknown_reason_falls_back_rather_than_leaking_the_code():
    text = messages.failure_message("some_internal_thing")

    assert "some_internal_thing" not in text


def test_a_raise_site_token_cannot_shadow_the_trusted_context():
    """The trusted context is applied last, so a payload token cannot rewrite the cap or the
    recipient clause into something the code does not enforce."""
    text = messages.failure_message(
        "too_many_items", tokens={"maxItems": "9999", "toRecipient": " to user \"admin\""}
    )

    assert "9999" not in text
    assert "admin" not in text


def test_a_conflict_names_the_recipient_and_the_item_that_was_already_there():
    """SPEC-166 FR-001 AC5, from the wording end. "Couldn't send" alone would leave the sender
    guessing which of the things they selected was the problem — and the item name is the one
    piece of context they can act on, by renaming it or asking the recipient to move theirs."""
    text = messages.failure_message("conflict", kind="user", name="bob", tokens={"itemName": "notes.txt"})

    assert 'user "bob"' in text
    assert '"notes.txt"' in text
    assert "{" not in text


def test_a_conflict_says_nothing_was_overwritten():
    """The reassurance is the point of the sentence as much as the refusal is: a send that
    stops has done nothing, and a sender who cannot tell the difference will go looking."""
    text = messages.failure_message("conflict", kind="user", name="bob", tokens={"itemName": "notes.txt"})

    assert "nothing was overwritten" in text


def test_a_success_names_the_recipient_the_items_and_the_count():
    """SPEC-167 FR-004. Both numbers, because either alone misleads: "1 thing" for a 3,000-file
    folder, or "3,000 files" for something the recipient will find under one name."""
    text = messages.success_message("user", "bob", ["reports", "notes.txt"], 301)

    assert 'user "bob"' in text
    assert '"reports"' in text and '"notes.txt"' in text
    assert "301 files" in text


def test_a_long_selection_is_summarised_rather_than_listed():
    """A notification is a sentence, not a manifest — and the item cap is 200."""
    text = messages.success_message("user", "bob", [f"item{n}" for n in range(20)], 20)

    assert "and 18 more" in text
    assert "item19" not in text


def test_one_file_reads_as_one_file():
    assert "(1 file)" in messages.success_message("user", "bob", ["notes.txt"], 1)


def test_the_recipient_is_told_where_to_look():
    """The destination is the one thing they cannot guess, and it comes from the layout module
    rather than from this table — a sentence that drifted from the keys would send people looking
    in the wrong place."""
    text = messages.recipient_message("alice", ["reports"], 300)

    assert text.startswith("alice sent you")
    assert paths.inbox_label("alice") in text


def test_the_space_owner_is_told_it_was_their_SPACE():
    """They did not receive it personally, and the wording must not suggest they did — they are
    hearing about it because they own the space."""
    text = messages.space_owner_message("alice", "finance", ["reports"], 300)

    assert 'your space "finance"' in text
    assert paths.inbox_label("alice") in text


def test_no_body_carries_a_raw_key_or_aws_text():
    """SPEC-106. Nothing in the table interpolates a key, a bucket or an engine message — the
    only markers are the two caps and the recipient clause."""
    for reason in messages._BODIES:
        text = messages.failure_message(reason, kind="user", name="bob")
        assert "s3://" not in text
        assert "arn:aws" not in text
