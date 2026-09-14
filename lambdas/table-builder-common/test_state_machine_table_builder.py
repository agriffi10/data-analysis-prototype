"""The table-builder machine's two branches over one shared spine (SPEC-143 FR-003).

The repo-wide invariants — reachability, no throwing intrinsic in a Parameters block, the
failure-seed rule — live in ``control-plane-common/test_state_machines_cpcommon.py`` and
cover this machine along with the other three. What is asserted HERE is what only this
machine has: that `mode` routes to the right verb on both sides, that the branch cannot
strand an execution, and that the new Task carries the same retry contract as its
siblings.

Reads the deployed template rather than a copy, so drift fails rather than passes.
"""

import json
import os
import re

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


# ── The timed-out door, both halves ───────────────────────────────────────────

_STEPFUNCTION_TF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "infra", "modules", "table-builder", "stepfunction.tf",
)
_DOOR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "table-builder-notify-failure", "tb_notify_failure.py",
)


def test_the_timeout_rule_exists_and_matches_timed_out_and_never_failed():
    """The rule this plane shipped WITHOUT for two years, and the reason it must stay narrow.

    A top-level TimeoutSeconds expiry is not an ASL path, so no Catch covers it and EventBridge is
    the only route to a notification — which is why its absence was invisible to every other test
    here. FAILED must stay out of the pattern: every whole-request failure the shared Catch takes
    already reaches NotifyFailure, so matching it would double-notify all of them.
    """
    with open(_STEPFUNCTION_TF, encoding="utf-8") as handle:
        text = handle.read()

    assert "aws_cloudwatch_event_rule" in text, "the plane has a ceiling and needs the door"
    assert 'status          = ["TIMED_OUT"]' in text
    pattern = text.split("event_pattern")[1].split("})")[0]
    assert "FAILED" not in pattern, "FAILED would double-notify every caught failure"
    assert "aws_lambda_permission" in text, "the rule needs the resource-based invoke grant"


def test_the_rule_is_only_half_the_door():
    """The rule alone deploys green and still notifies nobody.

    An EventBridge status-change event carries no top-level `actor`, so a handler without the
    detail-type dispatch takes its no-actor branch and returns — indistinguishable from the gap the
    rule was added to close. This asserts the other half exists beside it.
    """
    import ast

    with open(_DOOR, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)

    assigned = {
        t.id: n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    assert assigned.get("_TIMEOUT_DETAIL_TYPE") == "Step Functions Execution Status Change", (
        "the dispatch key must be the literal EventBridge sends, not merely mentioned in a docstring"
    )

    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert "_is_execution_timeout" in called, "the handler must dispatch, not just define the door"
    assert "trusted_actor" in called, "the actor must come from the identity block, not the body"


def test_the_door_reads_the_event_and_never_describes_the_execution():
    """This plane's inputs cannot approach EventBridge's cap, so it takes no DescribeExecution
    grant — and the door must not reach for the shared helper that falls back to one.

    Asserted on the CALLS rather than on the text. A substring sweep for the helper's name is
    satisfied by the docstring that explains why the door does not use it, so the first version of
    this test failed on its own subject's documentation — and would equally have passed a file that
    named the helper in a comment while calling it on the line below.
    """
    import ast

    with open(_DOOR, encoding="utf-8") as handle:
        source = handle.read()

    called = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)

    assert "timed_out_execution_input" not in called, "the fallback needs a grant this plane lacks"
    assert "describe_execution" not in called
    assert 'detail.get("input")' in source, "the door reads the event's own input directly"
