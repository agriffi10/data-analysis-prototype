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
    "overlapping_items",
    "too_many_objects",
    "selection_too_large_to_expand",
    "object_too_large",
    "source_missing",
    "source_empty",
    "destination_occupied",
    "plan_unreadable",
    "plan_superseded",
    "request_id_reused",
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


def test_every_outcome_this_plane_can_produce_is_in_the_closed_set():
    """Every verb that produces outcomes has to produce wordable ones, or the record arrives at the
    notifier as silence.

    The ratchet moved 7 -> 13 when the transfer, the deletion and the terminals arrived. It is
    RAISED deliberately, with each new member's wording decided in the same change — never
    loosened to let one through.
    """
    for member in (
        outcomes.NOOP,
        outcomes.PROTECTED,
        outcomes.REFUSED,
        outcomes.CLEARED,
        outcomes.CONFLICT,
        outcomes.SOURCE_MISSING,
        outcomes.SOURCE_EMPTY,
        outcomes.MOVED,
        outcomes.COPIED,
        outcomes.DELETED,
        outcomes.COPY_FAILED,
        outcomes.DUPLICATE,
        outcomes.DELETE_FAILED,
    ):
        assert member in outcomes.MEMBERS

    assert len(outcomes.MEMBERS) == 13, "an outcome was added without deciding how it is worded"


def test_a_gate_verdict_is_never_also_a_terminal():
    """``cleared`` means "may proceed". An item still wearing it when the machine finishes is
    indistinguishable from "moved successfully" to the producer that words the notification, so the
    two sets are disjoint by construction rather than by care."""
    assert not (outcomes.GATE_VERDICTS & outcomes.TERMINALS)
    assert outcomes.GATE_VERDICTS | outcomes.TERMINALS == outcomes.MEMBERS
    assert outcomes.CLEARED in outcomes.GATE_VERDICTS


def test_every_operation_has_a_terminal_success():
    """A ``cleared`` item that committed has to become something, and a missing row would leave it
    ``cleared`` at a terminal — the defect the disjointness above exists to make visible."""
    from focommon import config

    assert set(outcomes.TERMINAL_SUCCESS) == set(config.OPERATIONS)
    assert set(outcomes.TERMINAL_SUCCESS.values()) <= outcomes.TERMINALS


def test_the_new_reason_codes_each_resolve_to_a_SENTENCE_rather_than_the_fallback():
    """A reason code with no body resolves to the fallback, which tells the user nothing. These six
    arrive with the transfer and the deletion, and two of them (``copy_failed``,
    ``transfer_results_unreadable``) are the ones a plane most easily forgets — they are produced
    by the engine and the collector rather than by a refusal someone was already wording."""
    fallback = messages.copy_resolver.message("a_code_that_does_not_exist")
    for reason in (
        "destination_occupied_late",
        "copy_failed",
        "transfer_results_unreadable",
        "source_changed",
        "source_delete_failed",
        "delete_refused",
    ):
        for operation in ("copy", "move", "delete"):
            sentence = messages.failure_message(operation, reason)
            assert sentence != fallback, f"{reason} resolves to the fallback under {operation}"
            assert sentence.endswith((".", "!")), reason


def test_a_conflicts_extra_fields_come_out_of_the_ONE_record_builder():
    """The sample and its "there may be more" flag ride to the notification like everything else, so
    they are built where the shape is assertable rather than merged in by a caller."""
    record = outcomes.outcome(
        "alice/a/", "a", outcomes.CONFLICT, "destination_occupied", sample=["out/a/x"], more=True
    )

    assert record == {
        "itemKey": "alice/a/",
        "label": "a",
        "outcome": "conflict",
        "reason": "destination_occupied",
        "sample": ["out/a/x"],
        "more": True,
    }


def test_an_absent_extra_is_left_off_rather_than_carried_as_null():
    """A null on the state is a field a later reader has to test for, and one every item pays for in
    bytes against a 256 KB limit."""
    assert "sample" not in outcomes.outcome("alice/a/", "a", outcomes.CLEARED, sample=None)


# ── Carrying the list forward ────────────────────────────────────────────────


def test_the_list_is_carried_forward_COMPLETE_by_each_verb():
    """The test the rule exists for: one refusal, one empty item and one conflict, produced by three
    different verbs, all present at the end. A verb returning only its own records would drop the
    two before it — and those are exactly the per-item outcomes the model exists to carry."""
    from_validate = [
        outcomes.outcome("alice/athenaresults/", "athenaresults", outcomes.PROTECTED, "results_folder_not_deletable")
    ]
    from_expansion = outcomes.carry_forward(
        from_validate,
        [
            outcomes.outcome("alice/empty/", "empty", outcomes.SOURCE_EMPTY, "source_empty"),
            outcomes.outcome("alice/logs/", "logs", outcomes.CLEARED),
        ],
    )

    final = outcomes.carry_forward(
        from_expansion,
        [outcomes.outcome("alice/logs/", "logs", outcomes.CONFLICT, "destination_occupied")],
    )

    assert [(record["itemKey"], record["outcome"]) for record in final] == [
        ("alice/athenaresults/", "protected"),
        ("alice/empty/", "source_empty"),
        ("alice/logs/", "conflict"),
    ]


