"""The failure wording tables, held against the vocabulary they are supposed to cover."""

import messages

import config


def test_every_action_the_authorizer_accepts_has_a_phrase():
    """The module's own docstring claims an action added without a phrase here is "visibly missing
    rather than silently mistranslated", and until this test nothing enforced it.

    Nothing does go wrong loudly: the fallback renders, so every fault-path notification for the
    new action reads "We couldn't complete that shared workspace request" instead of naming what
    the user was trying to do. It is a finding that is an instance of a RULE, so the fix is the
    enumeration rather than the one line — the next verb added to this plane arrives here without
    anyone remembering to.
    """
    missing = config.VALID_ACTIONS - set(messages._ACTION_PHRASES)
    assert not missing, f"these actions have no phrase and would render the generic clause: {sorted(missing)}"

    stray = set(messages._ACTION_PHRASES) - config.VALID_ACTIONS
    assert not stray, f"these phrases name actions the authorizer does not recognise: {sorted(stray)}"


def test_a_refusal_that_has_a_target_names_it():
    """FR-002: "that person is not a member" is useless without saying which person, and the
    failure notifier cannot supply one — its input carries an action and a space and nothing else.
    """
    named = messages.refusal_message("TransferTargetNotMember", "finance", "bcarter")
    assert "bcarter" in named and "finance" in named


def test_an_unregistered_code_degrades_to_a_sentence_rather_than_rendering_the_code():
    """A reason code is operator text. The deploy-skew case is a real one — a producer newer than
    this layer can carry a code it has never heard of — and it must not surface as jargon."""
    rendered = messages.refusal_message("SomethingNobodyRegistered", "finance", "bcarter")
    assert "SomethingNobodyRegistered" not in rendered
    assert "finance" in rendered


def test_the_two_transfer_notifications_each_name_the_other_party():
    """FR-005: one producer says the outcome, and neither half is readable without the other name."""
    to_outgoing, to_incoming = messages.transfer_notifications("finance", "alice", "bcarter")
    assert "bcarter" in to_outgoing and "finance" in to_outgoing
    assert "alice" in to_incoming and "finance" in to_incoming
    assert "still a member" in to_outgoing, "the outgoing owner's chief question is what they keep"


def test_a_missing_space_or_target_renders_blank_rather_than_the_word_None():
    """This plane now takes messages from a producer outside the API's contract, so a field the
    contract would have refused can be absent. A Python ``None`` interpolated into a sentence a
    user reads is a worse outcome than an empty pair of quotes."""
    for rendered in (
        messages.refusal_message("TransferSpaceUnknown", None, None),
        messages.refusal_message("TransferTargetNotMember", None, None),
        messages.refusal_message("SomethingUnregistered", None, None),
    ):
        assert "None" not in rendered, rendered
