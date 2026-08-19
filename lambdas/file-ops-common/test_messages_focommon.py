"""One body table under three prefixes, and the closed outcome set they have to word.

The risk this file exists for is not a typo. It is that a user who pressed Delete reads that a copy
failed, or that a reason code arrives at the notifier with no sentence at all.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from focommon import config, messages, outcomes, protected

_OPERATIONS = ("copy", "move", "delete")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_each_operation_gets_its_own_opening(operation):
    """One resolver would word a delete refusal as a copy failure — the wrong sentence in front of
    the right explanation."""
    rendered = messages.failure_message(operation, "source_folder_undeletable")

    assert rendered.startswith(f"Couldn't {operation} that: ")


def test_the_three_resolvers_share_ONE_body_table():
    """Three tables would let one reason drift into three sentences. Asserted by rendering the same
    reason under all three and comparing what follows the prefix."""
    bodies = {
        messages.failure_message(op, "marker_not_deletable").split(": ", 1)[1] for op in _OPERATIONS
    }

    assert len(bodies) == 1


#: Reasons this plane can produce for ANY of the three operations. Their bodies are rendered under
#: all three prefixes, so a clause naming one operation is wrong two-thirds of the time.
#:
#: The rest are NOT operation-neutral and deliberately so: ``source_folder_undeletable`` and its
#: siblings are returned only for a delete or a move — ``source_refusal`` returns None for a copy —
#: so "cannot be moved or deleted" is accurate everywhere it can actually appear.
_OPERATION_NEUTRAL = (
    "marker_not_deletable",
    "settings_folder_not_a_source",
    "lock_wait_exhausted",
    "too_many_items",
    "selection_too_large",
    "no_items",
    "invalid_items",
    "invalid_target_name",
)


@pytest.mark.parametrize("reason", _OPERATION_NEUTRAL)
def test_a_body_rendered_under_every_prefix_names_no_single_operation(reason):
    """The real constraint on writing bodies that complete three prefixes.

    A clause saying "...so nothing was copied" reads wrong under two of the three openings. A body
    may still ENUMERATE all three — the marker's does, because refusing a copy is the one place
    this plane refuses one — since that sentence is true whichever prefix precedes it. What is
    forbidden is naming one and not the others.
    """
    body = messages.failure_message("copy", reason).split(": ", 1)[1]
    named = [verb for verb in ("copied", "moved", "deleted") if verb in body]

    assert not named or len(named) == 3, (
        f"{reason!r} names {named} — it is rendered under all three prefixes, so it must name all "
        f"three or none"
    )


def test_every_protected_refusal_has_a_sentence():
    """A reason code with no body resolves to the fallback, which tells the user nothing about
    which rule fired — and this plane went to the trouble of giving each rule its own code
    precisely so the notifier would not have to guess."""
    produced = {
        protected.destination_refusal("alice/", "alice/athenaresults/", "personal").reason,
        protected.destination_refusal("sales/", "sales/deep/archive/", "shared").reason,
        protected.source_refusal("alice/", "alice/saved_queries/", "delete", "personal").reason,
        protected.source_refusal("alice/", "alice/athenaresults/r.csv", "delete", "personal").reason,
        protected.source_refusal("alice/", "alice/archive/r.json", "delete", "personal").reason,
        protected.settings_source_refusal("alice/", "alice/user_settings/x").reason,
        protected.marker_refusal(f"alice/{config.MARKER_BASENAME}").reason,
    }

    missing = produced - set(messages._BODIES)

    assert not missing, f"these refusals have no wording: {sorted(missing)}"


def test_the_give_up_refusal_has_a_sentence_under_all_three_openings():
    """The waiting design's whole promise is that a request which cannot get the lock is REFUSED
    with an explanation rather than dying at the machine's ceiling. Without a body under every
    opening that promise degrades to the generic "contact an administrator" — and only in
    production, on the rarest path."""
    for operation in _OPERATIONS:
        rendered = messages.failure_message(operation, "lock_wait_exhausted")

        assert "already working in that space" in rendered


def test_a_cap_sentence_names_the_constant_that_enforces_it():
    """The number a user reads and the number the request is refused against are the same object,
    so a raised cap cannot leave a stale figure in the message."""
    assert str(config.FILE_OPS_MAX_ITEMS) in messages.failure_message("copy", "too_many_items")


def test_an_unrecognised_operation_still_produces_a_sentence():
    """Reached only on a request malformed enough that the operation itself was refused. Raising
    while composing the sentence that reports a refusal would replace a bad message with none."""
    assert messages.failure_message(None, "invalid_operation").startswith("Couldn't ")
    assert messages.failure_message("shred", "invalid_operation").startswith("Couldn't ")


def test_no_body_carries_a_smart_quote_or_non_ascii():
    """The inbox renders plain text, and a smart quote arrives as mojibake."""
    for reason, body in messages._BODIES.items():
        assert body.isascii(), f"{reason!r} is not ASCII"


# ── The outcome vocabulary ───────────────────────────────────────────────────


def test_the_outcome_set_is_closed_and_an_unknown_one_fails_loudly():
    """A record nothing can word is a notification the user never receives, so an unknown outcome
    fails where it is built rather than arriving at the notifier as silence."""
    assert outcomes.outcome("alice/a/", "a", outcomes.NOOP) == {
        "itemKey": "alice/a/",
        "label": "a",
        "outcome": "noop",
    }

    with pytest.raises(ValueError, match="not a file-ops outcome"):
        outcomes.outcome("alice/a/", "a", "vanished")


def test_the_record_keeps_identity_and_display_APART():
    """``itemKey`` is identity and ``label`` is what a person reads. Swapping them produces a
    notification naming a key the user never typed, and a later verb matching on the wrong field."""
    record = outcomes.outcome("alice/reports/", "reports", outcomes.PROTECTED, "archive_read_only")

    assert record["itemKey"] == "alice/reports/"
    assert record["label"] == "reports"
    assert record["reason"] == "archive_read_only"


def test_an_outcome_without_a_reason_carries_no_reason_key():
    """A ``noop`` has no reason, and an empty string in its place would be a reason code the
    notifier would try to word."""
    assert "reason" not in outcomes.outcome("alice/a/", "a", outcomes.NOOP)


def test_the_three_members_this_verb_produces_are_all_in_the_closed_set():
    """The expansion spec adds four more; these three ship here because this verb produces them."""
    for member in (outcomes.NOOP, outcomes.PROTECTED, outcomes.REFUSED):
        assert member in outcomes.MEMBERS
