"""This plane's own walk of its state machine.

The fleet-wide guards check what every machine must satisfy. They cannot check the two properties
that are specific to this one, and both are properties whose failure is silent:

  - **no reachable terminal skips the lock release**, and the one path that legitimately does is
    asserted as a NAMED exception rather than quietly uncovered;
  - **the waiting loop cannot spin**, because a Choice that falls through to its Default on an
    output that lost its shape would re-enter the Wait until the machine's own ceiling.

The fleet's seed guard is also structurally blind here: it identifies a failure seed by
``Parameters["error.$"] == "$"``, which matches only the pre-identity one, so a post-identity seed
reading a key nothing supplies would pass it.
"""

import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from focommon import config

MODULE = pathlib.Path(__file__).resolve().parents[2] / "infra" / "modules" / "file-ops"
TEMPLATE = MODULE / "state-machine.asl.json.tftpl"

#: Every state that frees the lock. Three, because one ASL state has one ``Next`` and the success
#: path, the give-up and the failure path each need their own.
RELEASE_STATES = {"ReleaseLock", "ReleaseLockOnGiveUp", "ReleaseLockOnFailure"}


def _machine() -> dict:
    """Parses the rendered ASL, substituting the template's placeholders.

    Args:
      None.

    Returns:
      The state machine definition.

    Raises:
      None.
    """
    return json.loads(re.sub(r"\$\{[^}]+\}", "1", TEMPLATE.read_text()))


STATES = _machine()["States"]


def _successors(name: str) -> set:
    """Returns every state one state can transition to, by any route.

    Args:
      name: The state's name.

    Returns:
      The set of reachable next states.

    Raises:
      None.
    """
    state = STATES[name]
    nexts = set()
    if state.get("Next"):
        nexts.add(state["Next"])
    if state.get("Default"):
        nexts.add(state["Default"])
    for choice in state.get("Choices", []):
        nexts.add(choice["Next"])
    for catch in state.get("Catch", []):
        nexts.add(catch["Next"])
    return nexts


def _paths_to_terminals() -> list:
    """Walks every route from the start state to a terminal.

    Cycles are broken by refusing to revisit a state on the same path, which is what makes the
    waiting loop walkable at all.

    Args:
      None.

    Returns:
      A list of state-name paths, each ending at a Succeed or a Fail.

    Raises:
      None.
    """
    paths, frontier = [], [["ValidateAuthorize"]]
    while frontier:
        path = frontier.pop()
        state = STATES[path[-1]]
        if state["Type"] in ("Succeed", "Fail"):
            paths.append(path)
            continue
        for nxt in _successors(path[-1]):
            if nxt not in path:
                frontier.append([*path, nxt])
    return paths


def test_the_walk_actually_walked_something():
    """Guard-the-guard: every assertion below is over the walk's output, so a walk that produced
    nothing would make the whole file pass while checking no machine at all."""
    paths = _paths_to_terminals()

    assert len(paths) > 5
    assert any(path[-1] == "Succeeded" for path in paths)
    assert any(path[-1] == "Failed" for path in paths)


def test_no_path_that_takes_the_lock_reaches_a_terminal_without_releasing_it():
    """The property the plane turns on, and one no fleet guard can express.

    A wedged lock is not a failed request — it is a SPACE in which nobody can copy, move or delete
    anything until the staleness rule recovers it, which is hours. Every route that gets past the
    acquire has to pass through one of the three release states.
    """
    for path in _paths_to_terminals():
        if "AcquireLock" not in path:
            continue

        assert RELEASE_STATES & set(path), f"this path takes the lock and never frees it: {path}"


def test_the_paths_that_do_NOT_release_are_the_ones_that_never_took_the_lock():
    """The complement, so the rule above cannot be satisfied by a machine that releases
    everywhere and means nothing by it."""
    for path in _paths_to_terminals():
        if RELEASE_STATES & set(path):
            continue

        assert "AcquireLock" not in path, f"this path holds a lock at a terminal: {path}"


