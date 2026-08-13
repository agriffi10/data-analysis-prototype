"""The archive state machine's own invariants, beside the fleet-wide ones in cpcommon.

The fleet suite (``test_state_machines_cpcommon.py``) already covers this machine for the
things every plane must have: no throwing intrinsic, a NotifyFailure Task with a States.ALL
Catch, RecordFailure copying ``$.error`` whole, every transition resolving, every state
reachable, and every failure seed supplying what the terminal reads. What is here is what only
this machine can get wrong.
"""

import json
import os
import pathlib
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, os.path.join(_HERE, "..", "archive-validate-authorize"))
sys.path.insert(0, os.path.join(_HERE, "..", "archive-collect-transfer-results"))

_ASL = os.path.join(_HERE, "..", "..", "infra", "modules", "archive", "state-machine.asl.json.tftpl")


def _load():
    """The rendered machine, with Terraform's interpolations stubbed.

    Bare interpolations (a Wait's Seconds, the ceiling, the Map's batch numbers) become 0; the
    quoted ones keep their VARIABLE NAME as their value rather than a shared placeholder, which
    is what lets a test tell two states apart by the Lambda they invoke. With every ARN rendered
    to one literal, "these three states call the same function" and "these three states call
    three different functions" looked identical.
    """
    raw = pathlib.Path(_ASL).read_text()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{([^}]+)\}", r"\1", raw))


ASL = _load()
STATES = ASL["States"]


# ── The mode branch, and the trap it is guarded against ──────────────────────


def test_the_mode_branch_guards_every_comparison_with_IsPresent():
    """SPEC-143's recorded trap, and the reason this is a test rather than a comment: a Choice
    comparing a string on an ABSENT path raises States.Runtime, which is neither retriable nor
    catchable, and `Default` does NOT cover it. The execution dies outright before any state
    can record or notify — on a malformed request, which is exactly what SPEC-152 exists to
    report on.

    Asserted per choice rather than "an IsPresent appears somewhere": one guarded arm and one
    unguarded arm reads as correct and is not.
    """
    for choice in STATES["ChooseMode"]["Choices"]:
        clauses = choice.get("And") or [choice]
        guarded = {c["Variable"] for c in clauses if c.get("IsPresent") is True}
        compared = {c["Variable"] for c in clauses if "StringEquals" in c}

        assert compared and compared <= guarded, (
            f"ChooseMode compares {sorted(compared - guarded)} without an IsPresent guard on "
            "the same path — an absent path raises an uncatchable States.Runtime"
        )


def test_the_mode_branch_has_a_default_that_reaches_the_failure_terminal():
    """A Default pointed at Succeeded would turn an unrecognised mode into a silent no-op:
    the user's archive simply never happens and nothing is ever said about it."""
    seen, frontier = set(), [STATES["ChooseMode"]["Default"]]
    while frontier:
        name = frontier.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        state = STATES[name]
        frontier.append(state.get("Next"))
        frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])

    assert "NotifyFailure" in seen and "Failed" in seen


def test_the_default_arm_seeds_a_reason_code_and_never_a_verbs_error_name():
    """notify-failure treats `TerminalError` as positive evidence that a verb's decorator
    already sent a message, so a seed wearing that name would be silently suppressed and the
    user told nothing (the recorded DiffMissingSeed rule). It must be a registered reason code
    instead, or the sentence degrades to the generic fallback."""
    from arcommon.messages import _BODIES

    seeded = STATES["UnknownModeSeed"]["Parameters"]["error"]

    assert seeded["Error"] != "TerminalError"
    assert seeded["Error"] in _BODIES


def test_both_modes_have_a_target_so_the_branch_is_a_real_branch():
    targets = {
        c["And"][1]["StringEquals"]: c["Next"] for c in STATES["ChooseMode"]["Choices"]
    }

    assert set(targets) == {"archive", "restore"}
    assert targets["archive"] != targets["restore"]


# ── The ASL/verb cross-check ─────────────────────────────────────────────────


def test_the_validated_pass_names_exactly_what_the_verb_returns():
    """THE POINT OF THE Validated STATE. A Task hands its output on whole, so nothing in a
    Task-to-Task chain would notice validate-authorize renaming a field — the rename would
    surface later as a JSONPath failure in a state nobody was looking at. A Pass naming each
    key fails HERE instead."""
    import archive_validate_authorize as verb

    source = pathlib.Path(verb.__file__).read_text()
    emitted = source[source.index("    validated = {"):]
    returned = set(re.findall(r'^\s{8}"([A-Za-z]+)":', emitted, re.MULTILINE))

    declared = {name.removesuffix(".$") for name in STATES["Validated"]["Parameters"]}

    assert declared == returned, (
        f"the machine reads {sorted(declared)} but the verb returns {sorted(returned)}"
    )


def test_the_validated_pass_carries_no_placeholder_status_literal():
    """A placeholder marker that outlives its placeholder is how a field nothing reads
    survives into production (file-send's recorded lesson, which shipped a `status` literal
    for two specs)."""
    assert "status" not in STATES["Validated"]["Parameters"]


# ── The failure seeds: what they carry, and what they must not read ──────────


def _seeds():
    """Every Pass state that feeds RecordFailure — this machine's failure seeds."""
    return {
        name: state
        for name, state in STATES.items()
        if state.get("Type") == "Pass" and state.get("Next") == "RecordFailure"
    }


def test_the_seed_scan_found_every_seed():
    """Guards every check below against passing vacuously if the machine is restructured."""
    assert set(_seeds()) == {
        "ValidateFailureSeed",
        "UnknownModeSeed",
        "NothingToArchiveSeed",
        "RollbackReturnedSeed",
        "RequestFailureSeed",
        "NothingToRestoreSeed",
        "RestoreTimedOutSeed",
        "RestoreIncompleteReturnedSeed",
    }


