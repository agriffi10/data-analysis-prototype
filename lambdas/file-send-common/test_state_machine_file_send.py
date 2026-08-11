"""The file-send machine's JSONPaths must match what the verbs actually emit.

**A Pass state's JSONPath hard-fails on an absent key with ``States.Runtime``, which is
neither retriable nor catchable.** So a key renamed on either side of this boundary does not
produce a nice error — it kills the execution outright, on the happy path as readily as the
failure path, with a green test suite either side.

The fleet test in ``control-plane-common`` guards the failure path for every plane (a seed must
supply every key its terminal reads). Nothing guards the SUCCESS path, and nothing anywhere
compares the ASL against the verb's real return value — the verb's own suite asserts its output
keys, but it asserts them against a list written in Python, so renaming a key in both places
stays green. This file is the cross-check: it reads the template and the verb, and requires
them to agree.

Attributes:
  _ASL: The rendered-at-apply state machine template.
"""

import json
import os
import pathlib
import re
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "file-send-validate-authorize"))
sys.path.insert(0, str(_HERE.parent / "file-send-inspect-source"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_inspect_source as i
import file_send_validate_authorize as v
from cpcommon import clients

_ASL = _HERE.parent.parent / "infra" / "modules" / "file-send" / "state-machine.asl.json.tftpl"


def _machine() -> dict:
    """The state machine, with template placeholders neutralised so it parses as JSON.

    Args:
      None.

    Returns:
      The parsed ASL document.

    Raises:
      None.
    """
    return json.loads(re.sub(r"\$\{[a-z_0-9]+\}", "PLACEHOLDER", _ASL.read_text()))


def _validated_output() -> dict:
    """The verb's real return value for a minimal valid request.

    Drives the actual handler with the boundary helpers stubbed, rather than restating a shape:
    a hand-written fixture would agree with a hand-written ASL assertion and prove nothing.

    Args:
      None.

    Returns:
      The validated request the machine's next state consumes.

    Raises:
      None.
    """
    v.auth.verified_username = lambda token, **kw: "alice"
    v.reg.load = lambda name: None
    v.cognito.user_exists = lambda name: True
    body = {
        "requestId": "req-1",
        "actor": "tok",
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }
    return v.handler([{"body": json.dumps(body)}], None)


def _read_paths(parameters: dict) -> set[str]:
    """The top-level keys a Pass state's Parameters block reads from its input.

    Args:
      parameters: The state's ``Parameters``.

    Returns:
      The first path segment of every ``$.x`` reference.

    Raises:
      None.
    """
    reads = set()
    for key, value in (parameters or {}).items():
        if key.endswith(".$") and isinstance(value, str) and value.startswith("$."):
            reads.add(value[2:].split(".")[0])
    return reads


def _planned_output() -> dict:
    """inspect-source's real return value, driven off validate-authorize's real output.

    Chained rather than hand-fed for the same reason ``_validated_output`` drives the handler:
    a fixture written by hand would agree with a hand-written ASL assertion and prove nothing
    about the two states this file exists to hold together.

    Args:
      None.

    Returns:
      The planned request the machine's terminal state consumes.

    Raises:
      None.
    """

    class _FakeS3:
        def get_paginator(self, name):
            class _P:
                def paginate(self, Bucket, Prefix):
                    yield {"Contents": []}

            return _P()

        def head_object(self, Bucket, Key):
            return {"ContentLength": 512}

        def put_object(self, **kwargs):
            return {}

    clients._s3 = _FakeS3()
    return i.handler(_validated_output(), None)


def _task_output_prefix(states: dict, task_name: str) -> str:
    """The JSONPath prefix at which a task's output sits when the state after it runs.

    DERIVED FROM THE MACHINE, never hard-coded, and that is the whole point of this helper. An
    earlier version of this file matched the literal ``"$.result.validated."`` — so deleting the
    ``ResultSelector`` or renaming the ``ResultPath`` left every assertion below passing against
    a machine that raised an uncatchable ``States.Runtime`` on its first real execution.
    Verified by mutation: both edits kept the whole suite green.

    Args:
      states: The machine's states.
      task_name: The task whose output plumbing to follow.

    Returns:
      The prefix the next state's Parameters must read through, e.g. ``"$."``.

    Raises:
      AssertionError: If the task's output plumbing is a shape this cross-check cannot follow,
        which is itself a finding rather than something to route around.
    """
    task = states[task_name]
    result_path = task.get("ResultPath")
    output_path = task.get("OutputPath")

    if output_path is not None:
        assert output_path == "$.Payload", (
            f"the task's OutputPath is {output_path!r}: the state after it is no longer the "
            f"verb's return value, and every JSONPath below reads the wrong object"
        )
        assert result_path is None, "OutputPath and ResultPath together — pick one"
        return "$."

    selector = task.get("ResultSelector") or {}
    assert list(selector.values()) == ["$.Payload"], (
        f"the task keeps its result under {selector!r} rather than selecting the Lambda "
        f"Payload — $.result would carry the invoke envelope, not the verb's output"
    )
    key = next(iter(selector)).removesuffix(".$")
    return f"{result_path}.{key}."


def _reads_through(states: dict, task_name: str, pass_name: str) -> set[str]:
    """The verb-output keys a Pass state reads, at whatever prefix the machine uses.

    Args:
      states: The machine's states.
      task_name: The task whose output the Pass consumes.
      pass_name: The Pass state doing the reading.

    Returns:
      The leaf key names.

    Raises:
      None.
    """
    prefix = _task_output_prefix(states, task_name)
    return {
        value[len(prefix) :]
        for key, value in states[pass_name]["Parameters"].items()
        if key.endswith(".$") and str(value).startswith(prefix)
    }


def _validated_reads(states: dict) -> set[str]:
    """The keys ``Validated`` reads out of validate-authorize's output."""
    return _reads_through(states, "ValidateAuthorize", "Validated")


def _planned_reads(states: dict) -> set[str]:
    """The keys ``Planned`` reads out of inspect-source's output."""
    return _reads_through(states, "InspectSource", "Planned")


def test_the_success_path_reads_only_keys_the_verb_emits():
    """The happy-path half nothing else covers."""
    states = _machine()["States"]
    validated = _validated_output()

    reads = _validated_reads(states)

    assert reads, "the Validated state reads nothing through the task's output path"
    assert reads <= set(validated), (
        f"the machine reads {sorted(reads - set(validated))} which validate-authorize does not "
        f"return — an absent key raises an uncatchable States.Runtime on the SUCCESS path"
    )


def test_the_verb_emits_nothing_the_machine_silently_drops():
    """The other direction, which is not a crash but a contract drift: a field the verb went to
    the trouble of computing and that no state carries forward is either dead or a bug."""
    states = _machine()["States"]

    assert set(_validated_output()) == _validated_reads(states)


def test_the_planned_state_reads_only_keys_inspect_source_emits():
    """The same cross-check one state further on (SPEC-165). A Task hands its output on whole,
    so nothing between two Tasks would notice a renamed field — this Pass is where it fails."""
    states = _machine()["States"]

    reads = _planned_reads(states)

    assert reads, "the Planned state reads nothing through the task's output path"
    assert reads <= set(_planned_output()), (
        f"the machine reads {sorted(reads - set(_planned_output()))} which inspect-source does "
        f"not return — an absent key raises an uncatchable States.Runtime on the SUCCESS path"
    )


def test_inspect_source_emits_nothing_the_machine_silently_drops():
    """The other direction: the plan key, the count and the byte total are what SPEC-166 reads,
    and a field the verb computed that no state carries forward is either dead or a bug."""
    assert set(_planned_output()) == _planned_reads(_machine()["States"])


@pytest.mark.parametrize("task", ["ValidateAuthorize", "InspectSource"])
def test_the_task_output_plumbing_is_the_shape_the_cross_check_assumes(task):
    """Stated on its own so a mutation to the plumbing fails HERE, with a message about the
    plumbing, rather than as a confusing key mismatch two tests away."""
    assert _task_output_prefix(_machine()["States"], task) == "$."


def test_the_failure_seed_recovers_the_request_from_the_context_object():
    """SPEC-152's guarantee on this plane depends on this one JSONPath.

    The validate task's input is the raw SQS ARRAY, so its Catch has no object to merge into
    and the error REPLACES the state — the request, and with it the only copy of the caller's
    token, is gone. ``$$.Execution.Input`` is the surviving copy, and without it notify-failure
    takes its no-recipient branch on every single failure: satisfied on paper, silent in
    practice, on exactly the cold-start and timeout failures the state exists for.

    Reading it from the CONTEXT rather than threading it through the state is also what keeps
    the payload honest — the Pipe record carries the same selection again as an escaped string,
    so threading it would roughly double the state for the whole run.
    """
    states = _machine()["States"]
    seed = states["ValidateFailureSeed"]["Parameters"]

    assert seed.get("raw.$") == "$$.Execution.Input"
    assert seed.get("error.$") == "$", "the seed must capture the error the Catch replaced the state with"
    assert "raw" in _read_paths(states["RecordFailure"]["Parameters"])


def test_the_request_is_not_threaded_through_the_success_path():
    """The payload cost of the alternative, pinned. Both places the request could ride are
    checked: the task's own output, and the notifier's merge-back."""
    states = _machine()["States"]

    assert "raw" not in _validated_reads(states)
    assert states["NotifyFailure"].get("ResultPath", "unset") is None, (
        "NotifyFailure merges its result back onto a state that already carries the whole "
        "request — nothing reads $.notified, and the copy can breach the payload limit"
    )


def test_the_verb_is_handed_the_pipes_batch_unwrapped():
    """The validator reads record[0] of the raw SQS array; anything else makes every request
    malformed."""
    task = _machine()["States"]["ValidateAuthorize"]

    assert task["Parameters"]["Payload.$"] == "$"


@pytest.mark.parametrize("state", ["ValidateFailureSeed", "RecordFailure"])
def test_the_failure_terminal_reads_only_seeded_keys(state):
    """A narrower restatement of the fleet guard, kept local so this plane's own suite fails
    on it rather than a shared one three directories away."""
    states = _machine()["States"]
    seeded = set(states["ValidateFailureSeed"]["Parameters"]) | {
        k.removesuffix(".$") for k in states["ValidateFailureSeed"]["Parameters"]
    }

    assert _read_paths(states[state]["Parameters"]) <= seeded


def _catches(states: dict):
    """Every ``(failing task, catch, keys addressable when it fires)`` on this machine.

    The third element is what makes the walk below able to check the catch TARGET rather than
    trusting it, and it is derived from the machine rather than listed. Two rules, both of them
    Step Functions' own:

    * With a ``ResultPath`` of ``$.x``, the error is merged INTO the task's input, so the state
      is that input plus ``x``. The input is whatever the preceding Pass emitted.
    * Without one, the error REPLACES the state, so nothing is addressable at ``$.something`` —
      which is why a pre-identity seed can only read the context object.
    """
    predecessor = {
        state["Next"]: name
        for name, state in states.items()
        if state.get("Next")
    }
    for name, state in states.items():
        for catch in state.get("Catch", []) or []:
            if not catch.get("Next"):
                continue
            before = states.get(predecessor.get(name) or "", {})
            available = (
                {k.removesuffix(".$") for k in before.get("Parameters", {})}
                if before.get("Type") == "Pass"
                else set()
            )
            result_path = catch.get("ResultPath", "$")
            if result_path == "$":
                available = set()
            elif result_path is not None:
                available |= {str(result_path)[2:].split(".")[0]}
            yield name, catch["Next"], available


def test_every_catch_reaches_a_terminal_that_reads_only_supplied_keys():
    """THE GUARD THE FLEET TEST CANNOT SEE ON THIS PLANE, and the reason is worth stating.

    ``test_a_failure_seed_supplies_every_key_the_failure_terminal_reads`` identifies a seed
    STRUCTURALLY, as a Pass whose ``error.$`` is ``"$"`` — the shape a pre-identity catch has,
    where the error REPLACED the state. SPEC-165's ``InspectFailureSeed`` is the other shape: its
    task's input is the request object, so its Catch carries a ``ResultPath`` and the error
    arrives at ``$.error`` alongside. The fleet walk skips it entirely.

    That is not academic here. ``RecordFailure`` on this plane reads ``$.raw``, which exists on
    NO post-validate state — the request is deliberately not threaded through, because the Pipe
    record carries the selection again as an escaped string. A catch routed straight to
    ``RecordFailure``, as every other plane's catches are, would raise an uncatchable
    ``States.Runtime`` and the sender would hear nothing on exactly the failures SPEC-152 exists
    to report. So this walks every Catch target forward and requires what it supplies to cover
    what the Passes downstream read.
    """
    states = _machine()["States"]

    for failing, entry, available in sorted(_catches(states)):
        supplied, frontier, seen = set(available), [entry], set()
        while frontier:
            name = frontier.pop()
            if not name or name in seen or name not in states:
                continue
            seen.add(name)
            state = states[name]
            if state.get("Type") == "Pass":
                missing = _read_paths(state["Parameters"]) - supplied
                assert not missing, (
                    f"a {failing} failure reaches {name}, which reads {sorted(missing)} that is "
                    f"not on the state by then — an uncatchable States.Runtime, and the sender "
                    f"is never notified"
                )
                supplied |= {k.removesuffix(".$") for k in state["Parameters"]}
            # Catch edges as well as Next: SPEC-165's machine has no Pass behind a catch on a
            # failure path, so following only Next passes today — and SPEC-166 adds states here.
            # The fleet walk follows both; a local walk that did not would be the narrower guard
            # of the two exactly where this plane needs the wider one.
            frontier.append(state.get("Next"))
            frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])


