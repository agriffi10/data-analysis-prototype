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

_ASL = os.path.join(_HERE, "..", "..", "infra", "modules", "archive", "state-machine.asl.json.tftpl")


def _load():
    raw = pathlib.Path(_ASL).read_text()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))


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


def test_the_transfer_is_the_only_map_and_it_is_top_level():
    """FR-003 AC1. A Distributed Map nested inside another Map is the shape SPEC-160 rejected:
    one flat fan-out over a (destination x object) manifest is what makes the ceiling the
    manifest's length rather than one Lambda's timeout. Asserted by walking every state's
    NESTED states rather than by reading the top-level list, because a nested Map is exactly
    what would not appear there."""
    assert set(_map_states()) == {"TransferObjects"}

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
    assert STATES["InspectArchive"]["Next"] == "CheckDestinationClear"
    assert STATES["CheckDestinationClear"]["Next"] == "RestoreReady"


def test_no_path_from_the_guards_refusal_reaches_anything_but_the_failure_terminal():
    """The other half of the same rule, walked from the GRAPH — because "there is no retrieval
    state yet" makes a "no path to a retrieval" assertion pass vacuously today and forever after.

    What is asserted instead is total: everything reachable from the guard's failure branch is
    the failure path itself. SPEC-171 adds its retrieval states downstream of RestoreReady, and
    the moment any of them becomes reachable from a refusal — through a Catch, a Next or a
    Choice — this fails.
    """
    refusal = _reachable_from(STATES["CheckDestinationClear"]["Catch"][0]["Next"])

    assert refusal == {"RequestFailureSeed", "RecordFailure", "NotifyFailure", "Failed"}


def test_the_restore_terminal_names_what_it_keeps_and_carries_the_plan_forward():
    """SPEC-171's replacement point. It keeps the plan KEY rather than the plan — the object
    list is what the 256 KB payload limit exists to keep off the state — and the archive block,
    because the retrieval is issued against those keys."""
    kept = {name.removesuffix(".$") for name in STATES["RestoreReady"]["Parameters"]}

    assert kept == {"requestId", "mode", "actor", "archive", "planKey", "objectCount", "totalBytes"}
    assert STATES["RestoreReady"]["Next"] == "Succeeded"


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
        "NotifyFailure",
    }
    assert nested == {"CopyObjects"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
