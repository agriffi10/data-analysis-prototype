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


def test_the_placeholders_carry_no_result_or_parameters():
    """A bare Pass, and this is not stylistic. Either field would replace or reshape the state and
    destroy ``$.lock`` — so ``ReleaseLock`` would free nothing and every SUCCESSFUL request would
    wedge its space until the lock went stale."""
    for name in ("CopyPlaceholder", "MovePlaceholder", "DeletePlaceholder"):
        assert "Result" not in STATES[name]
        assert "Parameters" not in STATES[name]
        assert STATES[name]["Next"] == "ReleaseLock"


def test_every_choice_comparison_is_guarded_by_IsPresent():
    """A Choice on an absent path raises an uncatchable ``States.Runtime``, and ``Default`` does
    not cover it. Every comparison on this machine pairs its test with a presence check."""
    for name in ("LockAcquired", "ChooseOperation"):
        for choice in STATES[name]["Choices"]:
            guarded = choice.get("IsPresent") is False or any(
                clause.get("IsPresent") is True for clause in choice.get("And", [])
            )

            assert guarded, f"{name} compares an unguarded path: {choice}"