def test_a_seed_reads_only_paths_its_own_input_actually_has():
    """A Pass state's JSONPath hard-fails on an ABSENT key with `States.Runtime`, which is
    neither retriable nor catchable — so the failure terminal dies BEFORE its notify state and
    the user hears nothing at all, on a request that already failed.

    THE FLEET GUARD DOES NOT COVER THIS. `test_a_failure_seed_supplies_every_key_the_failure_
    terminal_reads` walks FORWARD from a seed, checking what downstream states read against
    what the seed supplies; it says nothing about what the seed ITSELF reads. Measured: adding
    `"source.$": "$.source"` to ValidateFailureSeed — whose input after the Catch is the raw
    `{Error, Cause}`, so the path does not exist — left the whole fleet suite green.

    `ValidateFailureSeed`'s input is the raw error (the Catch had no object to merge into), so
    it may read `$` and the CONTEXT OBJECT and nothing else. `UnknownModeSeed`'s input is the
    validated request, so it may read that request's own top-level keys.
    """
    validated = set(STATES["Validated"]["Parameters"])
    validated = {name.removesuffix(".$") for name in validated}
    post_validate = validated | {"error"}
    allowed = {
        "ValidateFailureSeed": set(),
        "UnknownModeSeed": validated,
        "NothingToArchiveSeed": validated,
        "RollbackReturnedSeed": validated,
        "RequestFailureSeed": post_validate,
        # SPEC-171's three, all reached from post-validate states on the restore arm, so each
        # may read the validated request's own top-level keys and nothing further.
        "NothingToRestoreSeed": validated,
        "RestoreTimedOutSeed": validated,
        "RestoreIncompleteReturnedSeed": validated,
    }

    for name, seed in _seeds().items():
        for key, value in seed["Parameters"].items():
            if not key.endswith(".$") or not isinstance(value, str):
                continue
            if value == "$" or value.startswith("$$."):
                continue
            path = value.removeprefix("$.").split(".")[0]
            assert path in allowed[name], (
                f"{name} reads $.{path}, which its input does not carry — an absent key raises "
                "an uncatchable States.Runtime and the user is never notified"
            )


def test_no_seed_carries_the_selection_a_second_time():
    """A SIZE decision, not tidying, and it is asserted against the ASL rather than argued in a
    comment. `$.raw` is the Pipe's record, which at ARCHIVE_MAX_ITEM_BYTES is ~200 KB of
    escaped selection; `$.source` is that same selection AGAIN. The two together breach the
    256 KB state limit for a quote-heavy selection — on a Pass with NO Catch, killing the run
    before NotifyFailure, on exactly the failures SPEC-152 exists to report.

    Measured: an earlier version of this test did the arithmetic over two literal strings and
    never read the machine at all, so adding `"source.$": "$.source"` to a seed left it green.
    """
    for name, seed in _seeds().items():
        assert "source.$" not in seed["Parameters"], (
            f"{name} carries $.source beside $.raw — the same selection twice"
        )
        assert "raw.$" in seed["Parameters"], f"{name} must supply $.raw; RecordFailure reads it"


# ── The ceiling, and the door that makes it reachable (SPEC-169 FR-003) ──────


def _stepfunction_tf() -> str:
    """The archive Step Function's Terraform, as text.

    Read as DATA rather than restated: the ceiling and the rule that makes it reachable are
    one decision written in two files, and a test that asserted one and described the other
    is how the pair comes apart.
    """
    return pathlib.Path(_HERE, "..", "..", "infra", "modules", "archive", "stepfunction.tf").read_text()


def _locals_tf() -> str:
    """The archive module's Terraform locals, as text."""
    return pathlib.Path(_HERE, "..", "..", "infra", "modules", "archive", "locals.tf").read_text()


def test_the_machine_carries_a_top_level_ceiling():
    """A Standard workflow with no TimeoutSeconds runs for ONE YEAR, and this is the first
    version of this machine that can wedge — it is the first with a Map and a copy in it.

    Asserted at the TOP level, which is where the field belongs: SPEC-157 settled that
    distinction on the table-builder, where the same name exists as a Task field and means
    something else entirely.
    """
    assert "TimeoutSeconds" in ASL, (
        "this machine has a Map and a copy in it, so a run can wedge until Step Functions' own "
        "one-year default"
    )
    assert re.search(r"state_machine_timeout_seconds\s*=\s*(\d+)", _locals_tf())


def test_the_ceiling_ships_with_the_rule_that_makes_it_reachable():
    """THE HALF THAT IS EASY TO LEAVE OUT. AWS catchers cover Task, Parallel and Map states
    but NOT top-level execution failures: the ceiling terminates the execution outright, so
    no state runs, NotifyFailure is never invoked and the actor is told nothing at all — SPEC-152
    satisfied on paper and silent in practice, on the one failure where the user has been
    waiting for three hours.
    """
    body = _stepfunction_tf()

    assert "aws_cloudwatch_event_rule" in body and "TIMED_OUT" in body
    assert "aws_cloudwatch_event_target" in body, "the rule fires at nothing"
    assert "aws_lambda_permission" in body, "EventBridge may not invoke the notifier"


def test_the_timeout_rule_never_matches_a_plain_failure():
    """Every other whole-request failure already reaches NotifyFailure through a Catch, so a
    rule matching FAILED would send a second notification for every one of them."""
    body = _stepfunction_tf()
    pattern = body[body.index("event_pattern"):]
    pattern = pattern[: pattern.index("}\n")]

    assert "TIMED_OUT" in pattern, "the slice missed the status list — it is the parse that broke"
    assert "FAILED" not in pattern


def test_the_notifier_was_raised_for_the_door_it_grew():
    """15s was sized for a decode and a send. The timeout door does strictly more: a
    DescribeExecution read-back plus a cold-start JWKS fetch and a JWT verify, because the actor
    has to come from the token in the timed-out execution's own input. File-send's twin and the
    DLQ drain, which do the same verify, are both at 60s."""
    row = re.search(r'"notify-failure"\s*=\s*\{[^}]*timeout\s*=\s*(\d+)', _locals_tf())

    assert row and int(row.group(1)) >= 60


# ── The transfer (SPEC-169 FR-003) ───────────────────────────────────────────


def _map_states() -> dict:
    """Every Map state in the machine, by name."""
    return {name: state for name, state in STATES.items() if state.get("Type") == "Map"}