def test_a_revised_verdict_keeps_the_items_PLACE_in_the_list():
    """A person reads this list. A guard revising a provisional verdict must not reorder it."""
    existing = [
        outcomes.outcome("alice/a/", "a", outcomes.CLEARED),
        outcomes.outcome("alice/b/", "b", outcomes.CLEARED),
    ]

    merged = outcomes.carry_forward(
        existing, [outcomes.outcome("alice/a/", "a", outcomes.CONFLICT, "destination_occupied")]
    )

    assert [record["itemKey"] for record in merged] == ["alice/a/", "alice/b/"]
    assert merged[0]["outcome"] == "conflict"


def test_the_decided_keys_are_what_the_expansion_must_never_see():
    """A same-key no-op's destination subtree IS its source subtree, so expanding it would have the
    guard report every one of its own objects as a collision."""
    existing = [
        outcomes.outcome("alice/old/", "old", outcomes.NOOP),
        {"label": "malformed"},
    ]

    assert outcomes.decided_keys(existing) == {"alice/old/"}
    assert outcomes.decided_keys(None) == set()


def test_no_body_ASSERTS_A_COPY_HAPPENED_under_the_delete_prefix():
    """The check the "not the fallback, ends with a period" test above structurally cannot make.

    ``source_changed`` and ``source_delete_failed`` arise on a ``move``, where the data now exists
    twice, AND on a ``delete``, where nothing was copied at all. Both once read "You now have it in
    both places" — a FALSE SENTENCE under the delete prefix, and one that reinstates exactly the
    confusion the separate ``delete_failed`` outcome was added to prevent.

    So this asserts the property rather than the wording: no sentence a delete can produce may claim
    a copy exists. Swept over the WHOLE table, not the two reasons that were wrong, because the next
    body someone adds is the one this is for.
    """
    # Phrases that assert a copy EXISTS, not ones that merely name copying as an operation:
    # "it cannot be copied, moved or deleted" is a correct sentence under all three prefixes.
    claims_a_copy = ("both places", "the copy worked", "was copied")
    for reason in messages._BODIES:
        sentence = messages.failure_message("delete", reason).lower()
        for claim in claims_a_copy:
            assert claim not in sentence, (
                f"the delete wording for {reason!r} claims a copy exists: {sentence!r}"
            )


def test_the_two_source_survived_reasons_read_correctly_under_ALL_THREE_prefixes():
    """The pair that has to work everywhere: they say only that the original is still there, which is
    true whether or not anything was copied. The "in both places" clause belongs to the ``duplicate``
    OUTCOME, which is per-item wording the notification spec owns."""
    for reason in ("source_changed", "source_delete_failed"):
        for operation in ("copy", "move", "delete"):
            sentence = messages.failure_message(operation, reason)
            assert "still" in sentence or "left where it is" in sentence, (
                f"{reason} under {operation} no longer says the original survived: {sentence!r}"
            )


# ── The per-item wording, and the ONE sentence a run produces ─────────────────────────────


def _record(outcome, reason=None, label="q1.csv"):
    return messages.outcomes.outcome("alice/" + label, label, outcome, reason)


@pytest.mark.parametrize("outcome", sorted(messages.outcomes.TERMINALS))
@pytest.mark.parametrize("operation", ["copy", "move", "delete"])
def test_every_terminal_outcome_has_wording_under_every_operation(outcome, operation):
    """An outcome nothing can word is a notification the user never understands. The vocabulary is
    closed and asserted elsewhere; this walks it rather than listing it, so the member added next
    fails here instead of resolving to a generic clause in production."""
    clause = messages.item_clause(operation, _record(outcome, _REASONS.get(outcome)))

    assert clause and clause[-1] == "."
    assert clause != messages.copy_resolver.body("no_such_reason"), (
        f"{outcome!r} under {operation!r} falls back to the generic clause and says nothing"
    )


#: The reason each outcome that carries one actually arrives with, taken from the verbs that
#: produce them. Written here rather than invented, because a clause is only reachable through the
#: pair.
_REASONS = {
    "protected": "archive_read_only",
    "refused": "destination_inside_source",
    "conflict": "destination_occupied",
    "duplicate": "source_changed",
    "delete_failed": "source_delete_failed",
}


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("source_missing", None),
        ("source_empty", None),
        ("copy_failed", None),
        ("conflict", "destination_occupied"),
        ("conflict", "destination_occupied_late"),
        ("duplicate", "source_changed"),
        ("duplicate", "source_delete_failed"),
        ("duplicate", "delete_refused"),
        ("delete_failed", "source_delete_failed"),
        ("delete_failed", "delete_refused"),
        ("protected", "marker_not_deletable"),
    ],
)
def test_a_reason_that_already_has_a_BODY_is_worded_from_that_body_and_not_a_second_table(
    outcome, reason
):
    """The twin this module refuses to grow. Six of these codes are already worded for the failure
    sentence, and a second table for the item form would be one code with two sentences — which is
    exactly the drift the one-table rule above exists to stop, arriving inside one module."""
    clause = messages.item_clause("move", _record(outcome, reason))
    body = messages.move_resolver.body(reason or outcome)

    assert clause.startswith(body), f"{outcome}/{reason} is worded twice"


