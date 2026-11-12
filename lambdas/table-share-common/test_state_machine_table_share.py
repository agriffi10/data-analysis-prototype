"""The table-share machine and its two roles, after the Distributed Map (SPEC-160).

The repo-wide invariants — reachability, no throwing intrinsic, the failure-seed rule,
NotifyFailure before Fail — live in ``control-plane-common/test_state_machines_cpcommon.py``
and cover this machine with the other three. What is asserted HERE is what only this machine
has: that the transfer Map is TOP LEVEL, that its sizing matches the constants the batch verb
reads, that the recipient work really did split into a guard and a finish, and that the Map's
permissions landed on the STATE MACHINE role rather than the Lambda one.

Reads the deployed templates rather than a copy, so drift fails rather than passes.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon.transfer import config as transfer_config
from tf_blocks import argument, blocks, map_entries, module_calls, span

_INFRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra")
_PLANE = os.path.join(_INFRA, "planes", "table-share")
_CONTROL_PLANE = os.path.join(_INFRA, "modules", "control-plane")
_TFTPL = os.path.join(_PLANE, "state-machine.asl.json.tftpl")
_SFN_POLICY = os.path.join(_CONTROL_PLANE, "policies", "sfn-permissions.json.tftpl")
_ROOT = os.path.join(_INFRA, "plane-table-share.tf")


def _read(path):
    """The text of one Terraform or template file."""
    with open(path) as handle:
        return handle.read()


def _call():
    """The body of the root's ``module "table_share"`` call, which carries every per-plane value."""
    return module_calls(_read(_ROOT))["table_share"]


def _map_body(value):
    """A braced map argument's body with its outer braces removed, so ``argument`` reads into it."""
    assert value.startswith("{") and value.endswith("}"), f"not a map literal: {value[:40]}"
    return value[1:-1]


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


def _sfn_policy():
    """The shared state-machine policy, rendered the way the module renders it for this plane.

    The template gates every Distributed Map statement on ``distributed_map``, so this reads the
    call's ``distributed_map`` block (absent, the gated statements drop, as Terraform drops them)
    and resolves the child-execution actions from its ``can_stop`` the way iam.tf does.
    """
    try:
        distributed_map = _map_body(argument(_call(), "distributed_map"))
    except ValueError:
        distributed_map = None
    iam = _read(os.path.join(_CONTROL_PLANE, "iam.tf"))
    assert '? jsonencode(["states:DescribeExecution", "states:StopExecution"])' in iam
    assert ': jsonencode("states:DescribeExecution")' in iam
    can_stop = distributed_map is not None and argument(distributed_map, "can_stop") == "true"
    actions = ["states:DescribeExecution", "states:StopExecution"] if can_stop else "states:DescribeExecution"

    raw = _read(_SFN_POLICY)
    gated = re.compile(r"^%\{ if distributed_map ~\}\n(.*?)^%\{ endif ~\}\n", re.MULTILINE | re.DOTALL)
    assert gated.search(raw), "the shared sfn policy no longer gates its Map statements the way this reads"
    raw = gated.sub(lambda match: match.group(1) if distributed_map is not None else "", raw)
    raw = raw.replace("${child_execution_actions_json}", json.dumps(actions))
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
    """FR-002 AC3/AC4 — the numbers live in Python AND in the call's definition_vars, so hold them together.

    Terraform cannot import cpcommon. Two homes for one number is how a batch grows past the
    256 KB child-input limit it was sized against while its own test still passes.
    """
    definition_vars = argument(_call(), "definition_vars")

    for name, value in (
        ("transfer_max_items_per_batch", transfer_config.MAX_ITEMS_PER_BATCH),
        ("transfer_map_max_concurrency", transfer_config.MAP_MAX_CONCURRENCY),
    ):
        assert re.search(rf"^\s*{name}\s*=\s*{value}\s*$", definition_vars, re.MULTILINE), (
            f"definition_vars' {name} does not match cpcommon.transfer.config's {value}"
        )

    with open(_TFTPL) as handle:
        asl_raw = handle.read()
    assert '"MaxItemsPerBatch": ${transfer_max_items_per_batch}' in asl_raw
    assert '"MaxConcurrency": ${transfer_map_max_concurrency}' in asl_raw


# ── SPEC-161 FR-003/FR-004: the machine cannot hang, and nothing expires under it ──


def _timeout_seconds():
    """The ceiling the plane's call gives the state machine's TimeoutSeconds.

    The module renders ``ceiling.seconds`` into the definition as ``state_machine_timeout_seconds``,
    and that wiring is asserted too, so the number read from the call is the number deployed.
    """
    assert "state_machine_timeout_seconds = try(var.ceiling.seconds, null)" in _read(
        os.path.join(_CONTROL_PLANE, "locals.tf")
    ), "the control-plane module no longer renders ceiling.seconds as the machine's TimeoutSeconds"
    seconds = argument(_map_body(argument(_call(), "ceiling")), "seconds")
    assert seconds.isdigit(), f"the call's ceiling.seconds is {seconds!r}, not a literal"
    return int(seconds)


