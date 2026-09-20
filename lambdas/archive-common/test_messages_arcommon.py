"""The archive plane's user-facing wording.

SPEC-106: raw AWS text is never shown. The detail on a terminal error is for the logs and the
Step Functions record; the sentence a user reads is composed here.
"""

import ast
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import pytest
from arcommon import messages, receipt


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
        # How many items the copy-back declined to overwrite. Filled by update-receipt from the
        # collector's `transferOutcome.occupied`, which counts the failures carrying the
        # per-item occupied reason — a fact of one run, like the two counts beside it.
        "occupied",
    }
    for reason, body in messages._BODIES.items():
        for marker in re.findall(r"\{(\w+)\}", body):
            assert marker in fillable, f"{reason} names {{{marker}}}, which nothing supplies"


#: The outcomes on this plane that are genuinely partial. Every other code here refuses whole
#: because it CAN: the archive's commit gate means nothing was deleted, and a refused restore has
#: written nothing. A partial RESTORE cannot be made whole in either direction — the user's space
#: already holds some of their own data, and removing it to make the operation atomic would
#: destroy the very thing the restore was for — so its body has to say so.
#:
#: All four members are the SAME asymmetry reached by four different causes, and each is argued
#: here rather than merely listed, because a set is where a slipped standard hides:
#:   restore_incomplete           the copy-back stopped short.
#:   restore_incomplete_occupied  it stopped short because files had appeared in the way. Same
#:                                asymmetry, different cause — and the count it adds is exactly
#:                                what distinguishes the two for the user.
#:   restore_archive_cleared      it stopped short AND the vault count could not confirm the
#:                                archive, so the body says what came back and claims nothing
#:                                about the rest.
#:   restore_timed_out            the wait loop hit its ceiling. Files may already be back, which
#:                                is why its body no longer says nothing was changed.
_DELIBERATELY_PARTIAL = {
    "restore_incomplete",
    "restore_incomplete_occupied",
    "restore_archive_cleared",
    "restore_timed_out",
}


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



# ── FR-007: every restore message is safe to follow while a sibling restore runs ────────────
#
# Two restores of one archive can run at once, and the one that finishes first sweeps the vault.
# So a sentence that is merely misleading on one run can cost the only copy on two — and the
# failure this file exists to prevent is not a typo, it is a user following an instruction.
#
# THESE ARE RULES OVER A POPULATION, NOT A LIST OF SENTENCES, and that is the lesson rather than
# a style choice: per-sentence fixes were tried first and every review round found another one.
# A verb list with a looser negation rule — exempt any sentence containing a "not" — let eleven
# of seventeen destructive sentences through when it was measured, which is why the negations
# below are an explicit CLOSED allowlist and a negation nobody has added here fails the test.
# Failing on an unlisted negation is the safe way to be wrong.

_DESTRUCTIVE_VERBS = ("delete", "remove", "discard", "overwrite", "erase", "wipe", "purge")

#: "Clear ... out" is the one destructive instruction that is not a single word, and it is
#: matched across intervening words within a sentence ("clear them out", "clear the old ones
#: out") rather than as a fixed phrase.
_CLEAR_OUT = re.compile(r"clear\b[^.]*\bout\b")

#: The negated phrases this table is allowed to use. CLOSED: a body that needs a new one has to
#: add it here, beside the reasoning, rather than passing because the rule was loose.
_ALLOWED_NEGATIONS = (
    "don't delete or overwrite",
    "nothing was deleted",
    "nothing was overwritten",
    "can't be removed",
)

#: Sentences that state the archive's condition as a fact about NOW. Every one of them is false
#: the moment a sibling restore sweeps the vault, which it does as soon as it finishes.
_PRESENT_STATE_CLAIMS = (
    "is intact",
    "still intact",
    "remains intact",
    "is untouched",
    "can still be restored",
    "can be restored again",
    "still available",
)

#: The one permitted way to say anything about the archive: scoped to a moment that has passed,
#: so it stays true after a sweep. It has to be EARNED by counting the vault, so only the bodies
#: the count selects may carry it.
_TIME_SCOPED = "was still complete when this restore stopped"


def _destructive(text: str) -> list[str]:
    """Every destructive instruction in a sentence, after the allowed negations are stripped."""
    stripped = text.lower()
    for negation in _ALLOWED_NEGATIONS:
        stripped = stripped.replace(negation, " ")
    found = [verb for verb in _DESTRUCTIVE_VERBS if verb in stripped]
    if _CLEAR_OUT.search(stripped):
        found.append("clear ... out")
    return found