def test_the_timeout_expiry_is_a_NAMED_exception_rather_than_silently_uncovered():
    """A top-level ``TimeoutSeconds`` expiry terminates the execution outright: no state runs, no
    Catch fires, and so no release happens. That is unavoidable and it is not a hole — the stale
    steal is the recovery — but a walk that simply never considered it would look identical to one
    that had.

    The door exists, it listens for TIMED_OUT alone, and it deliberately does NOT release: by the
    time it fires the lock may already have been stolen, and releasing would clobber the new
    holder.
    """
    stepfunction = (MODULE / "stepfunction.tf").read_text()

    # A TOP-LEVEL field, not a task field: without it a Standard workflow's ceiling is Step
    # Functions' own default of ONE YEAR. Asserted against locals.tf rather than the rendered
    # template, because the template carries a placeholder here — and the mirror is the property
    # that matters: the steal threshold and the give-up bound are both derived from this number,
    # so a Terraform value that drifted from the Python one would make both meaningless while
    # every test still passed.
    assert "TimeoutSeconds" in _machine()
    assert (
        f"state_machine_timeout_seconds = {config.MACHINE_TIMEOUT_SECONDS}"
        in (MODULE / "locals.tf").read_text()
    )
    assert 'status          = ["TIMED_OUT"]' in stepfunction
    assert '"FAILED"' not in stepfunction, (
        "matching FAILED would send a second notification for every failure a Catch already caught"
    )
    door = stepfunction[stepfunction.index("aws_cloudwatch_event_target"):]

    assert "release" not in door.lower()


def test_no_Pass_state_reads_a_field_a_DELETE_request_does_not_carry():
    """The hazard that would have killed the very first delete, closed structurally.

    ``destination``, ``onConflict`` and ``submittedAt`` are REJECTED for a delete, so they are
    absent from its request — and a Pass reading an absent path raises ``States.Runtime``, which is
    neither retriable nor catchable. The execution would die before ``NotifyFailure`` and the user
    would be told nothing at all, on one of the plane's three operations.

    The neighbouring planes rebuild the whole state in a ``Validated`` Pass to cross-check the
    verb's return shape. That is safe for them because every field they name is unconditional; it
    is not safe here, so this machine has no such state and ``StampExecution`` MERGES the execution
    ARN with ``ResultPath`` instead of rebuilding — reading only ``$$.Execution.Id``, which is
    always present.

    Asserted as a rule over every Pass rather than about one state, because the next person to add
    a Pass will reach for the pattern the other planes use.
    """
    optional = {"destination", "onConflict", "submittedAt"}

    for name, state in STATES.items():
        if state["Type"] != "Pass":
            continue
        read = set(re.findall(r'"\$\.(\w+)', json.dumps(state.get("Parameters", {}))))

        assert not (read & optional), (
            f"{name} reads {sorted(read & optional)}, which a delete request does not carry — "
            f"an absent path in a Pass raises an uncatchable States.Runtime"
        )


@pytest.mark.parametrize(
    "state",
    [
        "ValidateAuthorize",
        "AcquireLock",
        "InspectSource",
        "CheckDestinations",
        "ReleaseLock",
        "ReleaseLockOnGiveUp",
        "ReleaseLockOnFailure",
        "NotifyFailure",
        "NotifyOutcomes",
    ],
)
def test_every_task_retries_a_transient_lambda_fault(state):
    """A Catch is what stops a failed release failing the request; a RETRY is what makes the
    release actually happen.

    One ``Lambda.TooManyRequestsException`` on a release would otherwise route straight to the
    terminal with the lock still held, and the only recovery is the stale steal — over three hours
    during which nobody can copy, move or delete anything in that space. The same throttle on
    ``NotifyFailure`` costs the user the one message the failure path exists to send.
    """
    retries = STATES[state].get("Retry", [])

    assert retries, f"{state} has no Retry"
    assert "Lambda.TooManyRequestsException" in retries[0]["ErrorEquals"]


# ── The waiting loop ─────────────────────────────────────────────────────────


