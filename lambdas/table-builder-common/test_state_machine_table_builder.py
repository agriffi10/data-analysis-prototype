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


def _mode(mode):
    """A threaded state carrying ``mode``, or carrying nothing when it is None."""
    return {} if mode is None else {"mode": mode}


def test_validate_authorize_hands_off_to_the_mode_router():
    states = _states()

    assert states["ValidateAuthorize"]["Next"] == "RouteByMode"
    assert states["RouteByMode"]["Type"] == "Choice"


def test_the_head_choice_routes_a_refresh_to_load_table_definition_and_all_else_to_create():
    states = _states()

    assert _route(states, "RouteByMode", _mode("refresh")) == "LoadTableDefinition"
    assert _route(states, "RouteByMode", _mode("create")) == "CheckTableAbsent"


def test_the_tail_choice_routes_a_refresh_away_from_execute_ddl():
    """A refresh reaches the inspection verbs but CANNOT reach ExecuteDdl — the create
    path's DDL state is not shared, and the refresh tail issues its own statements."""
    states = _states()

    assert states["InferSchema"]["Next"] == "RouteTailByMode"
    assert _route(states, "RouteTailByMode", _mode("refresh")) == "DiffSchema"
    assert _route(states, "RouteTailByMode", _mode("create")) == "ExecuteDdl"


def _changed(value):
    """A threaded state carrying `$.diff.changed`, or carrying no diff at all."""
    return {} if value is None else {"diff": {"changed": value}}


def _route_by_change(states, state):
    choice = states["RouteByChange"]
    for rule in choice["Choices"]:
        present = "changed" in (state.get("diff") or {})
        ok = True
        for conjunct in rule.get("And", [rule]):
            if "IsPresent" in conjunct:
                ok = ok and present is conjunct["IsPresent"]
            else:
                ok = ok and present and state["diff"]["changed"] == conjunct["BooleanEquals"]
        if ok:
            return rule["Next"]
    return choice["Default"]


def test_an_unchanged_schema_reaches_success_without_passing_through_any_ddl_state():
    """FR-002 AC1/AC3. The no-op is the common case once users get the habit, and it must
    not drop the table to discover it has nothing to do."""
    states = _states()

    assert states["DiffSchema"]["Next"] == "RouteByChange"
    assert _route_by_change(states, _changed(False)) == "RecordSuccess"
    assert _route_by_change(states, _changed(True)) != "RecordSuccess"
    # Both outcomes are EXPLICIT rules, so the Default is free to be a failure.
    assert len(states["RouteByChange"]["Choices"]) == 2


def test_an_absent_diff_records_a_failure_instead_of_stranding():
    """The Default is a FAILURE here, unlike the mode Choices, and the difference is the
    point.

    An absent `$.mode` has an obvious correct reading — create. An absent `$.diff.changed`
    means diff-schema returned something this machine cannot interpret, and defaulting THAT
    to RecordSuccess would hand it to a Pass state reading `$.status`, raising the same
    uncatchable States.Runtime one state later with no recorded outcome at all. The
    IsPresent guard alone only moves the failure; recording one is what removes it.
    """
    states = _states()

    assert states["RouteByChange"]["Default"] == "DiffMissingSeed"
    assert _route_by_change(states, _changed(None)) == "DiffMissingSeed"
    assert states["DiffMissingSeed"]["Next"] == "RecordFailure"
    assert states["DiffMissingSeed"]["ResultPath"] == "$.error"


def test_record_success_threads_status_and_every_path_that_reaches_it_sets_one():
    """FR-007. `status` stopped being a literal, so an absent one is now an uncatchable
    States.Runtime raised AFTER the work succeeded. The guard is that every state which can
    reach RecordSuccess sets it — asserted structurally, by walking the graph backwards.
    """
    states = _states()

    assert states["RecordSuccess"]["Parameters"]["status.$"] == "$.status"

    def _targets(state):
        """Every state this one can transition to, by ANY edge type.

        Catch is included deliberately: it is the edge written by hand on every Task, so
        it is the one most likely to gain a target nobody thought of as a predecessor.
        """
        yield state.get("Next")
        yield state.get("Default")
        for choice in state.get("Choices", []) or []:
            yield choice.get("Next")
        for catch in state.get("Catch", []) or []:
            yield catch.get("Next")

    predecessors = {
        name for name, state in states.items() if "RecordSuccess" in set(_targets(state))
    }
    # ExecuteDdl sets "created", ApplyRefresh sets "refreshed", and RouteByChange is fed by
    # DiffSchema, which sets "unchanged" on exactly the branch that reaches here. A new
    # predecessor must set one too.
    assert predecessors == {"ExecuteDdl", "RouteByChange", "ApplyRefresh"}, predecessors


def test_an_absent_mode_reaches_the_create_path_rather_than_killing_the_execution():
    """FR-003 AC2, and the reason each rule is an And with IsPresent rather than a bare
    StringEquals.

    A Choice rule whose Variable path is ABSENT raises States.Runtime — uncatchable, so
    the execution dies with no recorded outcome and no notification. `Default` does not
    cover that: it covers a value that is PRESENT and matches no rule. So the one input
    Default exists for — an envelope from a producer that predates this spec, or a create
    in flight while the infra and Lambda deploys land out of order — is exactly the input
    that would have killed it.
    """
    states = _states()

    assert _route(states, "RouteByMode", _mode(None)) == "CheckTableAbsent"
    assert _route(states, "RouteTailByMode", _mode(None)) == "ExecuteDdl"