def test_the_catch_walk_actually_walked_something():
    """Guards the guard: a machine whose catches stopped being found would pass vacuously."""
    catches = list(_catches(_machine()["States"]))

    assert {"ValidateFailureSeed", "InspectFailureSeed", "Failed"} == {t for _f, t, _a in catches}
    assert any(available for _f, _t, available in catches), (
        "no catch on this machine preserves anything — the availability model has gone trivial "
        "and every assertion above passes against an empty set"
    )


def test_the_inspect_catch_makes_the_validated_request_available():
    """The availability model at the one catch it matters for, stated so a mutation to the
    derivation fails HERE rather than as a confusing missing key in the walk.

    On a Task failure with a ``ResultPath``, Step Functions merges the error into the task's
    INPUT — so what survives is whatever ``Validated`` emitted plus ``error``, and NOT the
    fields inspect-source would have added. A seed reading the plan key would look perfectly
    reasonable and die on every failure, because the verb that produces it is the one that just
    failed.
    """
    states = _machine()["States"]
    available = [a for failing, _t, a in _catches(states) if failing == "InspectSource"]
    expected = {k.removesuffix(".$") for k in states["Validated"]["Parameters"]} | {"error"}

    assert available == [expected]


def test_the_post_validate_catch_keeps_the_verified_actor():
    """Without ``ResultPath`` the error REPLACES the state, and the verified username goes with
    it — the shared-space mistake SPEC-152 recorded, where the actor was silently discarded and
    every failure notified nobody. Here the actor is on the state by then, so the fix is one
    field rather than a token re-verification."""
    catches = _machine()["States"]["InspectSource"]["Catch"]

    assert [c["ResultPath"] for c in catches] == ["$.error"]
    assert _machine()["States"]["InspectFailureSeed"]["Parameters"]["actor.$"] == "$.actor"


