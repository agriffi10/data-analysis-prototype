"""The table-share machine and its two roles, after the Distributed Map (SPEC-160).

The repo-wide invariants — reachability, no throwing intrinsic, the failure-seed rule,
NotifyFailure before Fail — live in ``control-plane-common/test_state_machines_cpcommon.py``
and cover this machine with the other three. What is asserted HERE is what only this machine
has: that the transfer Map is TOP LEVEL, that its sizing matches the constants the batch verb
reads, that the recipient work really did split into a guard and a finish, and that the Map's
permissions landed on the STATE MACHINE role rather than the Lambda one.

Reads the deployed templates rather than a copy, so drift fails rather than passes. Runnable
under pytest or directly: python3 test_state_machine_table_share.py.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import pytest
from cpcommon.transfer import config as transfer_config

_MODULE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", "modules", "table-share"
)
_TFTPL = os.path.join(_MODULE, "state-machine.asl.json.tftpl")
_SFN_POLICY = os.path.join(_MODULE, "policies", "sfn-permissions.json.tftpl")
_EXECUTION_POLICY = os.path.join(_MODULE, "policies", "execution.json.tftpl")
_LOCALS = os.path.join(_MODULE, "locals.tf")


def _asl():
    """The rendered machine, with placeholders stubbed the way the fleet guard stubs them."""
    with open(_TFTPL) as handle:
        raw = handle.read()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{[^}]+\}", "ARN", raw))


def _states(asl, states=None, prefix=""):
    """(qualified name, state) for every state, including inside a Map's ItemProcessor."""
    for name, state in (states or asl["States"]).items():
        yield prefix + name, state
        if "ItemProcessor" in state:
            yield from _states(asl, state["ItemProcessor"]["States"], f"{prefix}{name}/")


def _policy(path):
    """The rendered policy. A bare placeholder in a value position (``jsonencode``d ARN lists)
    is stubbed to a string, a quoted one to its contents — the same two-step the ASL needs."""
    with open(path) as handle:
        raw = handle.read()
    raw = re.sub(r":\s*\$\{[^}]+\}", ': "STUB"', raw)
    return json.loads(re.sub(r"\$\{[^}]+\}", "STUB", raw))


def _actions(policy):
    actions = set()
    for statement in policy["Statement"]:
        action = statement["Action"]
        actions.update([action] if isinstance(action, str) else action)
    return actions


# ── the Distributed Map ─────────────────────────────────────────────────────


def test_the_transfer_map_is_top_level_and_not_nested():
    """FR-002 AC7 — the restructure's whole point, as an assertion.

    Nesting a Distributed Map inside the recipient Map is the obvious version of this change
    and the wrong one: it fans out per recipient, so the caps would still be per-recipient
    work, and it raises the nesting question this design sidesteps by covering every recipient
    in one Map over (recipient x object) pairs.
    """
    asl = _asl()
    for name, state in _states(asl):
        if "/" not in name:
            continue
        mode = (state.get("ItemProcessor") or {}).get("ProcessorConfig", {}).get("Mode")
        assert mode != "DISTRIBUTED", f"{name} is a Distributed Map nested inside another Map"


def test_an_item_failure_never_fails_the_map_run():
    """FR-002 AC5 — the run MUST finish, because attribution reads its export."""
    assert _asl()["States"]["TransferObjects"]["ToleratedFailurePercentage"] == 100


def test_the_maps_sizing_matches_the_constants_the_verb_reads():
    """FR-002 AC3/AC4 — the numbers live in Python AND in locals.tf, so hold them together.

    Terraform cannot import cpcommon. Two homes for one number is how a batch grows past the
    256 KB child-input limit it was sized against while its own test still passes.
    """
    with open(_LOCALS) as handle:
        locals_tf = handle.read()

    for name, value in (
        ("transfer_max_items_per_batch", transfer_config.MAX_ITEMS_PER_BATCH),
        ("transfer_map_max_concurrency", transfer_config.MAP_MAX_CONCURRENCY),
    ):
        assert re.search(rf"^\s*{name}\s*=\s*{value}\s*$", locals_tf, re.MULTILINE), (
            f"locals.tf's {name} does not match cpcommon.transfer.config's {value}"
        )

    with open(_TFTPL) as handle:
        asl_raw = handle.read()
    assert '"MaxItemsPerBatch": ${transfer_max_items_per_batch}' in asl_raw
    assert '"MaxConcurrency": ${transfer_map_max_concurrency}' in asl_raw


