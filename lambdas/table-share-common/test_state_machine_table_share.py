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
import math
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


def _tasks_in(state):
    """The Lambda ARNs a Map's ItemProcessor invokes."""
    return [
        s["Parameters"]["FunctionName"]
        for s in state["ItemProcessor"]["States"].values()
        if s.get("Type") == "Task"
    ]


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


def test_the_transfer_map_reads_the_manifest_as_jsonl():
    reader = _asl()["States"]["TransferObjects"]["ItemReader"]

    assert reader["Resource"] == "arn:aws:states:::s3:getObject"
    assert reader["ReaderConfig"] == {"InputType": "JSONL"}
    assert reader["Parameters"] == {
        "Bucket.$": "$.transfer.manifestBucket",
        "Key.$": "$.transfer.manifestKey",
    }


def test_the_child_executions_are_standard_not_express():
    """FR-002 AC2. A batch may hold a multi-GiB object whose multipart copy exceeds EXPRESS's
    five-minute ceiling, and EXPRESS's at-least-once semantics would re-run whole batches."""
    assert _asl()["States"]["TransferObjects"]["ItemProcessor"]["ProcessorConfig"] == {
        "Mode": "DISTRIBUTED",
        "ExecutionType": "STANDARD",
    }


def test_an_item_failure_never_fails_the_map_run():
    """FR-002 AC5 — the run MUST finish, because attribution reads its export."""
    assert _asl()["States"]["TransferObjects"]["ToleratedFailurePercentage"] == 100


def test_the_map_exports_its_results_rather_than_returning_them():
    """FR-002 AC6 — an inline array of every child result breaches the 256 KB state limit at
    exactly the scale this Map exists for."""
    writer = _asl()["States"]["TransferObjects"]["ResultWriter"]

    assert writer["Resource"] == "arn:aws:states:::s3:putObject"
    assert writer["Parameters"] == {
        "Bucket.$": "$.transfer.resultsBucket",
        "Prefix.$": "$.transfer.resultsPrefix",
    }
    assert _asl()["States"]["TransferObjects"]["ResultPath"] == "$.mapRun"


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


def test_the_map_concurrency_is_bounded():
    """FR-002 AC4 — declared, and nowhere near the 10,000 default.

    Every child execution invokes a Lambda that opens up to COPY_CONCURRENCY S3 connections,
    so the default would put the account's whole Lambda concurrency behind one user's share.
    """
    assert "MaxConcurrency" in _asl()["States"]["TransferObjects"]
    assert 0 < transfer_config.MAP_MAX_CONCURRENCY <= 100


# ── the restructure ─────────────────────────────────────────────────────────


def test_the_guard_map_runs_the_conflict_check_only():
    """FR-005 AC1 — copy and create moved out; the guard keeps its per-item Catch."""
    guard = _asl()["States"]["GuardRecipients"]

    assert len(_tasks_in(guard)) == 1
    assert guard["ItemProcessor"]["StartAt"] == "CheckTargetAbsent"
    assert guard["ItemProcessor"]["ProcessorConfig"]["Mode"] == "INLINE"
    catches = guard["ItemProcessor"]["States"]["CheckTargetAbsent"]["Catch"]
    assert catches[0]["Next"] == "RecipientRefused", "a refusal must end the ITEM, not the Map"


def test_the_finish_map_runs_create_table_only():
    """FR-005 AC2."""
    finish = _asl()["States"]["FinishRecipients"]

    assert len(_tasks_in(finish)) == 1
    assert finish["ItemProcessor"]["States"]["CreateTable"]["Parameters"]["Payload"] == {
        "recipient.$": "$.entry.recipient",
        "request.$": "$.request",
    }


def test_the_finish_map_only_creates_for_a_cleared_recipient():
    """A recipient short of a copied object must not get a table over a partial dataset."""
    choice = _asl()["States"]["FinishRecipients"]["ItemProcessor"]["States"]["RecipientOutcome"]

    assert choice["Choices"][0]["And"][1] == {"Variable": "$.entry.status", "StringEquals": "ok"}
    assert choice["Default"] == "RecipientCarried"


@pytest.mark.parametrize(
    ("state", "path"),
    [("HasTransferItems", "$.transfer.itemCount"), ("FinishRecipients/RecipientOutcome", "$.entry.status")],
)
def test_every_choice_tests_is_present_before_it_tests_the_value(state, path):
    """FR-005 AC3, and the settled rule behind it: a Choice on an ABSENT path raises
    States.Runtime, which is uncatchable and which `Default` does NOT cover."""
    choice = dict(_states(_asl()))[state]
    conditions = choice["Choices"][0]["And"]

    assert conditions[0] == {"Variable": path, "IsPresent": True}, (
        f"{state} must test IsPresent FIRST — Default does not cover an absent path"
    )