# ── SPEC-166 FR-004: which role holds which grant ───────────────────────────

_MODULE = _HERE.parent.parent / "infra" / "modules" / "file-send"
_SFN_POLICY = _MODULE / "policies" / "sfn-permissions.json.tftpl"
_EXECUTION_POLICY = _MODULE / "policies" / "execution.json.tftpl"


def _policy(path):
    """The rendered policy.

    A bare placeholder in a value position (the ``jsonencode``d ARN list) is stubbed to a
    string, a quoted one to its contents — the same two-step the ASL above needs.

    Args:
      path: The policy template.

    Returns:
      The parsed policy document.

    Raises:
      None.
    """
    raw = re.sub(r":\s*\$\{[^}]+\}", ': "STUB"', path.read_text())
    return json.loads(re.sub(r"\$\{[^}]+\}", "STUB", raw))


def _raw_policy(path):
    """The policy with each placeholder left as its own NAME rather than one shared literal.

    ``_policy`` collapses every ARN placeholder to ``STUB``, which cannot tell the admin bucket
    from the two space buckets — so a resource-scoping assertion made against it would pass on a
    grant that had stopped covering the bucket it names.

    Args:
      path: The policy template.

    Returns:
      The parsed policy document with named placeholders.

    Raises:
      None.
    """
    return json.loads(re.sub(r"\$\{([a-z_]+)\}", r"\1", path.read_text()))


