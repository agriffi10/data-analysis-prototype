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


# ── SPEC-172: the success producer, and the two things it must never do ──────


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


# ── the stamp runs before the verb that needs it ────────────────────────────


def test_the_execution_is_stamped_before_the_first_verb_that_reads_it():
    """**The ordering the archive id's claim depends on, and nothing else in the tree holds it.**

    inspect-source reads ``$.execution.name`` to claim the id. A stamp placed after it would
    leave that read empty on EVERY archive, which the verb refuses as malformed — so the whole
    plane would stop archiving, and the suite would not have noticed: the broken order is a
    perfectly legal state graph, and it was planted and run green before this test existed.

    It matters most across a deploy. The two deploy workflows are not sequenced, so the reorder
    and the claim land in separate PRs precisely to keep the stamp in front; a later edit that
    quietly moved it back would reopen that window with nothing to say so. Table-share and
    data-quality pin their own stamps the same way — this is the archive arm's missing copy.
    """
    assert STATES["ChooseMode"]["Choices"][0]["Next"] == "StampExecution"
    assert STATES["StampExecution"]["ResultPath"] == "$.execution"
    assert STATES["StampExecution"]["Parameters"] == {
        "name.$": "$$.Execution.Name",
        "startedAt.$": "$$.Execution.StartTime",
    }
    assert STATES["StampExecution"]["Next"] == "InspectSource"
    assert STATES["InspectSource"]["Next"] == "BuildTransferManifest"


def _reads_the_execution(states: dict) -> set:
    """Every state whose own Parameters read ``$.execution``, derived rather than listed."""
    return {
        name
        for name, state in states.items()
        if "$.execution" in json.dumps(state.get("Parameters") or {})
    }


def _reachable_without_stamping(states: dict) -> set:
    """Every state a path from the mode branch reaches WITHOUT passing through a stamp.

    The stamps are sinks rather than starting points, and that distinction is the whole rule: a
    walk that began AT a stamp would count its successors as covered even when nothing reaches
    the stamp at all, which is precisely the break this is looking for.
    """
    stamps = {"StampExecution", "StampRestoreExecution"}
    seen, frontier = set(), ["ChooseMode"]
    while frontier:
        name = frontier.pop()
        if not name or name in seen or name not in states or name in stamps:
            continue
        seen.add(name)
        state = states[name]
        frontier.append(state.get("Next"))
        frontier.append(state.get("Default"))
        frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])
        frontier.extend(c.get("Next") for c in state.get("Choices", []) or [])
    return seen


def _unstamped(states: dict) -> set:
    """Readers of ``$.execution`` a path can reach without a stamp having run."""
    return _reachable_without_stamping(states) & _reads_the_execution(states)


def test_no_state_reads_the_execution_on_a_path_that_never_stamped_it():
    """The rule rather than the instance. A reader a path reaches without passing a stamp gets
    an ABSENT key, and on a ``Pass`` that is an uncatchable ``States.Runtime`` — the failure this
    machine's own comments keep warning about, arriving on a path nobody walked.

    The population is derived from the rendered machine, so a state that starts reading
    ``$.execution`` joins it by existing. The three readers today are all restore seeds; the
    archive arm's reader is inside inspect-source rather than in ASL, which is why the test above
    pins that ordering separately and this one cannot.
    """
    readers = _reads_the_execution(STATES)

    assert readers, "no state reads $.execution — this test is measuring nothing"
    assert _unstamped(STATES) == set()


def test_that_rule_actually_catches_a_stamp_lifted_out_of_its_arm():
    """**The positive control, and it is not ceremony.** The assertion above is an emptiness
    check, and an emptiness check passes just as happily when the derivation has stopped finding
    anything. Routing the restore arm straight past its stamp has to flag the three seeds that
    then read a key nothing put there."""
    mutant = {name: dict(state) for name, state in STATES.items()}
    mutant["CheckDestinationClear"] = {
        **mutant["CheckDestinationClear"],
        "Next": "BuildRestoreManifest",
    }

    assert _unstamped(mutant) == {
        "SeedRestoreRequested",
        "SeedRestoreDone",
        "SeedRestoreIncomplete",
    }


# ── The transfer block the notifies thread ───────────────────────────────────

_TRANSFER_READ = re.compile(r'\$\.transfer(\.|")')
_BUILDERS = {"BuildTransferManifest", "BuildRestoreManifest"}


def _reads_the_transfer(states: dict) -> set:
    """Every state that reads ``$.transfer`` anywhere in its definition but its Comment.

    Anchored so ``$.transferOutcome`` is not a read of it, and taken over the whole state rather
    than its ``Parameters`` alone, because the Maps read the block from their ``ItemReader`` and
    the Choices from their rules.
    """
    return {
        name
        for name, state in states.items()
        if _TRANSFER_READ.search(json.dumps({k: v for k, v in state.items() if k != "Comment"}))
    }