def test_the_empty_transfer_skips_the_map_entirely():
    """FR-005 AC4 — every recipient conflicted: no child execution, no States.Runtime."""
    assert _asl()["States"]["HasTransferItems"]["Default"] == "CollectTransferResults"


def test_the_copy_batch_has_no_catch_of_its_own():
    """A caught batch failure would SUCCEED its child execution, filing a failed batch under
    SUCCEEDED_n.json with no per-item failures in it — and the collector would report every
    one of those items as copied."""
    copy_state = _asl()["States"]["TransferObjects"]["ItemProcessor"]["States"]["CopyObjects"]

    assert "Catch" not in copy_state
    assert copy_state["End"] is True
    assert "TransientError" in copy_state["Retry"][0]["ErrorEquals"]


def test_the_summary_still_reads_one_flat_per_recipient_array():
    """SPEC-092's terminal shape and SPEC-094's notifications are unchanged by this spec."""
    assert _asl()["States"]["ShapeSummary"]["Parameters"] == {
        "actor.$": "$.actor",
        "source.$": "$.source",
        "tableName.$": "$.tableName",
        "results.$": "$.recipientResults",
    }


# ── SPEC-161: the caps and the verbs that have to survive them ──────────────


def _verb_sizing(suffix):
    """The (timeout, memory) locals.tf declares for one table-share verb."""
    with open(_LOCALS) as handle:
        match = re.search(
            rf'^\s*"{suffix}"\s*=\s*\{{[^}}]*timeout\s*=\s*(\d+),\s*memory\s*=\s*(\d+)',
            handle.read(),
            re.MULTILINE,
        )
    assert match, f"locals.tf declares no timeout/memory for {suffix} — the block was reformatted"
    return int(match.group(1)), int(match.group(2))


def test_the_verb_sizing_parse_did_not_go_trivial():
    """Guards the guard: a regex that stops matching makes the two checks below vacuous."""
    assert _verb_sizing("copy-objects") == (900, 1024)


@pytest.mark.parametrize("suffix", ["build-transfer-manifest", "collect-transfer-results"])
def test_the_manifest_verbs_are_sized_for_the_transfer_item_cap(suffix):
    """SPEC-161 FR-001 AC1 — the cap's docstring names these two, so hold them to it.

    They handle the same volume in opposite directions: build-transfer-manifest serialises
    every transfer item, and collect-transfer-results reads the Map Run export, which carries
    every batch's input back again. The worst-case byte volume is COMPUTED from the cap and
    the same worst-case item the batch sizing uses (two 1024-byte keys, two 63-byte buckets),
    so raising SHARE_MAX_TRANSFER_ITEMS without re-sizing the verbs fails here.

    The multiplier is 8x rather than 1x because the constraint is not the bytes, it is
    ``json.loads`` of them: a parsed dict of short string keys costs several times its
    serialised size in Python objects, and the verb holds the source and the parse at once.

    The collector's side is counted at TWICE the manifest, not once: a Map Run export record
    carries the child's ``Input`` as well as its ``Output``, and ``results.read_failed_items``
    reads both groups. Modelling it at one copy would spend half the stated headroom silently.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tscommon import config as ts_config

    worst_item = json.dumps({
        "recipient": "r" * 63, "kind": "space",
        "srcBucket": "b" * 63, "srcKey": "s" * 1024,
        "destBucket": "d" * 63, "destKey": "k" * 1024,
        "size": 5 * 1024**3,
    })
    manifest_bytes = (len(worst_item.encode()) + 1) * ts_config.SHARE_MAX_TRANSFER_ITEMS
    worst_bytes = manifest_bytes * (2 if suffix == "collect-transfer-results" else 1)
    timeout, memory = _verb_sizing(suffix)

    assert memory * 1024**2 >= worst_bytes * 8, (
        f"{suffix} has {memory} MB for a worst-case {worst_bytes / 1024**2:.0f} MB of JSON at "
        f"SHARE_MAX_TRANSFER_ITEMS={ts_config.SHARE_MAX_TRANSFER_ITEMS:,}"
    )
    assert timeout >= 300, f"{suffix} has {timeout}s to move {worst_bytes / 1024**2:.0f} MB"


def test_the_recipient_cap_is_unchanged_by_the_scale_work():
    """SPEC-161 FR-001 AC4, as an explicit pin rather than an absence.

    It bounds the INLINE Map's state and the per-item error detail — neither of which this
    arc touched — so raising it alongside the others would be a change nothing here sized.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tscommon import config as ts_config

    assert ts_config.SHARE_MAX_RECIPIENTS == 50