def _actions(policy):
    """Every action the policy grants or denies, flattened.

    Args:
      policy: A parsed policy document.

    Returns:
      The set of action strings.

    Raises:
      None.
    """
    actions = set()
    for statement in policy["Statement"]:
        action = statement["Action"]
        actions.update([action] if isinstance(action, str) else action)
    return actions


def _resources(statement):
    """One statement's resources as a list, whatever shape it was written in.

    Args:
      statement: One policy statement.

    Returns:
      The resource list.

    Raises:
      None.
    """
    resource = statement["Resource"]
    return resource if isinstance(resource, list) else [resource]


def test_the_state_machine_role_holds_the_distributed_maps_permissions():
    """FR-004 AC3. It is the STATE MACHINE that starts each child execution and that reads the
    ItemReader object and writes the ResultWriter export."""
    actions = _actions(_policy(_SFN_POLICY))

    assert "states:StartExecution" in actions
    assert "states:DescribeExecution" in actions
    assert {"s3:GetObject", "s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"} <= actions


def test_the_lambda_execution_role_gains_nothing_from_the_map():
    """FR-004 AC3 — THE SWAP NOTHING ELSE WOULD CATCH. Granting these to the execution role
    renders green, applies green and passes every other policy assertion in this repo; it fails
    on the first real send, at the ItemReader, with an AccessDenied naming a role nobody was
    looking at. Inherited from SPEC-160 FR-006 rather than rediscovered."""
    actions = _actions(_policy(_EXECUTION_POLICY))

    assert not {a for a in actions if a.startswith("states:")}, (
        "the Distributed Map's states: actions are on the LAMBDA execution role"
    )


