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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)


MODULE = pathlib.Path(__file__).resolve().parents[2] / "infra" / "planes" / "file-ops"
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


# ── The failure seeds ────────────────────────────────────────────────────────


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
