"""SPEC-157 FR-004 AC1/AC2 — the bound that makes "this lock is stale" mean anything.

A lock is stealable only because executions are bounded, so the bound comes first. The state
machine had NO ``TimeoutSeconds``, which means a Standard execution may run for up to a year and
no age threshold could be justified against it — adding one is a prerequisite of the lock design,
not a tidy-up.

The number therefore lives in two places that cannot be allowed to drift: Terraform sets the
machine's timeout, and ``tbcommon.table_lock`` derives its steal threshold from a mirror of it.
A steal threshold below the real timeout would let a RUNNING execution's lock be stolen, which is
precisely the race the lock exists to prevent — and nothing else in the repo joins the two.

Reads the deployed Terraform rather than a copy, so drift fails rather than passes.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from tbcommon import table_lock
from tf_blocks import argument, module_calls

_INFRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra")
_ASL = os.path.join(_INFRA, "planes", "table-builder", "state-machine.asl.json.tftpl")
_ROOT = os.path.join(_INFRA, "plane-table-builder.tf")
_CONTROL_PLANE_LOCALS = os.path.join(_INFRA, "modules", "control-plane", "locals.tf")


def _waking_seconds(asl_text):
    """The backoff a Task spends waiting out a function waking from Inactive, read from the ASL.

    Charged once per function a run reaches and with no timeout: a rejected invoke never ran, and
    a function woken for its first attempt is awake for the rest. Every Task carries the same
    retrier, which this asserts, so one number stands for all of them.
    """
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", asl_text)
    policies = set()

    def walk(node):
        if isinstance(node, dict):
            if "Lambda.ResourceNotReadyException" in node.get("ErrorEquals", []):
                policies.add(json.dumps(node, sort_keys=True))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw)))
    assert len(policies) == 1, f"the waking retrier is not one shape across the machine: {policies}"
    policy = json.loads(policies.pop())
    return sum(policy["IntervalSeconds"] * policy["BackoffRate"] ** i for i in range(policy["MaxAttempts"]))


def _declared_timeout():
    """The execution bound the DEPLOYED machine actually carries.

    It is a top-level field of the ASL document, not a Terraform resource argument —
    `aws_sfn_state_machine` has no `timeout_seconds` and `tofu validate` rejects one. The
    template carries it as a placeholder the control-plane module fills from the plane call's
    ``ceiling.seconds``, so all three links are read: the field, the module's wiring and the
    call's number. A copy would agree with itself forever.
    """
    with open(_ASL) as handle:
        raw = re.sub(r":\s*\$\{([^}]+)\}", r': "\1"', handle.read())
    asl = json.loads(re.sub(r"\$\{[^}]+\}", "ARN", raw))
    assert "TimeoutSeconds" in asl, (
        "the state machine declares no TimeoutSeconds — a Standard execution may then run for a "
        "year, and no steal threshold in table_lock.py is defensible against that"
    )
    assert asl["TimeoutSeconds"] == "state_machine_timeout_seconds", (
        f"TimeoutSeconds is {asl['TimeoutSeconds']!r}, not the ceiling the module renders"
    )
    with open(_CONTROL_PLANE_LOCALS) as handle:
        assert "state_machine_timeout_seconds = try(var.ceiling.seconds, null)" in handle.read()
    with open(_ROOT) as handle:
        ceiling = argument(module_calls(handle.read())["table_builder"], "ceiling")
    return int(argument(ceiling[1:-1], "seconds"))


def test_the_state_machine_declares_a_timeout_at_all():
    """Without one a Standard execution may run for a year and no steal threshold is defensible."""
    assert _declared_timeout() > 0


def test_the_python_mirror_equals_what_terraform_sets():
    """The join nothing else makes. Raising one without the other silently changes what stale means."""
    assert _declared_timeout() == table_lock.MACHINE_TIMEOUT_SECONDS, (
        "tbcommon.table_lock.MACHINE_TIMEOUT_SECONDS and the plane call's ceiling.seconds have "
        "drifted — the steal threshold is derived from the mirror, so the lock would now be "
        "stealable on a schedule that no longer matches when executions actually die"
    )


def test_the_steal_threshold_is_strictly_greater_than_the_timeout():
    """Below it, a running execution's lock becomes stealable — the race, reintroduced."""
    assert _declared_timeout() < table_lock.STALE_LOCK_SECONDS


def test_the_timeout_clears_the_create_paths_worst_case():
    """FR-004 AC1. Adding a timeout must not fail an ordinary create.

    Every Task retries 3 times over 2/4/8-second intervals, so a state costs
    ``4 * timeout + 14`` seconds, plus one wait for its function to wake from Inactive. The create
    path's states are validate-authorize, check-table-absent, inspect-source, infer-schema,
    execute-ddl, the release pass-through and notify-failure. Computed here rather than asserted as a constant, so raising a verb's Lambda
    timeout without revisiting the machine's fails this instead of being discovered in production.
    """
    create_path_lambda_timeouts = [15, 15, 60, 120, 300, 15, 15]
    with open(_ASL) as handle:
        waking = _waking_seconds(handle.read())
    worst_case = sum(4 * t + 14 + waking for t in create_path_lambda_timeouts)

    assert _declared_timeout() > worst_case, (
        f"the create path's worst case is {worst_case}s but the machine times out at "
        f"{_declared_timeout()}s — adding the bound would fail ordinary table builds"
    )


def test_the_verb_timeouts_the_derivation_rests_on_are_still_what_terraform_says():
    """Guards the guard: the arithmetic above is only meaningful against the real timeouts."""
    with open(_ROOT) as handle:
        source = handle.read()
    timeouts = {
        suffix: int(value)
        for suffix, value in re.findall(
            r'"([a-z-]+)"\s*=\s*\{[^}]*timeout\s*=\s*(\d+)', source
        )
    }

    assert timeouts.get("execute-ddl") == 300
    assert timeouts.get("infer-schema") == 120
    assert timeouts.get("acquire-refresh-lock") == 15
    assert timeouts.get("release-refresh-lock") == 15