def test_stop_execution_is_not_granted():
    """Nothing here stops a child; StartExecution + DescribeExecution is the documented
    least-privilege pair."""
    assert "states:StopExecution" not in _actions(_policy(_SFN_POLICY))


def test_the_only_write_into_a_users_space_is_an_inbox():
    """FR-004 AC1. The scoping is the isolation: this role is on the user-space bucket's
    principal allowlist, so an unscoped PutObject would let a bug in any verb write anywhere in
    anybody's prefix. Read from the NAMED-placeholder form, because the collapsed one cannot
    tell the two data buckets from the admin bucket."""
    writes = [
        statement
        for statement in _raw_policy(_EXECUTION_POLICY)["Statement"]
        if statement["Effect"] == "Allow" and "s3:PutObject" in _actions({"Statement": [statement]})
    ]
    into_user_space = [
        resource
        for statement in writes
        for resource in _resources(statement)
        if resource.startswith(("user_space_bucket_arn", "shared_space_bucket_arn"))
    ]

    assert into_user_space, "the copy has no destination grant at all"
    assert all("/shared_files/" in resource for resource in into_user_space), (
        f"a write into user space is not scoped to an inbox: {into_user_space}"
    )


def test_the_inbox_grant_carries_the_multipart_actions_a_large_object_needs():
    """FR-002 AC6. An object over S3's 5 GiB single-copy limit takes UploadPartCopy, and the
    copier aborts a failed upload so it never leaves one accruing storage. Missing either, a
    large send fails at the object rather than at the plan."""
    inbox = next(
        statement
        for statement in _raw_policy(_EXECUTION_POLICY)["Statement"]
        if statement.get("Sid") == "SharedFilesWrite"
    )

    assert {"s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"} == set(
        inbox["Action"]
    )


def test_the_delete_deny_still_covers_every_bucket_this_plane_touches():
    """FR-004 AC2. A send is a copy: it never deletes the sender's copy and never overwrites at
    the destination, so the Deny makes "this plane deletes nothing" structural rather than
    behavioural — including over the admin bucket, whose artifacts a lifecycle rule expires."""
    deny = next(
        statement
        for statement in _raw_policy(_EXECUTION_POLICY)["Statement"]
        if statement["Effect"] == "Deny" and statement["Action"] == "s3:DeleteObject"
    )

    assert set(_resources(deny)) == {
        "user_space_bucket_arn/*",
        "shared_space_bucket_arn/*",
        "admin_bucket_arn/*",
    }


def test_no_new_wildcard_resource_appears():
    """FR-004 AC5 — the SPEC-139 plan scan's IAM findings must not grow. The one pre-existing
    ``Resource: "*"`` is Step Functions' own log delivery, which has no ARN to scope to; this
    pins the count at that one rather than forbidding it."""
    for path in (_SFN_POLICY, _EXECUTION_POLICY):
        wildcards = [s.get("Sid") for s in _policy(path)["Statement"] if s["Resource"] == "*"]
        assert wildcards in ([], ["StepFunctionLogDelivery"]), f"new wildcards in {path.name}: {wildcards}"