def test_every_map_is_top_level_and_there_are_exactly_three():
    """FR-003 AC1. A Distributed Map nested inside another Map is the shape SPEC-160 rejected:
    one flat fan-out over a (destination x object) manifest is what makes the ceiling the
    manifest's length rather than one Lambda's timeout. Asserted by walking every state's
    NESTED states rather than by reading the top-level list, because a nested Map is exactly
    what would not appear there.

    THREE since SPEC-171, and the restore's two are a pair rather than a duplication: the same
    manifest is read once to ASK for the objects and once, hours later, to COPY them, because a
    GLACIER object is not readable until a billed retrieval has finished with it.
    """
    assert set(_map_states()) == {"TransferObjects", "RetrieveObjects", "CopyBackObjects"}

    for name, state in STATES.items():
        nested = ((state.get("ItemProcessor") or {}).get("States") or {}).values()
        assert not [inner for inner in nested if inner.get("Type") == "Map"], (
            f"{name} nests a Map inside its own ItemProcessor"
        )


def test_the_transfer_map_is_distributed_standard_and_tolerates_every_item_failure():
    """Three settings, each for its own reason. DISTRIBUTED is what makes it a child-execution
    fan-out at all. STANDARD, not EXPRESS: a batch may hold a multi-GiB object whose multipart
    copy would blow EXPRESS's 5-minute ceiling, and at-least-once re-execution would recopy the
    batch. ToleratedFailurePercentage 100 is the one this plane needs most — a Map that aborted
    early would leave the COMMIT GATE unable to tell 'failed' from 'not attempted', and this
    gate decides whether a user's only copy is deleted."""
    transfer = STATES["TransferObjects"]

    assert transfer["ItemProcessor"]["ProcessorConfig"] == {
        "Mode": "DISTRIBUTED",
        "ExecutionType": "STANDARD",
    }
    assert transfer["ToleratedFailurePercentage"] == 100
    assert transfer["ItemReader"]["ReaderConfig"]["InputType"] == "JSONL"
    assert transfer["ResultWriter"]["Resource"] == "arn:aws:states:::s3:putObject"


def test_the_rendered_map_carries_the_engines_own_batch_numbers():
    """Terraform cannot import Python, so the ASL's ItemBatcher and MaxConcurrency are literals
    fed from locals.tf. Two homes for one number is how a batch silently grows past the limit it
    was sized against."""
    from cpcommon.transfer import config as transfer_config

    text = _locals_tf()

    assert re.search(
        rf"transfer_max_items_per_batch\s*=\s*{transfer_config.MAX_ITEMS_PER_BATCH}\b", text
    )
    assert re.search(
        rf"transfer_map_max_concurrency\s*=\s*{transfer_config.MAP_MAX_CONCURRENCY}\b", text
    )


def test_the_execution_name_is_stamped_by_a_pass_and_never_read_in_a_tasks_parameters():
    """SPEC-157's recorded shape. Reading `$$` inside a Task's own Parameters WRAPS the payload
    one level down, and every notify path on this plane reads the request at the TOP level — so
    the request would still be there and every failure message would resolve to nothing."""
    assert STATES["StampExecution"]["Parameters"]["name.$"] == "$$.Execution.Name"

    for name, state in STATES.items():
        if state.get("Type") != "Task":
            continue
        for key, value in (state.get("Parameters") or {}).items():
            assert not (isinstance(value, str) and value.startswith("$$")), (
                f"{name} reads the context object in a Task's Parameters ({key})"
            )


def test_the_choice_before_the_map_guards_its_comparison_and_refuses_an_empty_archive():
    """FR-002 AC7 and FR-001 AC6 meeting in one state. IsPresent BEFORE the numeric test,
    because a Choice on an absent path raises an uncatchable States.Runtime that `Default` does
    not cover — and the Default is a REFUSAL rather than a skip to success, because a receipt
    claiming zero files archived is worse than a refusal and an empty archive prefix is
    indistinguishable at restore time from one whose objects have vanished."""
    choice = STATES["HasTransferItems"]["Choices"][0]
    clauses = choice["And"]

    assert clauses[0]["IsPresent"] is True
    assert "NumericGreaterThan" in clauses[1]
    assert {c["Variable"] for c in clauses} == {"$.transfer.itemCount"}
    assert STATES["HasTransferItems"]["Default"] == "NothingToArchiveSeed"


# ── The commit gate (SPEC-169 FR-004) ────────────────────────────────────────


def _reachable_from(start: str) -> set:
    """Every state reachable from one state, following Next, Catch, Choices and Default."""
    seen, frontier = set(), [start]
    while frontier:
        name = frontier.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        state = STATES[name]
        frontier.append(state.get("Next"))
        frontier.append(state.get("Default"))
        frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])
        frontier.extend(c.get("Next") for c in state.get("Choices", []) or [])
    return seen


def test_no_path_from_the_rollback_branch_reaches_the_deletion():
    """**THE TEST THIS WHOLE SPEC EXISTS FOR.** The source is deleted only when every single
    object has been confirmed copied, and the failure mode it must never have is "copied 900 of
    1000, deleted 1000".

    Asserted by walking the GRAPH from the gate's rollback arm, not by reading the states in
    order: a Catch or a Next added anywhere on that arm could reconnect it, and nothing about
    the diff would say so.
    """
    rollback_arm = _reachable_from(STATES["CommitOrRollback"]["Default"])

    assert "DeleteSource" not in rollback_arm, (
        f"the rollback branch reaches the deletion via {sorted(rollback_arm)} — a partial "
        "archive would delete the source it does not hold"
    )
    assert "Failed" in rollback_arm, "the rollback branch does not fail the execution"


def test_the_commit_gate_guards_its_comparison_and_fails_closed():
    """The gate is one boolean computed by one verb, so there is one place it can be wrong. Its
    Default is the ROLLBACK rather than the commit: an absent or unrecognisable verdict must
    fail closed, because the failure on the other side is deleting a user's only copy."""
    gate = STATES["CommitOrRollback"]
    clauses = gate["Choices"][0]["And"]

    assert clauses[0]["IsPresent"] is True
    assert clauses[1]["BooleanEquals"] is True
    assert {c["Variable"] for c in clauses} == {"$.transferOutcome.complete"}
    assert gate["Default"] == "Rollback"
    assert gate["Choices"][0]["Next"] != "Rollback"


def test_the_deletion_sits_between_the_record_and_the_receipt():
    """FR-006 AC2/AC8: most durable to least. The record that describes the archive is written
    BEFORE the source is deleted, and the receipt AFTER it — so a receipt only ever exists for an
    archive that actually completed, and a run interrupted between any two states leaves
    something an operator can read."""
    assert STATES["CommitOrRollback"]["Choices"][0]["Next"] == "WriteManifest"
    assert STATES["WriteManifest"]["Next"] == "DeleteSource"
    assert STATES["DeleteSource"]["Next"] == "WriteReceipt"