def test_the_loop_fails_closed_on_an_output_that_lost_its_shape():
    """The one failure mode a loop has that a linear machine does not.

    With only the two positive clauses, an acquire output missing its lock record satisfies
    neither, falls to the Default, and re-enters the Wait — every thirty seconds until the
    machine's ceiling, ending as a bare timeout with the lock still held.
    """
    choice = STATES["LockAcquired"]
    fail_closed = [
        c for c in choice["Choices"] if c.get("IsPresent") is False and c["Next"] in RELEASE_STATES
    ]

    assert fail_closed, "LockAcquired has no clause for an output that lost its shape"
    assert choice["Default"] == "WaitForLock"


def test_the_loop_waits_the_interval_the_code_believes_it_waits():
    """ASL cannot import Python, so the interval has two homes. A test is the only thing holding
    them equal, and the give-up bound is computed from the one in Python."""
    assert f"lock_wait_seconds = {config.LOCK_WAIT_SECONDS}" in (MODULE / "locals.tf").read_text()
    assert STATES["WaitForLock"]["Next"] == "AcquireLock"


def test_the_attempt_counter_uses_no_arithmetic_intrinsic():
    """``States.MathAdd`` raises ``States.Runtime``, which is neither retriable nor catchable — so
    one anywhere kills the execution outright. The verb returns the incremented count instead."""
    assert "States.MathAdd" not in TEMPLATE.read_text()


# ── The failure seeds ────────────────────────────────────────────────────────


def test_every_seed_supplies_every_key_the_failure_terminal_reads():
    """The fleet's version of this identifies a seed by ``error.$ == "$"`` and so sees only the
    pre-identity one. This plane has three, and a post-identity seed missing a key raises an
    uncatchable error on exactly the path that exists to report a failure.
    """
    reads = set(re.findall(r'"(\w+)\.\$": "\$\.(\w+)"', json.dumps(STATES["RecordFailure"])))
    required = {source for _, source in reads}

    for seed in ("ValidateFailureSeed", "RequestFailureSeed", "GiveUpFailureSeed"):
        supplied = {key.removesuffix(".$") for key in STATES[seed]["Parameters"]}

        assert required <= supplied, f"{seed} does not supply {sorted(required - supplied)}"


def test_the_post_identity_seeds_take_the_verified_actor_rather_than_a_token():
    """Two byte-identical seeds would satisfy "a second seed exists" while delivering nothing. The
    difference is the point: after validate-authorize the verified username is already on the
    state, and recovering it from a token again is both slower and a second place to get it wrong.
    """
    for seed in ("RequestFailureSeed", "GiveUpFailureSeed"):
        assert STATES[seed]["Parameters"]["actor.$"] == "$.actor"

    assert STATES["ValidateFailureSeed"]["Parameters"]["actor"] is None


def test_the_pre_identity_seed_reads_the_raw_event_from_the_context_object():
    """The catch on validate-authorize receives the Pipe's JSON ARRAY and has no object to merge
    into, so the request can only come from the execution input."""
    assert STATES["ValidateFailureSeed"]["Parameters"]["raw.$"] == "$$.Execution.Input"


def test_the_unknown_operation_default_MERGES_its_error_instead_of_rebuilding_the_state():
    """It is the one seed reached while the lock is still HELD. A Pass that rebuilt the state with
    ``Parameters`` would drop ``$.lock``, and the release below it would then free nothing while
    reporting success — a wedged space from the path that exists to handle a malformed request.
    """
    seed = STATES["UnknownOperationSeed"]

    assert "Parameters" not in seed
    assert seed["ResultPath"] == "$.error"
    assert seed["Next"] in RELEASE_STATES


@pytest.mark.parametrize("state", sorted(RELEASE_STATES))
def test_a_release_never_fails_the_request_and_never_clobbers_the_real_error(state):
    """A request that did its work and then reported failure because of its own bookkeeping would
    be a worse outcome than a lock the staleness rule recovers anyway.

    ``ResultPath: null`` on the Catch as well as the state is the half that is easy to miss: the
    state already carries ``$.error`` from the upstream catch on the failure path, and a
    release-catch writing there would replace the real failure with a bookkeeping one.
    """
    release = STATES[state]

    assert release["ResultPath"] is None
    for catch in release["Catch"]:
        assert catch["ResultPath"] is None