def _verb_sizing():
    """The timeout and memory the plane's root file deploys for each table-share verb.

    Read from the Terraform rather than restated here, for the reason the cap constants are:
    a sizing decision asserted against a copy of itself agrees with nothing.

    Args:
      None.

    Returns:
      A dict of verb name to its ``(timeout seconds, memory MB)`` pair.

    Raises:
      AssertionError: If no verb entries are found, which would make every bound below
        vacuously true over an empty population.
    """
    root = _read(_ROOT)
    functions = span(root, root.index("table_share_functions = {") + len("table_share_functions = "))
    entries = re.findall(
        r'"([a-z-]+)"\s*=\s*\{[^}]*timeout\s*=\s*(\d+),\s*memory\s*=\s*(\d+)\s*\}',
        functions,
    )
    assert len(entries) >= 8, f"read {len(entries)} verb entries from the root file, expected the plane's"
    assert {name for name, _, _ in entries} == set(map_entries(functions)), (
        "a verb entry the sizing pattern cannot read would drop out of every bound below"
    )
    return {name: (int(timeout), int(memory)) for name, timeout, memory in entries}


def _worst_item():
    """The largest transfer item the manifest can carry, SHAPED BY THE BUILDER ITSELF.

    Built by handing worst-case inputs to ``build-transfer-manifest``'s own ``_items`` rather
    than by writing the seven fields out here. A hand-kept second copy of a production shape is
    the thing this whole commit exists to remove: it agrees with the original on the day it is
    written and silently stops agreeing when a field is added, and the bound computed from it
    then understates the manifest with every test still green.

    Worst case is S3's own: 1024-byte keys on both sides and 63-byte bucket names, which is the
    same worst case the batch sizing is computed against in
    ``test_a_worst_case_batch_stays_under_the_input_limit``.

    Args:
      None.

    Returns:
      One transfer item dict, as the builder would write it.

    Raises:
      AssertionError: If the builder returns anything but the single expected item.
    """
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-build-transfer-manifest")
    )
    import table_share_build_transfer_manifest as builder

    relative_key = "o" * 512
    items = builder._items(
        [{"name": "r" * 63, "kind": "space", "destBucket": "d" * 63, "destPrefix": "p" * (1024 - len(relative_key))}],
        {"bucket": "b" * 63, "prefix": "s" * (1024 - len(relative_key))},
        [{"relKey": relative_key, "size": 5 * 1024**3}],
    )
    assert len(items) == 1, f"the builder returned {len(items)} items for one pair"
    assert len(items[0]["srcKey"]) == 1024 and len(items[0]["destKey"]) == 1024, (
        "the fixture no longer builds S3's worst-case keys, so the manifest bound is understated"
    )
    return items[0]


#: Peak resident bytes per byte of manifest, measured against the production paths under
#: CPython. **The WRITE side is the larger one**, which is the opposite of the first guess:
#: ``write_manifest`` holds the item list, the joined string and the encoded body at once and
#: reached 3.5x to 4.8x depending on how the peak is sampled. ``read_failed_items`` opens ONE
#: result file at a time and accumulates only bounded ``{recipient, kind, reason}`` records, so
#: it holds the whole volume only in the degenerate single-result-file export, and measured
#: 2.6x to 3.4x even there. Six sits above every observation rather than on the highest.
_PEAK_RESIDENT_MULTIPLE = 6

#: How far the deployed memory must sit above that peak. The measurement above is CPython on a
#: developer machine with no boto3 client, no Lambda runtime and no allocator fragmentation, so
#: it is a floor rather than an estimate; and a Lambda that runs out of memory is killed with no
#: partial result and no reason an operator can read, while memory on this path is cheap. Four
#: is a judgment, stated here rather than folded into the multiple above so the two can be
#: argued separately.
_MEMORY_SAFETY_FACTOR = 4