def test_a_DUPLICATE_says_the_data_is_now_in_two_places():
    """The one outcome a user cannot infer and must act on — and the sentence the shared bodies are
    deliberately forbidden from carrying, because the same reasons arise on a delete where nothing
    was copied at all."""
    clause = messages.item_clause("move", _record("duplicate", "source_changed"))

    assert "in both places" in clause
    assert "both places" not in messages.move_resolver.body("source_changed")
    assert "both places" not in messages.item_clause("delete", _record("delete_failed", "source_changed"))


def test_a_NOOP_says_plainly_that_nothing_changed():
    """A rename to the same name is the ordinary way to reach it, and it reads as a failure
    otherwise."""
    clause = messages.item_clause("move", _record("noop"))

    assert "nothing changed" in clause


def test_a_CONFLICT_carries_the_statement_that_overwriting_cannot_be_undone():
    """These buckets have versioning off and no trash. The re-submit the refusal invites is the one
    gesture on this plane that destroys data, so the message that invites it says so."""
    clause = messages.item_clause("copy", _record("conflict", "destination_occupied"))

    assert "cannot be undone" in clause


def test_a_wholly_successful_run_names_the_operation_and_the_count():
    records = [_record("moved", label=f"f{i}.csv") for i in range(3)]

    assert messages.outcome_summary("move", records, "reports") == 'Moved 3 items to "reports".'
    assert messages.outcome_summary("delete", [_record("deleted")]) == "Deleted 1 item."


def test_a_MIXED_run_names_what_SUCCEEDED_as_well_as_what_did_not():
    """A message listing only refusals reads as though nothing worked, which is the question the
    user actually has."""
    records = [
        _record("moved", label="a.csv"),
        _record("moved", label="b.csv"),
        _record("conflict", "destination_occupied", label="c.csv"),
    ]
    sentence = messages.outcome_summary("move", records, "reports")

    assert sentence.startswith('Moved 2 of 3 items to "reports". 1 needs your attention:')
    assert '"c.csv"' in sentence


def test_the_sample_is_BOUNDED_and_says_how_many_it_did_not_name():
    """A sample a reader could mistake for the whole list is worse than a count alone."""
    records = [_record("conflict", "destination_occupied", label=f"f{i}.csv") for i in range(9)]
    sentence = messages.outcome_summary("delete", records, named=3)

    assert sentence.count(" - ") == 3
    assert "And 6 others not listed here." in sentence


def test_a_run_where_nothing_could_be_done_is_a_RESULT_rather_than_a_broken_sentence():
    sentence = messages.outcome_summary("delete", [_record("protected", "archive_read_only")])

    assert sentence.startswith("1 item needs your attention:")


def test_a_label_no_message_could_render_whole_is_shortened_rather_than_dropped():
    """The caps admit names of 255 characters. The basename is the half that identifies an item, so
    the middle goes — the same rule the destination guard's sample uses, from the same function."""
    long_label = "x" * 400
    sentence = messages.outcome_summary("delete", [_record("protected", "archive_read_only", long_label)])

    assert "..." in sentence
    assert long_label not in sentence


def test_no_outcome_clause_carries_a_smart_quote_or_non_ascii():
    """The inbox renders plain text, and a smart quote arrives as mojibake."""
    for clause in [*messages._OUTCOME_CLAUSES.values(), *messages._OUTCOME_ADDITIONS.values()]:
        assert clause.isascii(), f"{clause!r} is not ASCII"


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [("duplicate", "source_changed"), ("noop", None)],
)
def test_the_opening_never_DENIES_something_the_rest_of_the_sentence_asserts(outcome, reason):
    """The two outcomes the obvious success/failure split words FALSELY.

    A ``duplicate`` reached the destination — the notification's own link points there — so an
    opening of "Nothing was moved" is untrue and is contradicted two clauses later by "this data is
    now in both places". A ``noop`` is a success that did nothing, and this plane's vocabulary says
    so; reported as a denial it reads as the failure the wording rules exist to prevent.
    """
    sentence = messages.outcome_summary("move", [_record(outcome, reason)], "reports")

    assert "Nothing was" not in sentence
    assert sentence.startswith("1 item needs your attention:")


def test_the_residue_agrees_with_itself_in_NUMBER():
    """"1 item need your attention" is the shape a hardcoded verb produces beside a pluralising
    count, and it is the kind of thing only a reader notices."""
    one = messages.outcome_summary("delete", [_record("protected", "archive_read_only")])
    two = messages.outcome_summary("delete", [_record("protected", "archive_read_only")] * 2)

    assert one.startswith("1 item needs")
    assert two.startswith("2 items need ")