def test_the_success_terminal_names_what_it_keeps_and_drops_the_rest():
    """A payload decision, asserted where it can fail: the plan key, the transfer block, the Map
    Run pointer and the selection are all dropped rather than carried into the execution output,
    where SPEC-172 will read this shape.

    It is deliberately NOT the cross-check `Validated` is — that one parses the validator's real
    return value, and this one cannot, because write-receipt returns `{**event, …}` and its keys
    are not statically enumerable. What holds the paths here is that every one of them is produced
    by a verb whose own suite asserts it.
    """
    kept = {name.removesuffix(".$") for name in STATES["ArchiveComplete"]["Parameters"]}

    assert kept == {"requestId", "actor", "archive", "objectCount", "totalBytes", "receiptKey"}
    assert STATES["ArchiveComplete"]["Next"] == "Succeeded"


# ── The restore arm, and the ordering the bill depends on (SPEC-170) ─────────


def test_the_restore_arm_reaches_the_guard_before_it_can_reach_anything_else():
    """FR-004 AC7, and the reason SPEC-170 is its own spec. Glacier retrieval is BILLED and
    IRREVERSIBLE once initiated, so the conflict has to be found on this side of it — a guard
    after the retrieval would report the same refusal and charge the user for the privilege.

    Asserted as an ORDER over the arm rather than as "the guard exists": SPEC-171 adds
    RestoreObject and a Wait loop after RestoreReady, and the property that has to survive that
    is this one.
    """
    arm = [c["Next"] for c in STATES["ChooseMode"]["Choices"] if "restore" in json.dumps(c)]

    assert arm == ["InspectArchive"]
    assert STATES["InspectArchive"]["Next"] == "SeedInitialGuard"
    assert STATES["SeedInitialGuard"]["Next"] == "CheckDestinationClear"
    assert STATES["CheckDestinationClear"]["Next"] == "StampRestoreExecution"


def test_no_path_from_the_guards_refusal_reaches_anything_but_the_failure_terminal():
    """The other half of the same rule, walked from the GRAPH — because "there is no retrieval
    state yet" made a "no path to a retrieval" assertion pass vacuously right up until SPEC-171
    added one.

    What is asserted instead is total: everything reachable from the guard's failure branch is
    the failure path itself. The retrieval states now exist, so the moment any of them becomes
    reachable from a refusal — through a Catch, a Next or a Choice — this fails.
    """
    refusal = _reachable_from(STATES["CheckDestinationClear"]["Catch"][0]["Next"])

    assert refusal == {"RequestFailureSeed", "RecordFailure", "NotifyFailure", "Failed"}


# ── the bill, and everything that must not be able to reach it (SPEC-171) ────


def test_no_refusal_before_the_bill_can_reach_the_retrieval():
    """FR-001 AC8, AND IT IS THE ONE ASSERTION THIS SPEC MOST NEEDS. `RestoreObject` is billed
    the moment it is issued and cannot be cancelled, so a refusal that could somehow fall
    through to it would charge a user for a restore that was already known to be impossible.

    Walked from the GRAPH per refusing state rather than read off the ASL in order, because a
    `Catch` or a `Next` added anywhere on those arms could reconnect them and nothing about the
    diff would say so. All three of SPEC-170's refusals — `destination_occupied`,
    `archive_not_found` and `restore_archive_incomplete` — are raised by these two verbs, so
    their Catches are the whole surface.
    """
    for state in ("InspectArchive", "CheckDestinationClear"):
        arm = _reachable_from(STATES[state]["Catch"][0]["Next"])

        assert "RetrieveObjects" not in arm, (
            f"{state}'s refusal reaches the retrieval via {sorted(arm)} — a user would be "
            "billed for hours of Glacier retrieval that cannot land"
        )
        assert "CopyBackObjects" not in arm and "DeleteArchived" not in arm


def test_the_guard_runs_before_the_retrieval_and_the_receipt_marker_between_them():
    """FR-006 AC4's ordering, and it is a SAFETY ordering rather than a cosmetic one. The
    receipt marker says a restore is in flight, and it is written BEFORE the retrieval rather
    than after: there its failure costs nothing, where the same failure a moment later would
    fail a run the user had already been billed for."""
    assert STATES["StampRestoreExecution"]["Next"] == "BuildRestoreManifest"
    assert STATES["BuildRestoreManifest"]["Next"] == "HasRestoreItems"
    assert STATES["HasRestoreItems"]["Choices"][0]["Next"] == "SeedRestoreRequested"
    assert STATES["SeedRestoreRequested"]["Next"] == "MarkRestoreRequested"
    assert STATES["MarkRestoreRequested"]["Next"] == "RetrieveObjects"


def test_the_retrieval_map_tolerates_no_failure_where_the_copy_tolerates_every_one():
    """The two settings are opposites and both are right. The COPY must finish whatever happens,
    or the gate after it cannot tell 'failed' from 'not attempted' — and that gate decides
    whether data is deleted. The RETRIEVAL has no such gate: a genuine fault means nothing was
    copied and the archive is untouched, so failing the Map Run outright is the cheapest correct
    answer, and re-submitting costs no second bill because the verb tolerates
    RestoreAlreadyInProgress.
    """
    assert STATES["RetrieveObjects"]["ToleratedFailurePercentage"] == 0
    assert STATES["CopyBackObjects"]["ToleratedFailurePercentage"] == 100
    assert STATES["TransferObjects"]["ToleratedFailurePercentage"] == 100


def test_the_retrieval_map_exports_its_results_even_though_nothing_reads_them():
    """A Distributed Map with no ResultWriter AGGREGATES its children's output onto the state,
    and at ARCHIVE_MAX_OBJECTS in batches of 8 that is 2,500 children — States.DataLimitExceeded,
    thrown outside every Catch, before ResultPath could discard anything. The export exists for
    that reason alone, which is why its prefix is its own and the collector never reads it."""
    retrieval = STATES["RetrieveObjects"]

    assert retrieval["ResultWriter"]["Resource"] == "arn:aws:states:::s3:putObject"
    assert retrieval["ResultWriter"]["Parameters"]["Prefix.$"] == "$.transfer.retrievalResultsPrefix"
    assert retrieval["ResultPath"] is None
    assert STATES["CopyBackObjects"]["ResultWriter"]["Parameters"]["Prefix.$"] == (
        "$.transfer.resultsPrefix"
    )