def test_every_task_taken_under_the_lock_can_reach_a_terminal_at_all():
    """The hole the release walk above is structurally blind to.

    ``_successors`` reads ``Next``, ``Default``, ``Choices`` and ``Catch``. A Task with no ``Catch``
    therefore has NO EDGE to a terminal on its failing path — so the walk never visits it, "no path
    reaches a terminal holding the lock" stays true, and a fault in that verb wedges the space until
    the stale steal over three hours later. Every Task taken while the lock is held must carry a
    catch, and the two that decide what an operation will do are exactly where forgetting one is
    invisible.
    """
    # NotifyOutcomes is excluded for a reason worth writing down rather than inferring: it runs
    # AFTER the release, so it holds no lock — and a catch of its own into a release state would
    # be actively wrong, because a release is an OVERWRITE rather than a compare-and-set on the
    # holder, and by then a different execution may hold that space.
    under_lock = [
        name
        for name, state in STATES.items()
        if state["Type"] == "Task"
        and name not in ("ValidateAuthorize", "NotifyFailure", "NotifyOutcomes")
    ]

    assert "InspectSource" in under_lock and "CheckDestinations" in under_lock
    for name in under_lock:
        catches = STATES[name].get("Catch", [])

        assert catches, (
            f"{name} runs under the lock and has no Catch — a fault there wedges the space"
        )
        if name in RELEASE_STATES:
            continue
        caught = {catch["Next"] for catch in catches}

        assert caught <= RELEASE_STATES, f"{name}'s catch reaches {sorted(caught)}, none of which frees the lock"


def test_the_two_planning_verbs_merge_their_error_rather_than_replacing_the_state():
    """``ResultPath: "$.error"`` on the catch, like ``AcquireLock``'s. Without it the caught error
    REPLACES the running object, so the release below it frees nothing — it has no ``$.lock`` left
    to read — and the failure seed has no ``requestId`` or ``actor`` to name either."""
    for name in ("InspectSource", "CheckDestinations"):
        for catch in STATES[name]["Catch"]:
            assert catch["ResultPath"] == "$.error", f"{name}'s catch replaces the whole state"


def test_the_delete_branch_routes_PAST_the_destination_guard_on_the_operation():
    """A delete has no destination to check, and the obvious guard is the wrong one.

    validate-authorize normalises the copy/move-only fields to explicit NULLS for a delete, and
    ASL's ``IsPresent`` is TRUE for a field that is present and null — so a Choice on
    ``$.destination`` would route every delete into a destination check it has no destination for.
    Branching on the operation is what the rest of this machine already does.

    The Default is the GUARD rather than the skip, so an operation that lost its shape reaches a
    verb that refuses it rather than one that writes.
    """
    choice = STATES["NeedsDestinationGuard"]
    routes = {clause["Next"] for clause in choice["Choices"]}

    assert routes == {"BuildTransferManifest"}
    assert all(
        clause["And"][1]["Variable"] == "$.operation" for clause in choice["Choices"]
    ), "the branch past the guard reads a field a delete does not carry"
    assert choice["Default"] == "SeedFirstGuardPass"
    assert STATES["SeedFirstGuardPass"]["Next"] == "CheckDestinations", (
        "the Default no longer reaches the guard, so an operation that lost its shape skips it"
    )


def test_every_choice_comparison_is_guarded_by_IsPresent():
    """A Choice on an absent path raises an uncatchable ``States.Runtime``, and ``Default`` does
    not cover it. Every comparison on this machine pairs its test with a presence check.

    A rule over every Choice rather than a named pair, because the next branch added is the one that
    will not be in the list.
    """
    choices = [name for name, state in STATES.items() if state["Type"] == "Choice"]

    assert len(choices) >= 3, "this rule stopped seeing the machine's branches"
    for name in choices:
        for choice in STATES[name]["Choices"]:
            guarded = choice.get("IsPresent") is False or any(
                clause.get("IsPresent") is True for clause in choice.get("And", [])
            )

            assert guarded, f"{name} compares an unguarded path: {choice}"