def _keeps_the_state(state: dict) -> bool:
    """Whether a state's output still carries every key its input did.

    A Task whose result replaces the object — no ``ResultPath``, or ``$`` — keeps it only when it
    hands the whole state to a verb and selects the verb's return with ``OutputPath:
    $.Payload``, because every verb here returns ``{**event, …}``; without that selection the
    state becomes the Lambda response envelope. Anywhere else an ``OutputPath`` narrower than
    ``$`` drops keys. A ``ResultPath`` of null or a sub-path merges; ``$`` replaces. With no
    ``ResultPath`` a Pass that sets ``Parameters`` or ``Result`` replaces the object, a Map
    replaces it with its own output, and a Choice or a Wait passes it through.
    """
    kind = state.get("Type")
    output = state.get("OutputPath", "$")
    replaces = state.get("ResultPath", "$") == "$"
    if kind == "Task" and replaces:
        return (
            output == "$.Payload" and (state.get("Parameters") or {}).get("Payload.$") == "$"
        )
    if output != "$":
        return False
    if "ResultPath" in state:
        return not replaces
    if kind == "Pass":
        return "Parameters" not in state and "Result" not in state
    return kind in ("Choice", "Wait")


def _read_without_the_transfer(states: dict) -> set:
    """Readers of ``$.transfer`` some path reaches while the block is absent from the state.

    The walk carries whether the block is present. A builder puts it there on its way out; a
    state that replaces the object, or a Catch with no ``ResultPath``, takes it away. A reader
    reached without it is an absent ``Parameters`` path, which is an uncatchable
    ``States.Runtime`` — on ``NotifyArchived`` after the source has already been deleted.
    """
    readers = _reads_the_transfer(states)
    flagged, seen, frontier = set(), set(), [(ASL["StartAt"], False)]
    while frontier:
        name, present = frontier.pop()
        if not name or name not in states or (name, present) in seen:
            continue
        seen.add((name, present))
        if name in readers and not present:
            flagged.add(name)
        state = states[name]
        onward = True if name in _BUILDERS else present and _keeps_the_state(state)
        frontier.append((state.get("Next"), onward))
        frontier.append((state.get("Default"), onward))
        frontier.extend((c.get("Next"), onward) for c in state.get("Choices", []) or [])
        frontier.extend(
            (c.get("Next"), present and c.get("ResultPath", "$") != "$")
            for c in state.get("Catch", []) or []
        )
    return flagged


def test_no_state_reads_the_transfer_block_on_a_path_that_never_built_it():
    """The three notifies thread the WHOLE ``$.transfer`` block, not its ``fileCount``, so the
    file count cannot become a Parameters path the machine reads before a verb writes it. That
    makes the block itself load-bearing on every route into them, and this is the rule for it."""
    readers = _reads_the_transfer(STATES)

    assert {"NotifyArchived", "NotifyRestoreStarted", "NotifyRestored"} <= readers
    assert _read_without_the_transfer(STATES) == set()


def test_that_rule_catches_a_route_past_the_builder():
    """**The positive control**, for the stamp rule's reason: an emptiness check passes as
    happily when the walk has stopped finding readers. Routing each arm past its builder has to
    flag every reader downstream of it."""
    mutant = {name: dict(state) for name, state in STATES.items()}
    mutant["InspectSource"] = {**mutant["InspectSource"], "Next": "HasTransferItems"}
    mutant["StampRestoreExecution"] = {
        **mutant["StampRestoreExecution"],
        "Next": "HasRestoreItems",
    }

    flagged = _read_without_the_transfer(mutant)

    assert {"NotifyArchived", "NotifyRestoreStarted", "NotifyRestored"} <= flagged
    assert {"HasTransferItems", "HasRestoreItems"} <= flagged


def _with_a_reshaping_pass(states: dict) -> dict:
    """A Pass that names its own keys, spliced in after delete-source."""
    states["Reshape"] = {
        "Type": "Pass",
        "Parameters": {"requestId.$": "$.requestId"},
        "Next": "WriteReceipt",
    }
    states["DeleteSource"] = {**states["DeleteSource"], "Next": "Reshape"}
    return states


def _without_selecting_the_verbs_return(states: dict) -> dict:
    """write-receipt with its ``OutputPath`` gone, so the state becomes the invoke's envelope."""
    states["WriteReceipt"] = {
        key: value for key, value in states["WriteReceipt"].items() if key != "OutputPath"
    }
    return states


@pytest.mark.parametrize(
    "reshape",
    [_with_a_reshaping_pass, _without_selecting_the_verbs_return],
    ids=["a-pass-naming-its-own-keys", "a-task-that-stops-selecting-its-payload"],
)
def test_that_rule_catches_a_state_that_reshapes_the_object_after_the_builder(reshape):
    """The regressions a sink-only walk misses: the builder ran, and then something between it
    and the notify rebuilt the state without the block — a Pass naming its own keys, or a Task
    that no longer selects its verb's return and so hands on Lambda's response envelope."""
    mutant = reshape({name: dict(state) for name, state in STATES.items()})

    assert "NotifyArchived" in _read_without_the_transfer(mutant)
