"""Invariants that must hold in EVERY control-plane state machine.

These read the deployed ASL templates under infra/ rather than a copy, because the whole
point is to fail when one of them drifts. They are not about any single arc — they encode
rules that were each learned by breaking production.

Runnable under pytest or directly: python3 test_state_machines_cpcommon.py.
"""

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

_INFRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", "modules")
_TEMPLATES = sorted(glob.glob(os.path.join(_INFRA, "*", "state-machine.asl.json.tftpl")))

#: Intrinsics that RAISE rather than degrade when their input is the wrong shape. A Pass
#: state has no Catch, so one of these in a Pass kills the execution outright.
_THROWING_INTRINSICS = ("States.StringToJson", "States.ArrayGetItem", "States.MathAdd")


def _load(path):
    """Parse a .tftpl with its Terraform placeholders stubbed to a literal."""
    with open(path) as handle:
        return json.loads(re.sub(r"\$\{[^}]+\}", "stub", handle.read()))


def _states(asl):
    """Yield (qualified_name, state) for every state, including inside Map/Parallel."""
    def walk(states, prefix=""):
        for name, state in states.items():
            yield prefix + name, state
            for branch in state.get("Branches", []) or []:
                yield from walk(branch["States"], f"{prefix}{name}/")
            for key in ("Iterator", "ItemProcessor"):
                if key in state:
                    yield from walk(state[key]["States"], f"{prefix}{name}/")
    return walk(asl["States"])


def test_there_are_state_machines_to_check():
    """Guards the whole file against passing vacuously if the glob ever stops matching."""
    assert len(_TEMPLATES) >= 3, _TEMPLATES


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_no_pass_state_uses_a_throwing_intrinsic(path):
    """THE BUG THIS EXISTS FOR, and it cost every notification on the failure path.

    All three control planes decoded a Lambda error the same way:

        "cause.$": "States.StringToJson($.error.Cause)"

    in a Pass state. A Pass state cannot Catch, and StringToJson raises States.Runtime
    whenever Cause is absent or is not JSON. Confirmed against the live service with
    TestState: States.Timeout (no Cause), States.DataLimitExceeded and Lambda.Unknown
    (plain-sentence Cause) each killed the execution — BEFORE the recorded-failure and
    notify states. So on exactly the failures a user most needs to hear about, they were
    told nothing at all.

    Worse inside a Map: table-share decoded per recipient, so one recipient with an
    unparseable Cause failed the iteration, which failed the Map, which took down every
    SIBLING recipient too.

    Decode in Python instead — cpcommon.errors.failure_reason handles any shape.
    """
    offenders = [
        f"{name}.{key} = {value}"
        for name, state in _states(_load(path))
        if state.get("Type") == "Pass"
        for key, value in (state.get("Parameters") or {}).items()
        if isinstance(value, str) and any(fn in value for fn in _THROWING_INTRINSICS)
    ]

    assert not offenders, (
        f"{os.path.basename(os.path.dirname(path))}: a Pass state cannot Catch, so a "
        f"throwing intrinsic there kills the execution uncatchably: {offenders}"
    )


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_every_transition_resolves_and_every_state_is_reachable(path):
    """A dangling Next is a deploy-time error; an orphan state is dead code that reads as
    live. Both are cheap to check and neither is visible in a diff."""
    asl = _load(path)

    def check(states, start, scope):
        names = set(states)
        targets = set()
        for name, state in states.items():
            if state.get("Next"):
                targets.add(state["Next"])
            for catch in state.get("Catch", []) or []:
                targets.add(catch["Next"])
            for choice in state.get("Choices", []) or []:
                if choice.get("Next"):
                    targets.add(choice["Next"])
            if state.get("Default"):
                targets.add(state["Default"])
            for key in ("Iterator", "ItemProcessor"):
                if key in state:
                    check(state[key]["States"], state[key]["StartAt"], f"{scope}{name}/")
            for branch in state.get("Branches", []) or []:
                check(branch["States"], branch["StartAt"], f"{scope}{name}/")

        assert not targets - names, f"{scope}: transitions to missing states {sorted(targets - names)}"
        assert not names - targets - {start}, f"{scope}: unreachable states {sorted(names - targets - {start})}"

    check(asl["States"], asl["StartAt"], os.path.basename(os.path.dirname(path)) + ":")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