def test_the_transfer_item_cap_is_the_binding_one():
    """The product is what the manifest costs, so it must not exceed either factor's reach.

    A SHARE_MAX_TRANSFER_ITEMS above objects x recipients would be decorative — nothing could
    ever reach it — and one below SHARE_MAX_OBJECTS would refuse a single-recipient share the
    object cap just allowed, which is the more confusing of the two failures.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tscommon import config as ts_config

    assert ts_config.SHARE_MAX_TRANSFER_ITEMS >= ts_config.SHARE_MAX_OBJECTS
    assert (
        ts_config.SHARE_MAX_TRANSFER_ITEMS
        <= ts_config.SHARE_MAX_OBJECTS * ts_config.SHARE_MAX_RECIPIENTS
    )


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


def test_the_timeout_is_fed_from_a_named_value_and_clears_the_caps():
    """SPEC-161 FR-003 AC1/AC3 — a named local, COMPUTED against the FR-001 caps.

    An earlier version asserted a hard-coded ``>= 3600`` floor, and that is how the branch
    shipped an unsatisfiable timeout through two review rounds. The floor was derived from
    ``SHARE_MAX_TOTAL_BYTES`` alone — but the Map copies the source once PER RECIPIENT, so the
    real quantity is ``SHARE_MAX_TRANSFER_BYTES``, and at 50 recipients x a 1 TiB source it was
    50 TiB: 3.8 hours at the conservative rate against a 3-hour ceiling. A magic number cannot
    notice that; a computation can, and the two sibling bounds on this branch were already
    written that way.

    **And the denominator is a makespan, not an aggregate bandwidth** — the correction a fourth
    round made. ``MAP_MAX_CONCURRENCY x COPY_CONCURRENCY`` is 160 concurrent copies only when
    every batch holds eight comparable objects. ``copy_batch`` gives one whole object to one
    worker and ``copy_one`` part-copies serially, so a batch whose bytes sit in one large
    object runs at ONE stream while seven idle — an ordinary mixed-size Parquet table. The
    pessimistic denominator is therefore ``MAP_MAX_CONCURRENCY x rate`` (500 MB/s), not
    ``x COPY_CONCURRENCY x rate`` (4 GB/s). Under the aggregate reading 16 TiB looked like
    4,400 s; the real figure was 35,000, and the test was green.

    The copy is also not the only thing in the window: the finish Map's Athena creates and the
    serial verbs either side of the Map come out of the same ceiling, so they are subtracted
    here rather than waved at.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
    from cpcommon.transfer import config as transfer_config
    from tscommon import config as ts_config

    with open(_TFTPL) as handle:
        assert '"TimeoutSeconds": ${state_machine_timeout_seconds}' in handle.read()

    # One stream per in-flight child, because a batch's slowest object is what it costs.
    throughput = (
        transfer_config.MAP_MAX_CONCURRENCY * transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    )
    copy_seconds = ts_config.SHARE_MAX_TRANSFER_BYTES / throughput

    asl = _asl()
    finish_concurrency = asl["States"]["FinishRecipients"]["MaxConcurrency"]
    create_timeout, _ = _verb_sizing("create-table")
    finish_seconds = math.ceil(ts_config.SHARE_MAX_RECIPIENTS / finish_concurrency) * create_timeout
    serial_seconds = sum(
        _verb_sizing(v)[0]
        for v in ("inspect-source", "build-transfer-manifest", "collect-transfer-results")
    )
    total = copy_seconds + finish_seconds + serial_seconds

    assert total < _timeout_seconds(), (
        f"the worst share the caps allow needs {total:,.0f}s — copy {copy_seconds:,.0f}s for "
        f"{ts_config.SHARE_MAX_TRANSFER_BYTES / 1024**4:,.0f} TiB at {throughput / 1e6:.0f} MB/s, "
        f"finish Map {finish_seconds:,.0f}s, serial verbs {serial_seconds:,.0f}s — against a "
        f"{_timeout_seconds()}s ceiling. Lower SHARE_MAX_TRANSFER_BYTES or raise the timeout."
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


def test_the_admin_retention_window_outlasts_a_whole_run():
    """SPEC-161 FR-004 AC1 — the risk here is INVERTED from the usual one.

    Nothing new needs expiring: the manifest, the definition and the ResultWriter export all
    sit under table-share/, which expire-table-share-copy-plans already covers. The exposure a
    longer-running machine creates is the opposite — the rule expiring a LIVE run's manifest
    out from under its own Map Run. Read from infra/ so the two cannot drift apart.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    variables = os.path.join(here, "..", "..", "infra", "modules", "analytics", "variables.tf")
    with open(variables) as handle:
        block = re.search(
            r'variable "admin_results_retention_days".*?default\s*=\s*(\d+)',
            handle.read(),
            re.DOTALL,
        )
    assert block, "admin_results_retention_days has no default to compare against"

    retention_seconds = int(block.group(1)) * 86400
    assert retention_seconds > _timeout_seconds() * 100, (
        f"{block.group(1)}-day retention is only "
        f"{retention_seconds / _timeout_seconds():.0f}x the {_timeout_seconds()}s run ceiling"
    )


def test_no_second_lifecycle_rule_covers_the_transfer_artifacts():
    """SPEC-161 FR-004 AC2/AC3 — the obligation is to add NOTHING, so assert the absence.

    All three artifacts share the copy plan's prefix by construction (tscommon.copy_plan owns
    every key this plane writes), so a second rule would be a duplicate that S3 resolves by
    taking the shortest expiry — a silent tightening nobody chose.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "..", "infra", "modules", "analytics", "s3.tf")) as handle:
        lifecycle = handle.read()

    assert lifecycle.count('prefix = "table-share/"') == 1, "a second table-share/ rule appeared"
    assert 'id     = "expire-table-share-copy-plans"' in lifecycle