# ── The commit gate, and the ONE property its graph can actually prove ────────────────────


def _reaches(start: str, target: str) -> bool:
    """Reports whether any path from one state can arrive at another.

    Args:
      start: The state to walk from.
      target: The state to look for.

    Returns:
        True when target is reachable.

    Raises:
      None.
    """
    seen, stack = set(), [start]
    while stack:
        name = stack.pop()
        if name == target:
            return True
        if name in seen or name not in STATES:
            continue
        seen.add(name)
        stack.extend(_successors(name))
    return False


def test_an_EMPTY_deletable_set_cannot_reach_the_deletion():
    """The ONE property this walk asserts, and the spec says so in as many words.

    SPEC-169's gate was one boolean over the whole run and its guarantee was graph-level: the
    rollback arm could not REACH the delete. A per-item plane produces runs that are simultaneously
    committing and non-committing, and Step Functions has no per-item ``Choice`` over a list — so
    that guarantee is not available here and this test deliberately claims less.

    **It does NOT assert the per-item property.** "An item with one failed object is not deleted"
    is a collector unit test with a named mutation, plus the subset assertion in delete-source, at
    two layers. A walk claiming more than it proves is worse than one claiming less.
    """
    gate = STATES["HasDeletableItems"]
    positive = [choice["Next"] for choice in gate["Choices"]]

    assert positive == ["DeleteSource"], "the gate's only positive arm is no longer the deletion"
    assert not _reaches(gate["Default"], "DeleteSource"), (
        "an empty deletable set can reach DeleteSource"
    )


def test_the_gate_is_a_COUNT_guarded_by_IsPresent_rather_than_an_array_probe():
    """A bare ``$.deletable[0]`` IsPresent is a construct nothing in this repo uses and one the
    fleet's own Choice rule does not accept. The count is the shape ``HasTransferItems`` uses one
    state earlier, and it is also what keeps the key list off the state entirely."""
    clause = STATES["HasDeletableItems"]["Choices"][0]["And"]

    assert {"Variable": "$.deletableCount", "IsPresent": True} in clause
    assert {"Variable": "$.deletableCount", "NumericGreaterThan": 0} in clause


def test_a_copy_can_never_reach_a_state_that_DELETES():
    """This one IS a whole-request property, so the graph really does prove it.

    A copy is additive by nature; there is nothing to remove and no path that could. Asserted from
    the operation gate rather than by reading the verb, because the verb is not what decides it.
    """
    gate = STATES["NeedsSourceDeletion"]
    operations = {
        clause["StringEquals"]
        for choice in gate["Choices"]
        for clause in choice["And"]
        if "StringEquals" in clause
    }

    assert operations == {"move", "delete"}, "the deleting operations are no longer enumerated"
    assert not _reaches(gate["Default"], "DeleteSource")


def _successors_closure(start: str) -> set:
    """Returns every state reachable from one, itself excluded unless it is part of a cycle.

    Args:
      start: The state to walk from.

    Returns:
      The reachable state names.

    Raises:
      None.
    """
    seen, stack = set(), list(_successors(start))
    while stack:
        name = stack.pop()
        if name in seen or name not in STATES:
            continue
        seen.add(name)
        stack.extend(_successors(name))
    return seen


def test_no_gate_between_the_copy_and_the_deletion_DEFAULTS_into_deleting():
    """The fail-closed rule, scoped to the gates that actually decide whether a source is removed.

    A ``Default`` is where a state that lost its shape ends up — an ``operation`` that went missing,
    a verb that stopped echoing a field, a future ``Parameters`` edit. Every neighbouring gate on
    this fleet defaults to the safe side, and a machine that deletes user data with versioning off
    is the last place to make the exception.

    **Scoped rather than fleet-wide, and the scope is the honest part.** ``LockAcquired``'s Default
    is the wait loop, which re-enters the machine from the top and therefore "reaches" everything —
    that is the loop working, not a fail-open path. The gates this rule is about are the ones AFTER
    the copy, and the set is asserted so a new one cannot be added outside it.
    """
    deciding = {
        name
        for name in _successors_closure("CollectTransferResults")
        if STATES.get(name, {}).get("Type") == "Choice"
    }

    assert deciding == {"NeedsSourceDeletion", "HasDeletableItems"}, (
        f"the gates between the copy and the deletion are now {sorted(deciding)}; a new one has to "
        "be held to this rule too"
    )
    for name in deciding:
        assert not _reaches(STATES[name]["Default"], "DeleteSource"), (
            f"{name}'s Default can reach DeleteSource, so a state that lost its shape deletes"
        )


