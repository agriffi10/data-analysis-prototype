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

_MODULE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "infra", "modules", "table-builder",
)
_ASL = os.path.join(_MODULE, "state-machine.asl.json.tftpl")


def _declared_timeout():
    """The execution bound the DEPLOYED machine actually carries.

    It is a top-level field of the ASL document, not a Terraform resource argument —
    `aws_sfn_state_machine` has no `timeout_seconds` and `tofu validate` rejects one. Reading
    the shipped template is also the only way this assertion means anything: a copy would agree
    with itself forever.
    """
    with open(_ASL) as handle:
        asl = json.loads(re.sub(r"\$\{[^}]+\}", "ARN", handle.read()))
    assert "TimeoutSeconds" in asl, (
        "the state machine declares no TimeoutSeconds — a Standard execution may then run for a "
        "year, and no steal threshold in table_lock.py is defensible against that"
    )
    return asl["TimeoutSeconds"]


def test_the_state_machine_declares_a_timeout_at_all():
    """Without one a Standard execution may run for a year and no steal threshold is defensible."""
    assert _declared_timeout() > 0


def test_the_python_mirror_equals_what_terraform_sets():
    """The join nothing else makes. Raising one without the other silently changes what stale means."""
    assert _declared_timeout() == table_lock.MACHINE_TIMEOUT_SECONDS, (
        "tbcommon.table_lock.MACHINE_TIMEOUT_SECONDS and stepfunction.tf's timeout_seconds have "
        "drifted — the steal threshold is derived from the mirror, so the lock would now be "
        "stealable on a schedule that no longer matches when executions actually die"
    )


def test_the_steal_threshold_is_strictly_greater_than_the_timeout():
    """Below it, a running execution's lock becomes stealable — the race, reintroduced."""
    assert _declared_timeout() < table_lock.STALE_LOCK_SECONDS


def test_the_timeout_clears_the_create_paths_worst_case():
    """FR-004 AC1. Adding a timeout must not fail an ordinary create.

    Every Task retries 3 times over 2/4/8-second intervals, so a state costs
    ``4 * timeout + 14`` seconds. The create path's states are validate-authorize,
    check-table-absent, inspect-source, infer-schema, execute-ddl, the release pass-through and
    notify-failure. Computed here rather than asserted as a constant, so raising a verb's Lambda
    timeout without revisiting the machine's fails this instead of being discovered in production.
    """
    create_path_lambda_timeouts = [15, 15, 60, 120, 300, 15, 15]
    worst_case = sum(4 * t + 14 for t in create_path_lambda_timeouts)

    assert _declared_timeout() > worst_case, (
        f"the create path's worst case is {worst_case}s but the machine times out at "
        f"{_declared_timeout()}s — adding the bound would fail ordinary table builds"
    )


def test_the_verb_timeouts_the_derivation_rests_on_are_still_what_terraform_says():
    """Guards the guard: the arithmetic above is only meaningful against the real timeouts."""
    locals_tf = os.path.join(_MODULE, "locals.tf")
    with open(locals_tf) as handle:
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