def test_expiry_stays_the_buckets_job_and_not_the_planes():
    """SPEC-161 FR-004 AC4 — the Deny that makes "expired" mean the bucket did it.

    Read from the RAW template, not the stubbed policy: ``_policy`` collapses every ARN
    placeholder to one literal, so a check on the parsed form cannot tell the admin bucket
    from the two space buckets and would pass on a deny that had stopped covering it.
    """
    with open(_EXECUTION_POLICY) as handle:
        raw = json.loads(re.sub(r"\$\{([a-z_]+)\}", r"\1", handle.read()))
    deny = next(
        s for s in raw["Statement"] if s["Effect"] == "Deny" and s["Action"] == "s3:DeleteObject"
    )
    resources = deny["Resource"] if isinstance(deny["Resource"], list) else [deny["Resource"]]

    assert "admin_bucket_arn/*" in resources, (
        "the execution role's DeleteObject deny no longer covers the admin bucket, so a verb "
        "could delete a transfer artifact the lifecycle rule is supposed to expire"
    )


# ── FR-006: which role holds the Map's permissions ──────────────────────────


def test_the_state_machine_role_holds_the_distributed_maps_permissions():
    """FR-006 AC1/AC2. It is the STATE MACHINE that starts each child execution and that
    reads the ItemReader object and writes the ResultWriter export."""
    actions = _actions(_policy(_SFN_POLICY))

    assert "states:StartExecution" in actions
    assert "states:DescribeExecution" in actions
    assert {"s3:GetObject", "s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"} <= actions


def test_stop_execution_is_not_granted():
    """FR-006 AC1 — nothing here stops a child; StartExecution + DescribeExecution is the
    documented least-privilege pair."""
    assert "states:StopExecution" not in _actions(_policy(_SFN_POLICY))


def test_the_lambda_execution_role_gains_nothing_from_the_map():
    """FR-006 AC4 — THE SWAP NOTHING ELSE WOULD CATCH.

    Granting these to the execution role renders green, applies green, and passes every other
    policy assertion in this repo. It fails on the first real share, at the ItemReader, with an
    AccessDenied that names a role nobody was looking at.
    """
    actions = _actions(_policy(_EXECUTION_POLICY))

    assert not {a for a in actions if a.startswith("states:")}, (
        "the Distributed Map's states: actions are on the LAMBDA execution role"
    )


def test_the_execution_roles_delete_deny_still_stands():
    """FR-006 AC3 — untouched by this spec, and worth asserting because it is the one
    statement whose loss would let a verb delete a user's data."""
    policy = _policy(_EXECUTION_POLICY)
    denies = [s for s in policy["Statement"] if s["Effect"] == "Deny"]

    assert any(s["Action"] == "s3:DeleteObject" for s in denies)


def test_no_new_wildcard_resource_appears():
    """FR-006 AC5 — the SPEC-139 plan scan's IAM findings must not grow.

    The one pre-existing `Resource: "*"` here is Step Functions' own log delivery, which has no
    ARN to scope to; this pins the count at that one rather than forbidding it.
    """
    wildcards = [s["Sid"] for s in _policy(_SFN_POLICY)["Statement"] if s["Resource"] == "*"]
    assert wildcards == ["StepFunctionLogDelivery"], f"new wildcard statements: {wildcards}"


def test_the_results_bucket_is_the_admin_bucket():
    """FR-006 AC6 — a cross-account or cross-Region ResultWriter fails the execution with
    States.ResultWriterFailed. The admin bucket is a module input of this account's stack, so
    the requirement holds by construction; this pins the prefix the grant covers."""
    resources = {
        s["Resource"]
        for s in _policy(_SFN_POLICY)["Statement"]
        if s["Sid"] in ("ReadTransferManifest", "WriteTransferResults")
    }
    assert resources == {"STUB/table-share/*"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
