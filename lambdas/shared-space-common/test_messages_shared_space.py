"""The failure wording tables, held against the vocabulary they are supposed to cover."""

import auth
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


def test_every_registered_refusal_key_has_a_sentence_and_every_sentence_has_a_key():
    """Enumerated from the constant rather than swept from call sites, so the guard needs no
    positive control — an empty sweep and a complete one look identical, a set equality does not.

    Key equality alone is not enough, which is why the test below it exists: `refusal_message`
    consults ONE table and degrades an unregistered code to a sentence about a TRANSFER, so a
    second table would satisfy this assertion while every member refusal told the user their
    workspace could not be transferred.
    """
    assert set(messages._REFUSALS) == auth.REFUSAL_MESSAGE_KEYS
    assert auth.MEMBER_REFUSAL_CODES <= auth.REFUSAL_MESSAGE_KEYS


def test_every_member_refusal_renders_its_OWN_sentence_and_not_the_transfer_fallback():
    fallback = messages.refusal_message("NotARegisteredCode", "sales", "bob")
    for code in sorted(auth.MEMBER_REFUSAL_CODES | {"MemberRequestRefused"}):
        rendered = messages.refusal_message(code, "sales", "bob")
        assert rendered != fallback, f"{code} renders the generic transfer sentence"
        assert "transfer" not in rendered.lower() or code == "MemberRemoveOwner", (
            f"{code} tells the user about a transfer they did not ask for: {rendered}"
        )
        assert "sales" in rendered, f"{code} names no space: {rendered}"


def test_an_unregistered_key_is_refused_at_composition_rather_than_rendered_generically():
    """`_refusal` is the only composer, so this is where a code with no sentence has to stop.
    Left to the resolver it would render the transfer fallback — silently, and to a user who
    asked about something else entirely."""
    try:
        auth._refusal("NotARegisteredCode", "sales")
    except ValueError as exc:
        assert "NotARegisteredCode" in str(exc)
    else:
        raise AssertionError("an unregistered code composed a sentence")

    try:
        auth._refusal("MemberNotOwner", "sales", wording="AlsoNotRegistered")
    except ValueError as exc:
        assert "AlsoNotRegistered" in str(exc)
    else:
        raise AssertionError("an unregistered WORDING key composed a sentence")

    # The third case is the one the pair exists for, and the two above do not cover it: both are
    # satisfied by checking `wording or code` alone, so the CODE arm can be deleted with the suite
    # green. An unregistered code carried under a REGISTERED wording is what distinguishes them —
    # it is the shape that would return a code nothing can render while reading as fine.
    try:
        auth._refusal("NotARegisteredCode", "sales", wording="MemberRequestRefused")
    except ValueError as exc:
        assert "NotARegisteredCode" in str(exc)
    else:
        raise AssertionError("an unregistered CODE composed a sentence under a registered wording")


def test_every_membership_refusal_class_has_a_sentence_a_user_can_read():
    # The refusal table has a key-parity gate; this one did not, and the keys here are class
    # names the engine reports verbatim. A rename degrades the message to the generic clause
    # silently, which is the failure this file's own docstring says registering them prevents.
    import registry as reg

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    named = {cls.__name__ for cls in subclasses(reg.MembershipRefused)}
    assert named, "no MembershipRefused subclasses found — the walk is looking in the wrong place"
    missing = sorted(name for name in named if name not in messages._DOMAIN_REASONS)
    assert missing == [], f"no sentence registered for {missing}"
    for name in named:
        rendered = messages.failure_message("transfer_ownership", "sales", name)
        assert messages._DOMAIN_REASONS[name] in rendered