def test_both_restore_maps_read_the_one_manifest():
    """One dataset, read twice. Two would be two things that could disagree with the plan, and
    the disagreement would surface as a restore that retrieved one set of objects and copied
    another — with every count still agreeing with itself."""
    for name in ("RetrieveObjects", "CopyBackObjects"):
        reader = STATES[name]["ItemReader"]["Parameters"]

        assert reader["Bucket.$"] == "$.transfer.manifestBucket"
        assert reader["Key.$"] == "$.transfer.manifestKey"


# ── the wait loop (SPEC-171 FR-002) ─────────────────────────────────────────


def test_the_loop_is_wait_then_poll_then_choice_and_it_closes():
    """FR-002 AC1. The only loop in this repo, and it exists because a GLACIER object is not
    readable until S3 has spent 3-5 hours making a temporary copy of it. Asserted as a CYCLE —
    the Default must come back to the Wait — because a loop whose exit is right and whose return
    edge is missing is a machine that polls exactly once."""
    # SPEC-172 inserted the restore-started notification between the retrieval and the wait, so
    # the edge is now two hops. Followed rather than re-pinned to the new state's name: what this
    # test is about is that the retrieval reaches the LOOP, and a notification is not a loop.
    assert STATES["RetrieveObjects"]["Next"] == "NotifyRestoreStarted"
    assert STATES["NotifyRestoreStarted"]["Next"] == "WaitForRetrieval"
    assert STATES["WaitForRetrieval"]["Type"] == "Wait"
    assert STATES["WaitForRetrieval"]["Next"] == "PollRestore"
    assert STATES["PollRestore"]["Next"] == "RestoreRetrieved"
    assert STATES["RestoreRetrieved"]["Default"] == "WaitForRetrieval"


def test_the_wait_carries_the_interval_the_python_constant_names():
    """Terraform cannot import Python, so the Wait's Seconds is a literal fed from locals.tf.
    Two homes for one number is how a five-minute poll becomes a five-second one against a
    3-5 hour retrieval, which is a Lambda invocation every five seconds for hours."""
    from arcommon import config

    assert re.search(rf"restore_poll_seconds\s*=\s*{config.RESTORE_POLL_SECONDS}\b", _locals_tf())


def test_the_iteration_cap_is_not_an_ASL_literal():
    """RESTORE_MAX_POLLS lives in Python alone: poll-restore computes `exhausted` and the Choice
    reads a boolean. A literal here plus a constant there would be two numbers that could only
    disagree on a restore already going badly — and the ASL copy is the one nobody would think
    to change."""
    from arcommon import config

    assert "exhausted" in json.dumps(STATES["RestoreRetrieved"])
    assert str(config.RESTORE_MAX_POLLS) not in json.dumps(STATES["RestoreRetrieved"])


def test_the_loops_exit_guards_every_comparison_and_cannot_spin_on_a_lost_shape():
    """The usual IsPresent rule, plus the one a LOOP needs and a linear machine does not. With
    only the two positive clauses, a poll output that lost its shape would satisfy neither, fall
    to the Default and go round again — every five minutes until the machine's own ceiling, with
    nothing in the log to say why. The third clause is `IsPresent: false` on the poll's own
    counter, so an unrecognisable verdict ends the loop instead of feeding it.
    """
    choices = STATES["RestoreRetrieved"]["Choices"]
    positive = [c for c in choices if "And" in c]

    for choice in positive:
        guarded = {c["Variable"] for c in choice["And"] if c.get("IsPresent") is True}
        compared = {c["Variable"] for c in choice["And"] if "BooleanEquals" in c}
        assert compared and compared <= guarded

    fail_closed = [c for c in choices if c.get("IsPresent") is False]
    assert fail_closed, "the loop has no guard against a poll output that lost its shape"
    assert {c["Next"] for c in fail_closed} == {"RestoreTimedOutSeed"}


def test_the_loops_timeout_is_not_the_machines_and_reaches_the_ordinary_failure_door():
    """The machine's own TimeoutSeconds kills the execution outright and needs the EventBridge
    TIMED_OUT rule to say anything at all. This one fires while the execution is HEALTHY, so it
    reaches RecordFailure and NotifyFailure through the door every other failure uses."""
    arm = _reachable_from("RestoreTimedOutSeed")

    assert arm == {"RestoreTimedOutSeed", "RecordFailure", "NotifyFailure", "Failed"}


# ── the restore's gate: the commit gate's mirror image (SPEC-171 FR-004) ────


def test_no_path_from_the_partial_restore_reaches_the_archive_deletion():
    """**THE TEST THIS SPEC EXISTS FOR, and it is the archive gate's rule pointing the other
    way.** A partial restore cannot be rolled back — the user's space already holds some of
    their own data — so the archive is the only complete copy left in existence and NOTHING on
    that arm may delete it. A restore that half succeeded and then deleted its own source would
    be unrecoverable.

    Walked from the GRAPH, because a Catch added anywhere on that arm could reconnect it.
    """
    partial = _reachable_from(STATES["RestoreCompleteOrPartial"]["Default"])

    assert "DeleteArchived" not in partial, (
        f"the partial-restore branch reaches the archive deletion via {sorted(partial)} — the "
        "only complete copy of the user's data would be destroyed"
    )
    assert "Failed" in partial, "the partial-restore branch does not fail the execution"


