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

_HERE = os.path.dirname(os.path.abspath(__file__))
_INFRA = os.path.join(_HERE, "..", "..", "infra", "modules")
_TEMPLATES = sorted(glob.glob(os.path.join(_INFRA, "*", "state-machine.asl.json.tftpl")))

#: Intrinsics that RAISE rather than degrade when their input is the wrong shape.
#:
#: They raise ``States.Runtime``, which AWS documents as neither retriable NOR catchable —
#: a ``Catch: ["States.ALL"]`` on the very same Task does not catch it. So one of these
#: anywhere, in ANY state type, kills the execution outright. (An earlier version of this
#: guard checked only ``Pass`` states, on the mistaken belief that "a Pass state cannot
#: Catch" was the mechanism. It is not — the Pass states were merely where the bug
#: happened to live.)
_THROWING_INTRINSICS = ("States.StringToJson", "States.ArrayGetItem", "States.MathAdd")

#: Every control plane whose machine must satisfy the invariants below. Named rather than
#: counted so a renamed or deleted module fails loudly instead of shrinking the sample.
_EXPECTED_ARCS = {"data-quality", "shared-spaces", "table-builder", "table-share"}


def _intrinsics_in(value):
    """Yield every throwing intrinsic anywhere inside a Parameters value.

    Recurses: a Parameters block nests, and an intrinsic one level down
    (``{"outer": {"cause.$": "States.StringToJson(...)"}}``) is exactly as fatal as one at
    the top and exactly as invisible to a flat scan.
    """
    if isinstance(value, str):
        if any(fn in value for fn in _THROWING_INTRINSICS):
            yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _intrinsics_in(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _intrinsics_in(nested)


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


def test_every_expected_state_machine_is_being_checked():
    """Guards the whole file against passing vacuously if the glob stops matching.

    Asserts the NAMES, not a count: a renamed module would keep a count-based check green
    while silently dropping a whole control plane from every invariant below.
    """
    found = {os.path.basename(os.path.dirname(p)) for p in _TEMPLATES}

    assert found == _EXPECTED_ARCS, f"missing {_EXPECTED_ARCS - found}, unexpected {found - _EXPECTED_ARCS}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_no_state_uses_a_throwing_intrinsic(path):
    """THE BUG THIS EXISTS FOR, and it cost the failure path its outcome in all three arcs.

    Every control plane decoded a Lambda error the same way:

        "cause.$": "States.StringToJson($.error.Cause)"

    StringToJson raises States.Runtime whenever Cause is absent or is not JSON, and
    States.Runtime is neither retriable nor catchable — not even by a Catch on the very
    same state. Confirmed against the live service with TestState: States.Timeout (no
    Cause), States.DataLimitExceeded and Lambda.Unknown (plain-sentence Cause) each killed
    the execution BEFORE the recorded-failure state. In data-quality that meant no
    notification at all on exactly the failures a user most needs to hear about; in
    table-share, which decoded per recipient inside a Map, one unparseable Cause failed the
    iteration, which failed the Map, which took down every SIBLING recipient's share.

    CHECKS EVERY STATE TYPE, not just Pass, and recurses into nested Parameters — an
    intrinsic in a Task's Parameters is exactly as fatal and was exactly as unguarded.

    Decode in Python instead: cpcommon.errors.failure_reason handles any shape.
    """
    offenders = [
        f"{name}.{key} = {found}"
        for name, state in _states(_load(path))
        for key, value in (state.get("Parameters") or {}).items()
        for found in _intrinsics_in(value)
    ]

    assert not offenders, (
        f"{os.path.basename(os.path.dirname(path))}: States.Runtime cannot be caught "
        f"anywhere, so a throwing intrinsic kills the execution outright: {offenders}"
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


#: Step Functions' hard cap on a state payload. Breaching it raises
#: States.DataLimitExceeded, which is thrown OUTSIDE every Catch.
_STATE_PAYLOAD_LIMIT = 256 * 1024


def test_the_failure_records_contribution_to_the_map_state_is_bounded():
    """Bounds what THIS PR controls — the failure records — and only that.

    HONEST SCOPE, because an earlier version of this test was not: it measured the results
    array alone, called the answer 26% of the limit, and read as though the Map state were
    safe. It is not. `inspect-source` puts an `objects` array of up to SHARE_MAX_OBJECTS
    entries on the state, the Map's ItemSelector copies the whole state into every item, and
    ResultPath merges the results back into it. Measured at the shipped caps with ordinary
    Hive keys (`year=/month=/day=/hour=/part-…parquet`, ~140 chars):

        results array alone (what this test bounds)      78 KB   30%
        FULL Map state, 1000 objects, 50 recipients     249 KB   95%
        the same with ZERO failures                     187 KB   71%

    So the dominant term is `objects`, it is pre-existing, and no recipient cap can fix it.
    That is being moved to an S3 pointer (the SPEC-110 manifest precedent); the whole-state
    guard belongs with that change, where it can assert something true.

    What IS true here: two constants bound the failure records, and both are load-bearing.
    A count cap alone cannot bound them — at Step Functions' 32 KB Cause ceiling the array
    breaches on its own at SEVEN recipients.
    """
    sys.path.insert(0, os.path.join(_HERE, "..", "table-share-common"))
    from cpcommon import errors
    from tscommon import config as ts_config

    cause = json.dumps({
        "errorMessage": "create_failed: " + ("x" * errors.MAX_DETAIL_CHARS),
        "errorType": "TerminalError",
        "requestId": "0" * 36,
        "stackTrace": ['  File "/var/task/table_share_create_table.py", line 999, in _fn\n    raise\n'] * 8,
    })
    entry = {
        "kind": "space",
        "name": "s" * 64,
        "status": "failed",
        "error": {"Error": "TerminalError", "Cause": cause},
    }
    records = len(json.dumps([entry] * ts_config.SHARE_MAX_RECIPIENTS))

    # A THIRD of the limit for the records alone — deliberately strict, because the rest of
    # the state is large and is not bounded here.
    assert records < _STATE_PAYLOAD_LIMIT // 3, (
        f"failure records reach {records:,} bytes at SHARE_MAX_RECIPIENTS="
        f"{ts_config.SHARE_MAX_RECIPIENTS} x MAX_DETAIL_CHARS={errors.MAX_DETAIL_CHARS}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
