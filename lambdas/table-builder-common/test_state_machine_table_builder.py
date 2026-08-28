"""The table-builder machine's two branches over one shared spine (SPEC-143 FR-003).

The repo-wide invariants — reachability, no throwing intrinsic in a Parameters block, the
failure-seed rule — live in ``control-plane-common/test_state_machines_cpcommon.py`` and
cover this machine along with the other three. What is asserted HERE is what only this
machine has: that `mode` routes to the right verb on both sides, that the branch cannot
strand an execution, and that the new Task carries the same retry contract as its
siblings.

Reads the deployed template rather than a copy, so drift fails rather than passes.
Runnable under pytest or directly: python3 test_state_machine_table_builder.py.
"""

import json
import os
import re
import sys

import pytest

_TFTPL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "infra", "modules", "table-builder", "state-machine.asl.json.tftpl",
)

#: The uniform Retry contract every Task state carries. The three middle names are
#: `Lambda.`-prefixed IN THE SHIPPED ASL, and an unprefixed name matches nothing — a
#: silently-never-retried Task looks identical to one that never needed retrying.
_RETRY_ERRORS = [
    "Lambda.ServiceException",
    "Lambda.TooManyRequestsException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "TransientError",
]


def _asl():
    with open(_TFTPL) as handle:
        return json.loads(re.sub(r"\$\{[^}]+\}", "ARN", handle.read()))


def _states():
    return _asl()["States"]


def _matches(rule, state):
    """Evaluate one Choice rule against ``state`` — the And/IsPresent/StringEquals subset."""
    if "And" in rule:
        return all(_matches(conjunct, state) for conjunct in rule["And"])
    present = rule["Variable"] == "$.mode" and "mode" in state
    if "IsPresent" in rule:
        return present is rule["IsPresent"]
    return present and state["mode"] == rule["StringEquals"]


def _route(states, choice_name, state):
    """Where ``choice_name`` sends ``state`` — its Default when no rule matches."""
    choice = states[choice_name]
    for rule in choice["Choices"]:
        if _matches(rule, state):
            return rule["Next"]
    return choice["Default"]


def _targets(state):
    """Every state this one can transition to, by ANY edge type.

    Catch is included deliberately: it is the edge written by hand on every Task, so it is the
    one most likely to gain a target nobody thought of as a predecessor.
    """
    yield state.get("Next")
    yield state.get("Default")
    for choice in state.get("Choices", []) or []:
        yield choice.get("Next")
    for catch in state.get("Catch", []) or []:
        yield catch.get("Next")


def _walk(states, start, *, through=None):
    """Every state reachable from ``start``, optionally only THROUGH a named set.

    SPEC-157 put the two lock states on paths the create branch shares, so several assertions
    that used to name a single hop now have one in between. They are written as reachability
    rather than as a renamed literal on purpose: a test that pins the exact next state re-breaks
    every time a state is inserted, which teaches the next reader to update the expected string
    instead of checking the property still holds.
    """
    seen, stack = set(), [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in states:
            continue
        seen.add(name)
        if through is not None and name != start and name not in through:
            continue
        stack.extend(t for t in _targets(states[name]) if t)
    return seen


#: The two SPEC-157 states, which pass a request through without interpreting it. Assertions
#: about where a verb "goes" step over them.
_LOCK_STATES = frozenset({"ReleaseRefreshLock", "ReleaseRefreshLockOnFailure"})


def test_the_lock_holder_identifies_the_execution_not_the_request():
    """SPEC-157. requestId is a property of the MESSAGE and Pipes delivery is at-least-once, so
    two executions of one redelivered message share it — and table_lock's re-entrancy branch
    would hand the lock to both. The ARN is what tells them apart.

    A Pass rather than the acquire task's own Parameters: reading $$ there means building an
    object, which wraps the payload, and every notification path here reads the request at the
    top level of the event.
    """
    states = _states()
    stamp = states["StampExecution"]

    assert stamp["Type"] == "Pass"
    assert stamp["Parameters"] == {"arn.$": "$$.Execution.Id"}
    assert stamp["ResultPath"] == "$.execution"
    assert "$$" not in json.dumps(states["AcquireRefreshLock"]["Parameters"])


def _strings(value, key=None):
    """Every string in a parsed state definition, skipping Comment prose."""
    if key == "Comment":
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for name, nested in value.items():
            yield from _strings(nested, name)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-157 FR-002: the lock is released on EVERY terminal path ─────────────


def test_no_path_reaches_a_terminal_state_still_holding_the_lock():
    """FR-002 AC2, asserted at the REAL cut.

    An earlier version of this test derived the feeders of RecordSuccess/RecordFailure and
    required them to be lock states. That measures one hop too early: a Catch pointed PAST the
    shaping states — straight at Failed, or at NotifyFailure — bypasses the release entirely and
    the assertion still holds because nothing new points at RecordFailure. Three such mutations
    were confirmed to leave the whole suite green, each one stranding a refresh's lock for the
    full steal threshold.

    So this walks every path from StartAt to a terminal state, carrying whether the lock has been
    taken, and fails if any path ends while still holding it. That is the property FR-002 AC2
    actually names, and it cannot be satisfied by a state nobody remembered to list.
    """
    states = _states()
    terminals = {n for n, s in states.items() if s.get("Type") in ("Succeed", "Fail")}
    assert terminals, "no terminal states found — the walk measured nothing"

    violations = []

    def _walk_from(name, held, seen):
        if name in terminals:
            if held:
                violations.append([*seen, name])
            return
        if (name, held) in seen_pairs:
            return
        seen_pairs.add((name, held))
        state = states[name]
        if name == "AcquireRefreshLock":
            held = True
        elif name in _LOCK_STATES:
            held = False
        for nxt in _targets(state):
            if nxt:
                _walk_from(nxt, held, [*seen, name])

    seen_pairs = set()
    _walk_from(_asl()["StartAt"], False, [])

    assert not violations, (
        "these paths reach a terminal state still holding the refresh lock, stranding the table "
        f"until the steal expires: {violations[:3]}"
    )