def test_a_fixtured_export_with_one_failure_lands_on_the_arm_that_cannot_delete():
    """**FR-004 AC4 END TO END, joining the two halves nothing else joins.** The graph walk above
    proves the arm cannot reach the deletion; the collector's own suite proves a failed item
    yields `complete: false`. Neither says the verdict the collector actually produces is routed
    to that arm — which is the claim the AC makes, and the one a renamed field or an inverted
    Choice would break with both halves still green.

    So this runs the REAL collector over a REAL `ResultWriter` export carrying one failure, reads
    the boolean off its output, evaluates the gate's own Choice against it, and walks the graph
    from wherever that lands.
    """
    import archive_collect_transfer_results as collector
    from cpcommon import clients

    export = {
        "MapRunArn": "arn:aws:states:us-east-1:1:mapRun/m/r",
        "ResultFiles": {
            "SUCCEEDED": [{"Key": "archive/r/restore-results/SUCCEEDED_0.json", "Size": 1}]
        },
    }
    succeeded = [
        {"Input": json.dumps({"Items": [{"srcKey": "a"}, {"srcKey": "b"}]}),
         "Output": json.dumps({"copied": 1, "failures": [{"reason": "copy_failed"}]})},
    ]

    class _FakeS3:
        def get_object(self, Bucket, Key):
            body = export if Key.endswith("manifest.json") else succeeded

            class _B:
                def read(self_inner):
                    return json.dumps(body).encode()

            return {"Body": _B()}

    clients._s3 = _FakeS3()

    out = collector.handler(
        {
            "requestId": "9f2c1b8e-1111-4222-8333-444444444444",
            "actor": {"username": "alice"},
            "objectCount": 2,
            "transfer": {"itemCount": 2},
            "mapRun": {
                "ResultWriterDetails": {"Bucket": "admin-bkt", "Key": "archive/r/manifest.json"}
            },
        },
        None,
    )

    assert out["transferOutcome"]["complete"] is False, "the fixture did not produce a failure"

    gate = STATES["RestoreCompleteOrPartial"]
    clause = gate["Choices"][0]["And"][1]
    taken = (
        gate["Choices"][0]["Next"]
        if out["transferOutcome"]["complete"] == clause["BooleanEquals"]
        else gate["Default"]
    )

    assert "DeleteArchived" not in _reachable_from(taken), (
        "one failed item routed to an arm that can delete the archive — the only complete copy "
        "of data the user has just half received"
    )
    assert "Failed" in _reachable_from(taken)


def test_the_restores_gate_guards_its_comparison_and_fails_closed():
    """Same shape as the commit gate and the same reasoning turned around: an unrecognisable
    verdict must fail closed, which here means keeping a VAULT where on the archive arm it means
    keeping a SOURCE."""
    gate = STATES["RestoreCompleteOrPartial"]
    clauses = gate["Choices"][0]["And"]

    assert clauses[0]["IsPresent"] is True
    assert clauses[1]["BooleanEquals"] is True
    assert {c["Variable"] for c in clauses} == {"$.transferOutcome.complete"}
    assert gate["Default"] == "SeedRestoreIncomplete"
    assert gate["Choices"][0]["Next"] == "DeleteArchived"


def test_the_partial_arm_records_the_outcome_before_it_fails():
    """FR-006 AC2. The receipt must never claim a restore that did not finish, so the partial
    arm writes it before raising — the rollback verb's shape on the archive arm, and the reason
    update-receipt is reached from three states rather than one."""
    assert STATES["SeedRestoreIncomplete"]["Parameters"]["status"] == "incomplete"
    assert STATES["SeedRestoreIncomplete"]["Next"] == "ReportRestoreIncomplete"
    assert STATES["ReportRestoreIncomplete"]["Next"] == "RestoreIncompleteReturnedSeed"


# ── cleanup and the receipt: the two failures that do NOT fail a run ────────


def test_the_cleanups_failure_reaches_the_success_terminal():
    """FR-005 AC3, and it is the exact inverse of delete-source's discipline. There a partial
    deletion means a user told their archive completed while their files were still half there.
    Here the outcome the user asked for has already happened — their data is back — and residue
    in a bucket the browser cannot reach costs storage the 7-year expiry sweeps. So it is a flag
    on a SUCCESSFUL run, and the flag is injected by a Pass because RestoreComplete names
    `$.cleanup` and a Pass reading an absent key raises an uncatchable States.Runtime.
    """
    assert STATES["DeleteArchived"]["Catch"][0]["Next"] == "CleanupIncomplete"
    assert STATES["CleanupIncomplete"]["Result"]["cleanupIncomplete"] is True
    assert STATES["CleanupIncomplete"]["ResultPath"] == "$.cleanup"
    assert "Succeeded" in _reachable_from("CleanupIncomplete")
    assert "Failed" not in _reachable_from("CleanupIncomplete")


def test_the_receipt_rewrites_failure_reaches_the_success_terminal():
    """FR-006 AC5. Most durable to least — data restored, then receipt, then notification — so
    by this state the data is already back and a failed rewrite must not take it away."""
    # Both exits now run through SPEC-172's success notification first, and the Catch reaching it
    # is the point: a user whose files are back must be told so whether or not the document
    # recording it could be rewritten.
    assert STATES["UpdateReceipt"]["Catch"][0]["Next"] == "NotifyRestored"
    assert STATES["NotifyRestored"]["Next"] == "RestoreComplete"
    assert "Failed" not in _reachable_from(STATES["UpdateReceipt"]["Catch"][0]["Next"])


def test_the_success_terminal_names_only_what_BOTH_arms_into_it_carry():
    """The receipt's key is deliberately absent. The Catch above reaches this state without one,
    and a Pass naming a key its input lacks raises an uncatchable States.Runtime — which would
    turn a failed receipt write into a killed execution on a run whose data had landed."""
    kept = {name.removesuffix(".$") for name in STATES["RestoreComplete"]["Parameters"]}

    assert "receiptKey" not in kept
    assert kept == {
        "requestId",
        "actor",
        "archive",
        "spaceRoot",
        "spaceKind",
        "objectCount",
        "totalBytes",
        "cleanup",
    }
    assert STATES["RestoreComplete"]["Next"] == "Succeeded"


def test_the_receipt_verbs_stage_is_seeded_by_the_machine_and_never_inferred():
    """One function serves three stages, so the STATE says which — the verb does not read the
    absence of `$.transferOutcome` and conclude anything. 'Nothing has run yet' and 'the run
    reported nothing' are different facts that look identical from inside a handler."""
    seeds = {
        "SeedRestoreRequested": "requested",
        "SeedRestoreDone": "restored",
        "SeedRestoreIncomplete": "incomplete",
    }
    for name, status in seeds.items():
        assert STATES[name]["Parameters"]["status"] == status
        assert STATES[name]["ResultPath"] == "$.restore"

    receipt_states = {
        name
        for name, state in STATES.items()
        if state.get("Type") == "Task"
        and state["Parameters"]["FunctionName"] == STATES["UpdateReceipt"]["Parameters"]["FunctionName"]
    }
    assert receipt_states == {"MarkRestoreRequested", "UpdateReceipt", "ReportRestoreIncomplete"}
    for name in receipt_states:
        seeding = [n for n, s in STATES.items() if s.get("Next") == name and s["Type"] == "Pass"]
        assert seeding, f"{name} invokes the receipt verb with no seeded stage"