def test_the_manifest_verbs_are_sized_for_the_transfer_item_cap():
    """``SHARE_MAX_TRANSFER_ITEMS`` is a bound on two Lambdas, so it is computed against them.

    The cap is not about the fan-out — the Map is happy at a hundred million items. It is about
    the two verbs that handle the whole manifest in one invocation, in opposite directions:
    ``build-transfer-manifest`` serialises every item into one body — it is the verb that holds
    the whole volume, and the one this bound is really sized for. ``collect-transfer-results``
    reads the Map Run export, which carries every batch's input back again; it streams that a
    result file at a time, so it reaches the same peak only when the export lands as one file.
    Both are held to the same floor because both are deployed from one sizing decision.

    Computed from the cap and the worst-case item rather than asserted as 46 MB, so the model is
    visible and a raise has somewhere to fail. What it does NOT claim is that the timeouts are
    derived: measured, serialising and parsing a worst-case manifest costs about a fifth of a
    second, so the 300 s is I/O headroom rather than a computed bound, and only its containment
    in the machine's own ceiling is asserted here.

    The floor this leaves is deliberate and worth knowing, because a bound whose bite is
    unmeasured is the kind that turns out to have had none. Measured against the shipped
    numbers it refuses 1024 MB and the fleet default of 512 MB, which is the direction a
    tidy-up moves a verb. In the other direction it is a floor rather than a tripwire: the
    first item count it refuses is 38,207, so the cap can be raised by 91% without touching
    either verb, and the plane doc says so rather than promising a build failure it cannot
    deliver.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tscommon import config as ts_config

    item_bytes = len(json.dumps(_worst_item(), separators=(",", ":")).encode())
    volume = ts_config.SHARE_MAX_TRANSFER_ITEMS * item_bytes
    required_mb = (volume * _PEAK_RESIDENT_MULTIPLE * _MEMORY_SAFETY_FACTOR) / 1024**2

    sizing = _verb_sizing()
    for verb in ("build-transfer-manifest", "collect-transfer-results"):
        memory = sizing[verb][1]
        assert memory >= required_mb, (
            f"{verb} deploys {memory} MB, under the {required_mb:.0f} MB a worst-case "
            f"{volume / 1024**2:.0f} MB manifest needs at SHARE_MAX_TRANSFER_ITEMS="
            f"{ts_config.SHARE_MAX_TRANSFER_ITEMS} — raise the verb or lower the cap"
        )

    # What this catches is the machine's ceiling being LOWERED beneath the work, not the verbs
    # growing into it: Lambda's own 900 s limit caps the sum well under the current 10800 s, so
    # no edit to the verb table alone can trip it. Stated rather than dressed as a fence.
    serial = sum(sizing[verb][0] for verb in sizing if verb != "copy-objects")
    assert serial < _timeout_seconds(), (
        f"the serial verbs alone want {serial} s of the machine's {_timeout_seconds()} s, so the "
        "run can die at the top level, where no Catch reaches the sender"
    )


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
    here is that the in-machine path is still intact for every whole-request failure a Catch
    takes, and that the two cannot both fire (the rule matches TIMED_OUT, the Fail state
    produces FAILED).
    """
    asl = _asl()

    assert asl["States"]["RecordFailure"]["Next"] == "NotifyFailure"
    assert asl["States"]["NotifyFailure"]["Catch"][0]["Next"] == "Failed"
    assert asl["States"]["Failed"]["Type"] == "Fail"

    rules = blocks(_read(os.path.join(_CONTROL_PLANE, "main.tf")), "aws_cloudwatch_event_rule")
    assert "execution_timed_out" in rules, (
        "nothing listens for TIMED_OUT, so a wedged run ends silently — the timeout bounds the "
        "run but tells the sender nothing"
    )
    ceiling = _map_body(argument(_call(), "ceiling"))
    assert argument(ceiling, "notifier_verb") == '"notify-failure"', (
        "the call's ceiling names no notifier, so the module's TIMED_OUT rule targets nothing"
    )


# ── the run a notice names ──────────────────────────────────────────────────


def test_every_notifier_holds_the_execution_name_its_notices_are_keyed_on():
    """The paths ``tscommon.notify.run_of`` reads, asserted on the machine that builds them.

    Table-share has no request id, so a notice's dedup id names its run by the execution's name,
    and a notifier that does not hold the name falls back to the queue's content dedup without a
    sound — two shares ending alike are told once again. The stamp must therefore come before the
    first notifying verb, the Maps and create-table must carry the state under ``request`` where
    ``run_of`` looks, and the recorded failure must copy the name from the context object, since
    its seed has no state to read it from.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the machine stops carrying the name to a notifier where ``run_of`` reads
        it. The verbs that pass the state on in Python are held by their own suites.
    """
    states = _asl()["States"]
    finish = states["FinishRecipients"]["ItemProcessor"]["States"]

    assert _asl()["StartAt"] == "ValidateAuthorize"
    assert states["ValidateAuthorize"]["Next"] == "StampExecution"
    assert states["StampExecution"]["Parameters"] == {"name.$": "$$.Execution.Name"}
    assert states["StampExecution"]["ResultPath"] == "$.execution"
    assert states["StampExecution"]["Next"] == "InspectSource"
    for task in ("InspectSource", "BuildTransferManifest", "CollectTransferResults"):
        assert states[task]["Parameters"]["Payload.$"] == "$", f"{task} no longer receives the whole state"
    assert states["GuardRecipients"]["ItemSelector"]["request.$"] == "$"
    assert states["FinishRecipients"]["ItemSelector"]["request.$"] == "$"
    assert finish["CreateTable"]["Parameters"]["Payload"]["request.$"] == "$.request"
    assert states["RecordFailure"]["Parameters"]["execution"] == {"name.$": "$$.Execution.Name"}


# ── FR-006: which role holds the Map's permissions ──────────────────────────


def test_the_state_machine_role_holds_the_distributed_maps_permissions():
    """FR-006 AC1/AC2. It is the STATE MACHINE that starts each child execution and that
    reads the ItemReader object and writes the ResultWriter export."""
    actions = _actions(_sfn_policy())

    assert "states:StartExecution" in actions
    assert "states:DescribeExecution" in actions
    assert {"s3:GetObject", "s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"} <= actions