def _present_state(text: str) -> list[str]:
    """Every claim about the archive's condition right now."""
    lowered = text.lower()
    return [phrase for phrase in _PRESENT_STATE_CLAIMS if phrase in lowered]


def _restore_reachable() -> dict:
    """Every body the restore resolver can render: the whole table, less the archive-only set."""
    return {
        reason: body
        for reason, body in messages._BODIES.items()
        if reason not in messages.ARCHIVE_ONLY
    }


def _receipt_lines() -> dict:
    """Every line ``arcommon.receipt`` can write on a restore, labelled by where it comes from.

    Both values of ``archiveIntact`` and every status, because the incomplete branch is the one
    that says something about the archive and the flag is what decides which sentence. The
    fallback record is included because a restore that finds no receipt composes one.
    """
    lines = {}
    for status in ("requested", "restored", "incomplete", None):
        for intact in (True, False):
            state = {
                "status": status,
                "requestedAt": "2026-09-12T09:30:00.000Z",
                "destination": "s3://user-bkt/alice/",
                "restored": 3,
                "expected": 5,
                "archiveIntact": intact,
            }
            for label, value in receipt.restore_lines(state).items():
                lines[f"restore_lines[{status},{intact}] {label}"] = value
    lines["render(fallback record)"] = receipt.render(
        {
            "requestId": "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c",
            "startedAt": None,
            "source": {"bucket": "user-bkt", "root": "alice/"},
            "archive": {"bucket": "archive-bkt", "root": "personal/alice/archive/x/"},
            "objectCount": 5,
            "totalBytes": 1024,
        }
    )
    return lines


def _everything_a_restore_can_show() -> dict:
    """The full population both rules run over: the bodies, the suffix, and the receipt."""
    return {
        **_restore_reachable(),
        "restore_resolver suffix": messages.RESTORE_SAFETY_SUFFIX,
        **_receipt_lines(),
    }


def test_no_restore_message_tells_the_user_to_destroy_anything():
    """**RULE 1.** The remediation is "move or rename": that keeps the bytes whoever they belong
    to, and a user who wants a file gone does not need this app to suggest it.

    It matters most where it is least obvious. When two restores of one archive overlap, the
    files a message names can be the OTHER run's output — and that run sweeps the vault when it
    finishes, so a user who follows "delete the ones that came back" destroys the only copy.
    """
    offenders = {
        where: found
        for where, text in _everything_a_restore_can_show().items()
        if (found := _destructive(text))
    }
    assert offenders == {}, f"destructive instructions in restore-reachable text: {offenders}"


def test_no_restore_message_states_the_archives_condition_as_a_fact():
    """**RULE 2.** A claim about the archive is only true when it is made, and a sibling can
    sweep the vault a second later. The one permitted form is time-scoped, and rule 3 below
    holds it to being earned."""
    offenders = {
        where: found
        for where, text in _everything_a_restore_can_show().items()
        if (found := _present_state(text))
    }
    assert offenders == {}, f"present-tense claims about the archive: {offenders}"


def test_the_time_scoped_claim_appears_only_where_the_vault_count_earned_it():
    """The permitted form is not a free pass: it is a claim, and it has to be paid for by
    ``restore.archive_is_intact`` counting the prefix. Only the two bodies that count selects,
    and the receipt line the same flag selects, may carry it."""
    bodies = {reason for reason, body in messages._BODIES.items() if _TIME_SCOPED in body.lower()}
    receipt_lines = {
        where for where, text in _receipt_lines().items() if _TIME_SCOPED in text.lower()
    }

    assert bodies == {"restore_incomplete", "restore_incomplete_occupied"}
    assert all("True" in where for where in receipt_lines), receipt_lines
    assert receipt_lines, "the receipt never says it — this assertion is measuring nothing"


@pytest.mark.parametrize(
    "planted",
    [
        "Please delete them.",
        "Please remove them.",
        "Discard the old copies.",
        "Overwrite them.",
        "Clear them out.",
        "move, rename or remove them",
        "Nothing was overwritten, so you can delete the older copies.",
    ],
)
def test_rule_1_flags_each_destructive_sentence_that_has_been_written_here_before(planted):
    """**THE CORPUS, and it is not optional.** Running the rule against this table proves the
    table is clean and nothing about whether the rule works — a rule that had gone quiet would
    look exactly like a healthy table.

    The last plant is the one that killed the previous design. A phrase-level rule that exempted
    any sentence containing a negation passed it: the negation is true, and the instruction after
    it still destroys the only copy. Stripping only the explicitly allowed negations is what
    catches it.
    """
    assert _destructive(planted), f"rule 1 did not flag {planted!r}"