def test_the_transfer_Map_is_declared_at_the_TOP_level():
    """A Distributed Map nested inside another Map is a different service limit and a different
    failure mode. This plane has exactly one Map and it is top-level."""
    maps = [name for name, state in STATES.items() if state.get("Type") == "Map"]

    assert maps == ["TransferObjects"]
    processor = STATES["TransferObjects"]["ItemProcessor"]
    assert processor["ProcessorConfig"]["Mode"] == "DISTRIBUTED"
    for state in processor["States"].values():
        assert state.get("Type") != "Map", "a Distributed Map is nested inside another Map"


def test_the_Map_is_skipped_by_an_IsPresent_guarded_numeric_test():
    """``IsPresent`` BEFORE the numeric comparison: a numeric test against an absent path raises,
    and it would raise on exactly the runs where nothing was cleared to copy."""
    clause = STATES["HasTransferItems"]["Choices"][0]["And"]

    assert clause[0] == {"Variable": "$.transfer.itemCount", "IsPresent": True}
    assert clause[1] == {"Variable": "$.transfer.itemCount", "NumericGreaterThan": 0}
    assert STATES["HasTransferItems"]["Default"] == "CollectTransferResults", (
        "a run with nothing to copy must still reach the collector — for a delete that IS the run"
    )


def test_the_second_guard_pass_runs_BEFORE_the_manifest_is_written():
    """So a newly conflicted item never contributes a line. Ordering is the whole value of the
    second pass: run after the manifest, it would refuse an item whose objects were already listed
    for the copy."""
    assert STATES["CheckDestinations"]["Next"] == "SeedSecondGuardPass"
    assert STATES["SeedSecondGuardPass"]["Next"] == "CheckDestinationsAgain"
    assert STATES["CheckDestinationsAgain"]["Next"] == "BuildTransferManifest"


def test_the_guard_pass_is_seeded_by_a_Pass_rather_than_merged_beside_the_payload():
    """Merging a literal into ``Parameters`` next to ``Payload.$: "$"`` is the wrapping trap this
    fleet has already paid for once: it puts the request one level below where every notify path
    reads it. A ``Pass`` with ``ResultPath`` merges without reshaping."""
    for name, value in (("SeedFirstGuardPass", 1), ("SeedSecondGuardPass", 2)):
        state = STATES[name]
        assert state["Type"] == "Pass"
        assert state["Result"] == value
        assert state["ResultPath"] == "$.guardPass"
        assert "Parameters" not in state

    for name in ("CheckDestinations", "CheckDestinationsAgain"):
        assert STATES[name]["Parameters"] == {
            "FunctionName": STATES[name]["Parameters"]["FunctionName"],
            "Payload.$": "$",
        }


def test_a_delete_skips_BOTH_guard_passes():
    """A delete has no destination to guard. Skipped whole by the same ``IsPresent``-guarded Choice
    that skipped the first pass before this spec existed."""
    gate = STATES["NeedsDestinationGuard"]
    delete_branch = next(
        choice["Next"]
        for choice in gate["Choices"]
        if any(c.get("StringEquals") == "delete" for c in choice["And"])
    )

    assert delete_branch == "BuildTransferManifest"
    assert not _reaches(delete_branch, "CheckDestinations")
    assert not _reaches(delete_branch, "CheckDestinationsAgain")