def test_every_seed_carries_the_mode_so_a_restore_is_not_worded_as_an_archive():
    """One body table under two prefixes (arcommon.messages), so the failure path has to say
    which one it is. `ValidateFailureSeed` supplies a literal null because its input is the raw
    error — a Pass reading `$.mode` there would raise an uncatchable States.Runtime on the
    failure path itself."""
    for name, seed in _seeds().items():
        assert "mode" in seed["Parameters"] or "mode.$" in seed["Parameters"], (
            f"{name} does not carry the mode; a restore failure would be worded as an archive"
        )

    assert STATES["ValidateFailureSeed"]["Parameters"]["mode"] is None
    assert STATES["RecordFailure"]["Parameters"]["mode.$"] == "$.mode"


def test_every_verb_state_is_one_of_the_planes_deployed_functions():
    """The Task set is the plane's shape, asserted so that adding a state without its Lambda —
    or its IAM — fails here rather than at runtime with an AccessDenied that reads like an IAM
    bug. SPEC-168's version of this test asserted the machine wrote to S3 NOWHERE; this one
    replaces it, because the writes are now the point."""
    tasks = {name for name, state in STATES.items() if state.get("Type") == "Task"}
    nested = {
        name
        for state in STATES.values()
        for name in ((state.get("ItemProcessor") or {}).get("States") or {})
    }

    assert tasks == {
        "ValidateAuthorize",
        "InspectSource",
        "BuildTransferManifest",
        "CollectTransferResults",
        "Rollback",
        "WriteManifest",
        "DeleteSource",
        "WriteReceipt",
        "InspectArchive",
        "CheckDestinationClear",
        "ReCheckDestinationClear",
        "BuildRestoreManifest",
        "MarkRestoreRequested",
        "PollRestore",
        "CollectRestoreResults",
        "DeleteArchived",
        "UpdateReceipt",
        "ReportRestoreIncomplete",
        # SPEC-172's success producer, at the three points an outcome is known. It is a Task like
        # any other and belongs in this set for the same reason: a state whose Lambda is not
        # deployed fails at runtime with an error that reads like an IAM bug.
        "NotifyArchived",
        "NotifyRestoreStarted",
        "NotifyRestored",
        "NotifyFailure",
    }
    assert nested == {"CopyObjects", "InitiateRestore", "CopyBack"}


def test_the_state_count_is_not_the_verb_count_and_the_reuse_is_deliberate():
    """Three states invoke update-receipt and two apiece invoke copy-objects and
    collect-transfer-results, so the Task set above over-counts the plane's Lambdas. Both reuses
    are decisions rather than savings and are asserted rather than left implicit: a restore
    records its progress on the archive's own receipt at three stages, and the copy-back asks the
    copy's identical question in the opposite direction — what differs is only what the answer
    AUTHORIZES, which is the Choice after it."""
    arns = {}
    for name, state in STATES.items():
        if state.get("Type") == "Task":
            arns.setdefault(state["Parameters"]["FunctionName"], set()).add(name)
    for states in ((state.get("ItemProcessor") or {}).get("States") or {} for state in STATES.values()):
        for name, state in states.items():
            arns.setdefault(state["Parameters"]["FunctionName"], set()).add(name)

    shared = {frozenset(names) for names in arns.values() if len(names) > 1}

    assert shared == {
        frozenset({"MarkRestoreRequested", "UpdateReceipt", "ReportRestoreIncomplete"}),
        frozenset({"CopyObjects", "CopyBack"}),
        frozenset({"CollectTransferResults", "CollectRestoreResults"}),
        frozenset({"CheckDestinationClear", "ReCheckDestinationClear"}),
        # SPEC-172. The third deliberate reuse, and the same reasoning as update-receipt's: the
        # outcome is a property of WHERE the machine is rather than of what is on the state — all
        # three points carry identical keys — so the ASL seeds it and one verb renders all three.
        frozenset({"NotifyArchived", "NotifyRestoreStarted", "NotifyRestored"}),
    }


# ── SPEC-172: the success producer, and the two things it must never do ──────


def _notify_states():
    """The three states that invoke the success producer, by name."""
    return {"NotifyArchived", "NotifyRestoreStarted", "NotifyRestored"}


def test_the_success_producer_can_never_fail_the_run():
    """THE INVARIANT THIS FEATURE CANNOT LOSE. On the archive arm the source is DELETED before
    the notification is sent, so a notifier that could fail the execution would turn a completed
    archive into a reported failure with the data already gone — and on the restore arm it would
    report a failure over files that are back in the user's space.

    Asserted as "every exit is a forward one": both the Next and every Catch must lead to the
    state this one was inserted in front of, and never to the failure seed.
    """
    forward = {
        "NotifyArchived": "ArchiveComplete",
        "NotifyRestoreStarted": "WaitForRetrieval",
        "NotifyRestored": "RestoreComplete",
    }
    for name, onward in forward.items():
        state = STATES[name]
        assert state["Next"] == onward, name
        catches = state.get("Catch") or []
        assert catches, f"{name} has no Catch, so a Lambda fault fails the execution"
        for catch in catches:
            assert catch["ErrorEquals"] == ["States.ALL"], name
            assert catch["Next"] == onward, name


def test_the_success_producer_cannot_reshape_the_running_object():
    """`ResultPath: null` on all three. Two of them sit MID-machine — the restore-started one is
    followed by a Wait, a poll loop, a second guard and a copy — and a verb that returned onto
    the state would replace the object every one of those reads."""
    for name in _notify_states():
        assert STATES[name]["ResultPath"] is None, name