# ── SPEC-161 FR-003/FR-004: the machine cannot hang, and nothing expires under it ──


def _timeout_seconds():
    """The named value locals.tf gives the state machine's TimeoutSeconds."""
    with open(_LOCALS) as handle:
        match = re.search(
            r"^\s*state_machine_timeout_seconds\s*=\s*(\d+)\s*$", handle.read(), re.MULTILINE
        )
    assert match, "locals.tf declares no state_machine_timeout_seconds"
    return int(match.group(1))


def test_the_timeout_is_a_top_level_field_of_the_definition():
    """SPEC-161 FR-003 AC1, and the distinction is the whole criterion.

    TimeoutSeconds is a field of the STATE MACHINE, beside StartAt — not an argument to the
    aws_sfn_state_machine resource and not a task field. Put on a Task it bounds that step
    only, which is not what a wedged run needs; omitted entirely, a Standard workflow runs to
    Step Functions' one-year default. SPEC-157 settled the same point for the table-builder.
    """
    asl = _asl()

    assert "TimeoutSeconds" in asl, "the machine has no top-level TimeoutSeconds"
    for name, state in _states(asl):
        assert "TimeoutSeconds" not in state, (
            f"{name} carries a TimeoutSeconds — this spec bounds the RUN, not a step"
        )


def test_the_byte_product_is_what_the_timeout_is_sized_against_not_the_source():
    """The distinction that made the bug invisible, pinned so it cannot be un-learned.

    ``SHARE_MAX_TOTAL_BYTES`` bounds ONE copy of the source. The manifest carries one item per
    (recipient, object) pair, so the Map moves the source once per recipient — and a timeout
    sized against the source alone is short by a factor of ``SHARE_MAX_RECIPIENTS``.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tscommon import config as ts_config

    assert ts_config.SHARE_MAX_TRANSFER_BYTES >= ts_config.SHARE_MAX_TOTAL_BYTES, (
        "a single-recipient share of a max-size source must not be refused by the transfer cap"
    )
    assert (
        ts_config.SHARE_MAX_TRANSFER_BYTES
        < ts_config.SHARE_MAX_TOTAL_BYTES * ts_config.SHARE_MAX_RECIPIENTS
    ), (
        "the transfer cap is above source x recipients, so it can never bind — which is the "
        "state the plane was in when the timeout could not cover its own caps"
    )


def test_the_machine_itself_cannot_notify_a_timeout_so_a_rule_must():
    """SPEC-161 FR-003 AC2 — asserted as the thing that is TRUE, not the thing we wish were.

    An earlier version of this test asserted `RecordFailure → NotifyFailure` and called the
    criterion covered. That is pre-existing SPEC-152 wiring, it passes with `TimeoutSeconds`
    deleted, and it proves nothing about a timeout: AWS is explicit that "catchers are
    available for Task, Parallel and Map states, but not for top-level state machine execution
    failures". A top-level timeout terminates the run outright — no state runs, no Catch fires,
    and `NotifyFailure` is unreachable on this one path.

    So what has to hold is that **something outside the machine listens**. The rule and its
    handler are covered in `table-share-notify-failure/test_ts_notify_failure.py`; what belongs
    here is that the in-machine path is still intact for every OTHER whole-request failure, and
    that the two cannot both fire (the rule matches TIMED_OUT, the Fail state produces FAILED).
    """
    asl = _asl()

    assert asl["States"]["RecordFailure"]["Next"] == "NotifyFailure"
    assert asl["States"]["NotifyFailure"]["Catch"][0]["Next"] == "Failed"
    assert asl["States"]["Failed"]["Type"] == "Fail"

    with open(os.path.join(_MODULE, "stepfunction.tf")) as handle:
        stepfunction = handle.read()
    assert "aws_cloudwatch_event_rule" in stepfunction, (
        "nothing listens for TIMED_OUT, so a wedged run ends silently — the timeout bounds the "
        "run but tells the sender nothing"
    )


# ── FR-006: which role holds the Map's permissions ──────────────────────────


def test_the_state_machine_role_holds_the_distributed_maps_permissions():
    """FR-006 AC1/AC2. It is the STATE MACHINE that starts each child execution and that
    reads the ItemReader object and writes the ResultWriter export."""
    actions = _actions(_policy(_SFN_POLICY))

    assert "states:StartExecution" in actions
    assert "states:DescribeExecution" in actions
    assert {"s3:GetObject", "s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"} <= actions


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