def test_the_lock_is_released_BEFORE_anything_that_would_notify():
    """FR-000's ordering. The producer is inserted after ``ReleaseLock`` — before it, the space
    would be held for the whole time the messages take to write."""
    assert STATES["FinaliseOutcomes"]["Next"] == "ReleaseLock"
    assert STATES["ReleaseLock"]["Next"] == "NotifyOutcomes"
    assert STATES["NotifyOutcomes"]["Next"] == "Succeeded"


def test_BOTH_of_the_releases_edges_reach_the_producer():
    """The half that is easy to miss, and it costs the user the whole message.

    ``ReleaseLock`` carries a ``Catch`` so that a failed release cannot fail a request that did its
    work. Routed to the terminal, that catch skips the producer — so a release whose ``Retry`` is
    exhausted by one throttle completes the operation and tells the user NOTHING, while a browser
    waiting on that message to settle its in-flight record holds the space's submit gate until the
    machine's own ceiling. The lock is already free either way, so this costs nothing.
    """
    caught = {catch["Next"] for catch in STATES["ReleaseLock"]["Catch"]}

    assert caught == {"NotifyOutcomes"}, f"a failed release skips the producer and reaches {caught}"


def test_the_producer_cannot_fail_the_run_or_replace_its_output():
    """By the time it runs, a ``move`` has already deleted its sources.

    So the state may neither fail the execution nor rewrite what the finaliser shaped: ``ResultPath:
    null`` on the state AND on its catch, and a catch that leads to the terminal rather than to a
    release — the lock is free, and releasing again would clobber whichever execution has since
    acquired it.
    """
    producer = STATES["NotifyOutcomes"]

    assert producer["ResultPath"] is None
    assert {catch["Next"] for catch in producer["Catch"]} == {"Succeeded"}
    for catch in producer["Catch"]:
        assert catch["ResultPath"] is None
    assert not (RELEASE_STATES & set(_successors("NotifyOutcomes")))


def test_the_wait_loop_still_has_the_shape_SPEC_187_gave_it():
    """Unchanged by this spec, and pinned so that adding six states around it cannot quietly move
    it. The loop is reachable ONLY from the Choice's Default — any other edge into the Wait would be
    a second way to spin."""
    assert STATES["WaitForLock"]["Next"] == "AcquireLock"
    assert STATES["LockAcquired"]["Default"] == "WaitForLock"

    into_the_wait = {
        name for name in STATES if "WaitForLock" in _successors(name) and name != "LockAcquired"
    }
    assert not into_the_wait, f"{into_the_wait} can also enter the wait loop"


def test_no_per_item_outcome_code_can_seed_a_WHOLE_REQUEST_failure():
    """FR-008's rule, enforced rather than stated: a whole-request terminal is reachable only from a
    cause that is a property of the REQUEST, never of an item.

    Deliberately NOT an enumeration of the causes — they are spread across three specs and a list
    would be wrong the day someone adds the next one. What is asserted instead is the direction: no
    member of the per-item vocabulary appears as the ``Error`` on any failure seed.
    """
    from focommon import outcomes

    seeds = {name: state for name, state in STATES.items() if name.endswith("Seed")}

    assert len(seeds) == 4, (
        f"the failure seeds are now {sorted(seeds)}; this rule has to cover every one of them"
    )
    for name, state in seeds.items():
        # A seed carries its error under Result (merged with ResultPath) OR under Parameters
        # (rebuilt). Selecting only one shape reads as a fleet-wide rule while covering a quarter
        # of it — which is what this test did until a reviewer counted them.
        carried = state.get("Result") if isinstance(state.get("Result"), dict) else {}
        parameters = state.get("Parameters") if isinstance(state.get("Parameters"), dict) else {}
        literal = carried.get("Error") or (parameters.get("error") or {}).get("Error")
        assert literal is None or literal not in outcomes.MEMBERS, (
            f"{name} uses the per-item outcome {literal!r} as a whole-request failure reason"
        )


def test_the_terminal_path_walk_has_not_become_the_slow_one():
    """Six new states each carrying a Catch multiply the simple-path count this suite walks. Pinned
    so the growth is visible in a review rather than felt as a slow build."""
    paths = _paths_to_terminals()

    assert len(paths) < 400, f"the walk now enumerates {len(paths)} paths"
