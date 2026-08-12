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

_ASL = os.path.join(_HERE, "..", "..", "infra", "modules", "archive", "state-machine.asl.json.tftpl")


def _load():
    raw = pathlib.Path(_ASL).read_text()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))


ASL = _load()
STATES = ASL["States"]


# ── The mode branch, and the trap it is guarded against ──────────────────────


def test_the_mode_branch_guards_every_comparison_with_IsPresent():
    """SPEC-143's recorded trap, and the reason this is a test rather than a comment: a Choice
    comparing a string on an ABSENT path raises States.Runtime, which is neither retriable nor
    catchable, and `Default` does NOT cover it. The execution dies outright before any state
    can record or notify — on a malformed request, which is exactly what SPEC-152 exists to
    report on.

    Asserted per choice rather than "an IsPresent appears somewhere": one guarded arm and one
    unguarded arm reads as correct and is not.
    """
    for choice in STATES["ChooseMode"]["Choices"]:
        clauses = choice.get("And") or [choice]
        guarded = {c["Variable"] for c in clauses if c.get("IsPresent") is True}
        compared = {c["Variable"] for c in clauses if "StringEquals" in c}

        assert compared and compared <= guarded, (
            f"ChooseMode compares {sorted(compared - guarded)} without an IsPresent guard on "
            "the same path — an absent path raises an uncatchable States.Runtime"
        )


def test_the_mode_branch_has_a_default_that_reaches_the_failure_terminal():
    """A Default pointed at Succeeded would turn an unrecognised mode into a silent no-op:
    the user's archive simply never happens and nothing is ever said about it."""
    seen, frontier = set(), [STATES["ChooseMode"]["Default"]]
    while frontier:
        name = frontier.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        state = STATES[name]
        frontier.append(state.get("Next"))
        frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])

    assert "NotifyFailure" in seen and "Failed" in seen


def test_the_default_arm_seeds_a_reason_code_and_never_a_verbs_error_name():
    """notify-failure treats `TerminalError` as positive evidence that a verb's decorator
    already sent a message, so a seed wearing that name would be silently suppressed and the
    user told nothing (the recorded DiffMissingSeed rule). It must be a registered reason code
    instead, or the sentence degrades to the generic fallback."""
    from arcommon.messages import _BODIES

    seeded = STATES["UnknownModeSeed"]["Parameters"]["error"]

    assert seeded["Error"] != "TerminalError"
    assert seeded["Error"] in _BODIES


def test_both_modes_have_a_target_so_the_branch_is_a_real_branch():
    targets = {
        c["And"][1]["StringEquals"]: c["Next"] for c in STATES["ChooseMode"]["Choices"]
    }

    assert set(targets) == {"archive", "restore"}
    assert targets["archive"] != targets["restore"]


# ── The ASL/verb cross-check ─────────────────────────────────────────────────


def test_the_validated_pass_names_exactly_what_the_verb_returns():
    """THE POINT OF THE Validated STATE. A Task hands its output on whole, so nothing in a
    Task-to-Task chain would notice validate-authorize renaming a field — the rename would
    surface later as a JSONPath failure in a state nobody was looking at. A Pass naming each
    key fails HERE instead."""
    import archive_validate_authorize as verb

    source = pathlib.Path(verb.__file__).read_text()
    emitted = source[source.index("    validated = {"):]
    returned = set(re.findall(r'^\s{8}"([A-Za-z]+)":', emitted, re.MULTILINE))

    declared = {name.removesuffix(".$") for name in STATES["Validated"]["Parameters"]}

    assert declared == returned, (
        f"the machine reads {sorted(declared)} but the verb returns {sorted(returned)}"
    )


def test_the_validated_pass_carries_no_placeholder_status_literal():
    """A placeholder marker that outlives its placeholder is how a field nothing reads
    survives into production (file-send's recorded lesson, which shipped a `status` literal
    for two specs)."""
    assert "status" not in STATES["Validated"]["Parameters"]


# ── What this machine deliberately does NOT have yet ─────────────────────────


def test_the_machine_has_no_top_level_timeout_and_nothing_in_it_waits():
    """The absence is deliberate and is only correct while the second half holds. A
    TimeoutSeconds does NOT on its own reach NotifyFailure — AWS catchers cover Task, Parallel
    and Map states but not top-level execution failures — so it must ship WITH an EventBridge
    TIMED_OUT rule or it is SPEC-152 satisfied on paper and silent in practice.

    This test fails the moment SPEC-169 adds a Map, a Wait or a copy, which is the moment the
    ceiling and its rule become required. That is the whole point: it is a tripwire on the
    next spec, not a description of this one.
    """
    waiting = [
        name for name, state in STATES.items()
        if state.get("Type") in ("Map", "Wait", "Parallel")
    ]

    assert not waiting, (
        f"{waiting} can wedge, so this machine now needs a top-level TimeoutSeconds AND the "
        "EventBridge TIMED_OUT rule that makes it reachable by a notification"
    )
    assert "TimeoutSeconds" not in ASL


def test_no_verb_state_writes_to_s3_yet():
    """SPEC-168 copies nothing and deletes nothing. The execution role holds no S3 grant on
    any data bucket, so a Task added here without the matching grant would fail at runtime
    with an AccessDenied that reads like an IAM bug."""
    tasks = {name for name, state in STATES.items() if state.get("Type") == "Task"}

    assert tasks == {"ValidateAuthorize", "NotifyFailure"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