def test_the_asl_seeds_the_outcome_rather_than_the_verb_inferring_it():
    """The three call sites carry IDENTICAL keys — request id, actor, space, counts — so nothing
    on the state distinguishes them. Inferring would mean guessing, and a restore-started message
    on a finished restore is worse than no message at all (SPEC-171 settled its two destination
    guards the same way)."""
    seeded = {STATES[name]["Parameters"]["Payload"]["outcome"] for name in _notify_states()}

    assert seeded == {"archived", "restore_started", "restored"}


def test_each_outcome_is_seeded_from_exactly_one_state():
    """One notification per outcome (SPEC-114's rule, which is about OUTCOMES and not verbs). A
    second state seeding the same token would put two rows in one inbox for one event."""
    seeded = [STATES[name]["Parameters"]["Payload"]["outcome"] for name in sorted(_notify_states())]

    assert len(seeded) == len(set(seeded))


def test_the_archived_notification_runs_after_the_receipt_exists():
    """It hands out the archive id, and the receipt is where that id can be read back. Announced
    before write-receipt, a run whose receipt then failed would have told the user to look in a
    folder holding nothing — on the one plane where the source is already gone."""
    assert STATES["WriteReceipt"]["Next"] == "NotifyArchived"


def test_the_restore_start_is_announced_after_the_retrieval_is_actually_requested():
    """RestoreObject is billed on request and cannot be cancelled, so THIS is where the hours
    begin. Announced before the Map, a failed retrieval would leave the user waiting for a
    completion that was never going to come."""
    assert STATES["RetrieveObjects"]["Next"] == "NotifyRestoreStarted"


def test_the_restore_success_is_announced_on_both_of_the_receipts_exits():
    """A receipt that could not be rewritten is a FLAG on a successful run (SPEC-171), not a
    failure of it — so the user whose files are back is told they are back either way."""
    assert STATES["UpdateReceipt"]["Next"] == "NotifyRestored"
    assert STATES["UpdateReceipt"]["Catch"][0]["Next"] == "NotifyRestored"


def test_no_success_notification_sits_on_a_failure_path():
    """The failure arm has its own producer (SPEC-152's NotifyFailure) and its own wording. A
    success state reachable from RecordFailure would tell a user their archive completed on the
    run that reported it had not."""
    seen, frontier = set(), ["RecordFailure"]
    while frontier:
        name = frontier.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        state = STATES[name]
        frontier.append(state.get("Next"))
        frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])

    assert not (seen & _notify_states())


def _payload_paths(name):
    """The `.$` fields of one Task's Payload, as `{field: path}`."""
    payload = STATES[name]["Parameters"]["Payload"]
    flat = {}
    for key, value in payload.items():
        if key.endswith(".$"):
            flat[key[:-2]] = value
        elif isinstance(value, dict):
            for inner, path in value.items():
                flat[f"{key}.{inner[:-2]}"] = path
    return flat


def test_the_success_producers_payload_paths_are_the_ones_they_are_meant_to_read():
    """THE GUARD THIS SPEC'S THREE STATES NEEDED AND DID NOT HAVE.

    Every other Task on this machine passes ``"Payload.$": "$"`` — these three NAME their paths,
    which is the one shape a Pass-only seed check cannot see, and a Parameters path that is absent
    at runtime raises an uncatchable ``States.Runtime``. Measured while this was written: replacing
    ``$.source.kind`` with a path no state carries left the whole fleet suite green.

    Pinned as EXACT SETS rather than "contains", because the failure that matters most is not a
    typo — it is ``"actor.$": "$.actor"`` instead of ``$.actor.username``. That hands a dict to a
    message composer and then to ``MessageGroupId``, which throws inside SQS, is swallowed by
    ``emit_notification``'s except, and loses the notification silently with every test green.
    """
    common = {
        "requestId": "$.requestId",
        "actor": "$.actor.username",
        "space.kind": "$.source.kind",
        "space.name": "$.source.name",
        "objectCount": "$.objectCount",
        "totalBytes": "$.totalBytes",
    }

    assert _payload_paths("NotifyArchived") == common
    assert _payload_paths("NotifyRestoreStarted") == common
    # The restore's terminal alone reads the cleanup block, because it is the only outcome whose
    # wording depends on it (SPEC-171 made a failed vault sweep a flag on a SUCCESSFUL run).
    assert _payload_paths("NotifyRestored") == {**common, "cleanup": "$.cleanup"}


def test_every_path_the_producers_read_is_one_the_machine_carries_there():
    """The other half: the paths above have to EXIST at those three points.

    `requestId`, `actor` and `source` come from validate-authorize's five-key contract and are
    threaded by every verb's `{**event, ...}`. `objectCount`/`totalBytes` are set by inspect-source
    on the archive arm and inspect-archive on the restore arm — both upstream of all three states.
    `cleanup` is the only one written INSIDE the restore's tail, and it is written on BOTH routes
    into the terminal, which is what this asserts: `DeleteArchived` on success and the
    `CleanupIncomplete` Pass on its Catch. One route writing it would be a States.Runtime on the
    other, on a run whose data is already safely back.
    """
    assert STATES["CleanupIncomplete"]["ResultPath"] == "$.cleanup"
    assert "cleanupIncomplete" in STATES["CleanupIncomplete"]["Result"]
    assert STATES["DeleteArchived"]["Catch"][0]["Next"] == "CleanupIncomplete"
    # And the success route reaches the same terminal without passing through that Pass, so the
    # verb itself must write the block — asserted from its source rather than from a fixture,
    # because a fixture here would only restate the test's own assumption.
    delete_archived = (
        pathlib.Path(__file__).resolve().parents[1]
        / "archive-delete-archived"
        / "archive_delete_archived.py"
    ).read_text()

    assert '"cleanup": {' in delete_archived and '"cleanupIncomplete"' in delete_archived


def test_the_producer_reads_exactly_what_the_asl_sends_it():
    """The two halves of one contract, held together. A field renamed on either side alone is a
    notification that silently degrades — the verb reads `None`, composes a sentence about zero
    files, and every test on both sides stays green."""
    verb = (
        pathlib.Path(__file__).resolve().parents[1] / "archive-notify" / "archive_notify.py"
    ).read_text()
    sent = {field.split(".")[0] for field in _payload_paths("NotifyRestored")} | {"outcome"}
    read = set(re.findall(r'summary\.get\("([^"]+)"\)', verb))

    assert read == sent, f"the ASL sends {sorted(sent)}; the verb reads {sorted(read)}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