@pytest.mark.parametrize(
    "body",
    ["restore_incomplete", "destination_occupied", "destination_occupied_after_retrieval"],
)
def test_rule_1_flags_the_three_bodies_that_used_to_say_or_delete(body):
    """The three that carried it, plus the regression the fix invites: someone restoring "or
    delete" for symmetry with a sibling sentence."""
    assert _destructive(messages._BODIES[body].replace("move or rename", "move, rename or delete"))


@pytest.mark.parametrize("phrase", _PRESENT_STATE_CLAIMS)
def test_rule_2_flags_each_present_tense_claim_about_the_archive(phrase):
    """Every phrase the rule names, planted into a body's shape. Without this the rule could
    match nothing and the table would still pass."""
    assert _present_state(f"the restore stopped and the archive {phrase} under the same id.")


def test_a_code_missing_from_ARCHIVE_ONLY_is_checked_by_default():
    """The population is stated as an EXCLUSION so that a code added to the table later is held
    to both rules without anybody remembering to add it. Asserted by planting one: an unlisted
    code carrying a destructive instruction has to be caught."""
    planted = dict(messages._BODIES)
    planted["some_future_restore_refusal"] = "please delete the files that came back."

    population = {r: b for r, b in planted.items() if r not in messages.ARCHIVE_ONLY}

    assert "some_future_restore_refusal" in population
    assert _destructive(population["some_future_restore_refusal"])


def test_ARCHIVE_ONLY_names_no_code_that_is_not_in_the_table_and_no_restore_code():
    """A stale member is a silent hole: it exempts a code from both rules while looking like
    documentation. The four codes both arms can reach are asserted absent by name, because each
    is a live path — the vault sweep goes through the same deletion guard the archive does, which
    is what puts ``protected_marker`` on a restore."""
    both_arms = {
        "plan_unreadable",
        "plan_superseded",
        "transfer_results_unreadable",
        "protected_marker",
        "copy_failed",
        "invalid_request",
    }

    assert set(messages._BODIES) >= messages.ARCHIVE_ONLY
    assert messages.ARCHIVE_ONLY & both_arms == set()
    assert not any(reason.startswith("restore_") for reason in messages.ARCHIVE_ONLY)
    assert not any(reason.startswith("destination_occupied") for reason in messages.ARCHIVE_ONLY)


def test_every_message_the_restore_resolver_renders_ends_with_the_safety_sentence():
    """A code reachable after the copy-back has begun needs no list to carry the sentence, which
    is the whole reason it belongs to the resolver. The fallback is included deliberately: it is
    what a killed verb produces, and a killed verb is exactly the run that cannot say what it
    left behind."""
    for reason in _restore_reachable():
        assert messages.restore_resolver.message(reason).endswith(messages.RESTORE_SAFETY_SUFFIX), reason

    assert messages.restore_resolver.message("forbidden").endswith(messages.RESTORE_SAFETY_SUFFIX)
    assert messages.restore_resolver.message("a_code_nobody_registered").endswith(
        messages.RESTORE_SAFETY_SUFFIX
    )


def test_the_archive_resolver_and_every_other_plane_carry_no_suffix():
    """An archive's wording is unchanged, and so is every other plane's. Asserted on the archive
    resolver directly and on the SOURCE for the rest: exactly one registration in the tree passes
    a suffix, which is the population claim a per-plane spot check could not make."""
    for reason in messages._BODIES:
        assert not messages.resolver.message(reason).endswith(messages.RESTORE_SAFETY_SUFFIX), reason
    assert not messages.resolver.message("forbidden").endswith(messages.RESTORE_SAFETY_SUFFIX)

    lambdas = pathlib.Path(__file__).resolve().parent.parent
    # cpcommon/messages.py is the MECHANISM, not a caller: its `register` forwards the keyword
    # to `Resolver`, so it names `suffix` on every call whether or not anyone passes one.
    # Exempted by full path, and `registrations` below keeps the exemption from hiding a sweep
    # that has stopped matching.
    library = lambdas / "control-plane-common" / "cpcommon" / "messages.py"
    passing = []
    registrations = 0
    for path in lambdas.rglob("*.py"):
        if "__pycache__" in str(path) or path.name.startswith("test_") or path == library:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if called not in ("register", "Resolver"):
                continue
            registrations += 1
            if any(keyword.arg == "suffix" for keyword in node.keywords):
                passing.append(str(path.relative_to(lambdas)))

    assert registrations >= 6, (
        f"only {registrations} resolver registration(s) found — the sweep has stopped matching "
        "and this assertion would hold over nothing"
    )
    assert sorted(set(passing)) == ["archive-common/arcommon/messages.py"], sorted(set(passing))
