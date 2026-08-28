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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


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