def test_both_choices_declare_a_default_at_all():
    """A Choice with no Default raises States.NoChoiceMatched, which also strands the
    execution — a separate failure from the absent-field one above."""
    states = _states()

    assert states["RouteByMode"]["Default"] == "CheckTableAbsent"
    assert states["RouteTailByMode"]["Default"] == "ExecuteDdl"


def test_neither_choice_tests_anything_but_mode():
    """A Choice that grew a second Variable would make the branch depend on state the
    tests below don't model, and both branches share every downstream verb."""

    def _variables(rule):
        return {v for c in rule.get("And", [rule]) for v in [c["Variable"]]}

    for name in ("RouteByMode", "RouteTailByMode"):
        variables = {v for rule in _states()[name]["Choices"] for v in _variables(rule)}

        assert variables == {"$.mode"}, f"{name} tests {variables}"


def test_the_two_branches_rejoin_at_inspect_source_and_run_the_same_spine():
    """FR-003 AC3 — the reason this arc adds no second control plane."""
    states = _states()

    assert states["CheckTableAbsent"]["Next"] == "InspectSource"
    assert states["LoadTableDefinition"]["Next"] == "InspectSource"
    assert states["InspectSource"]["Next"] == "InferSchema"


def test_load_table_definition_carries_the_same_retry_and_catch_contract_as_its_siblings():
    """FR-003 AC5. Compared against a SIBLING rather than a literal, so a fleet-wide change
    to the retry contract cannot leave this one state silently behind."""
    states = _states()
    new, sibling = states["LoadTableDefinition"], states["CheckTableAbsent"]

    assert new["Retry"] == sibling["Retry"]
    assert new["Retry"][0]["ErrorEquals"] == _RETRY_ERRORS
    assert new["Catch"] == [
        {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "RecordFailure"}
    ]
    assert new["OutputPath"] == "$.Payload"


def test_the_stub_is_gone_and_apply_refresh_took_its_place():
    """SPEC-143's not_implemented Pass existed to exercise the branch before it could
    change anything. It is deleted here, not left unreachable — a dead state that once
    meant "safe" is worse than none."""
    states = _states()

    assert "RefreshNotImplemented" not in states
    assert _route_by_change(states, _changed(True)) == "ApplyRefresh"
    assert states["ApplyRefresh"]["Next"] == "RecordSuccess"


def test_apply_refresh_carries_the_same_retry_and_catch_contract_as_its_siblings():
    """Compared against a SIBLING rather than a literal, so a fleet-wide change to the
    retry contract cannot leave the one destructive verb behind."""
    states = _states()
    new_state, sibling = states["ApplyRefresh"], states["ExecuteDdl"]

    assert new_state["Retry"] == sibling["Retry"]
    assert new_state["Retry"][0]["ErrorEquals"] == _RETRY_ERRORS
    assert new_state["Catch"] == [
        {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "RecordFailure"}
    ]


def test_record_success_still_carries_the_mode():
    """`mode` on the record is what lets a reader tell which branch produced an outcome
    without inferring it from `status`."""
    assert _states()["RecordSuccess"]["Parameters"]["mode.$"] == "$.mode"


def test_record_failure_reads_nothing_validate_failure_seed_does_not_seed():
    """THE REAL INVARIANT, stated generally. It replaces an earlier test that simply
    forbade `mode.$` here — a rule whose stated REASON was this one: RecordFailure is
    reachable from ValidateFailureSeed, and a Pass state's JSONPath hard-fails on an ABSENT
    key with an uncatchable States.Runtime. On the failure path that kills the execution
    before the user hears anything, which is the whole class SPEC-152 exists to close.

    SPEC-152 needed `$.mode` on this state so a failed REFRESH does not tell the user their
    CREATE failed, and paid for it the documented way — by seeding `mode` in
    ValidateFailureSeed, exactly as data-quality seeds `location` and `reportKey`. So the
    ban was never the invariant; the seeding was. Asserted as a set difference rather than
    a fixed key list so the next field to be added is checked automatically instead of
    needing this test rewritten a second time.
    """
    states = _states()
    read = {v[2:] for v in states["RecordFailure"]["Parameters"].values() if isinstance(v, str) and v.startswith("$.")}
    seeded = set(states["ValidateFailureSeed"]["Parameters"])
    # The seed writes `error.$` from the whole state ("$"), and nests `space.database`.
    seeded = {k.removesuffix(".$") for k in seeded} | {"space.database"}

    assert not read - seeded, (
        f"RecordFailure reads {sorted(read - seeded)}, which ValidateFailureSeed does not "
        "seed: a pre-identity failure would die on an absent key before it could notify"
    )
    assert "mode" in read, "SPEC-152: without $.mode a failed refresh reads as a failed create"


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


def test_no_state_uses_states_stringtojson_anywhere_in_its_definition():
    """FR-003 AC6, and stronger than the fleet-wide guard, which walks Parameters only.

    Walks the PARSED states, not the raw template: the literal string already appears in
    RecordFailure's Comment (explaining why the decode moved to Python, #252), so a
    string-containment check over the file fails on day one against the shipped machine.
    """
    offenders = [
        f"{name}: {found}"
        for name, state in _states().items()
        for found in _strings(state)
        if "States.StringToJson" in found
    ]

    assert not offenders, f"States.Runtime is uncatchable anywhere: {offenders}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
