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

import fnmatch
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
sys.path.insert(0, str(_HERE.parent / "file-send-build-transfer-manifest"))
sys.path.insert(0, str(_HERE.parent / "file-send-check-target-absent"))
sys.path.insert(0, str(_HERE.parent / "file-send-collect-transfer-results"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_build_transfer_manifest as b
import file_send_collect_transfer_results as c
import file_send_inspect_source as i
import file_send_validate_authorize as v
from cpcommon import clients

_ASL = _HERE.parent.parent / "infra" / "modules" / "file-send" / "state-machine.asl.json.tftpl"


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
    v.reg.load = lambda name: None
    v.cognito.user_exists = lambda name: True
    body = {
        "requestId": "req-1",
        "identity": {"actor": "alice", "delegated_by": None, "assurance": "interactive"},
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }
    return v.handler([{"body": json.dumps(body)}], None)


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
        """An S3 that SERVES BACK what was written to it.

        The chain below drives four real verbs in sequence, and the third of them reads the copy
        plan the second wrote. A fake that swallowed the write and 404'd the read would make the
        manifest verb unreachable here — and it is the verb whose contract with the machine the
        couplings at the end of this file exist to check.
        """

        def __init__(self):
            self.objects = {}

        def get_paginator(self, name):
            class _P:
                def paginate(self, Bucket, Prefix, **kwargs):
                    yield {"Contents": [], "CommonPrefixes": []}

            return _P()

        def head_object(self, Bucket, Key):
            return {"ContentLength": 512}

        def put_object(self, Bucket, Key, Body, **kwargs):
            self.objects[Key] = Body
            return {}

        def get_object(self, Bucket, Key):
            class _B:
                def __init__(self, payload):
                    self._payload = payload

                def read(self):
                    return self._payload

            return {"Body": _B(self.objects[Key])}

    clients._s3 = _FakeS3()
    return i.handler(_validated_output(), None)


#: The guard record a REFUSED recipient produces. Used to drive the two verbs after the guard
#: without any S3 at all: with nobody accepted the manifest is skipped and the collector has no
#: export to read, which is the machine's own "everybody already had it" path.
_REFUSED = {
    "status": "failed",
    "recipient": {"kind": "user", "name": "bob"},
    "reason": "conflict",
    "detail": "notes.txt",
}


def _manifest_output() -> dict:
    """build-transfer-manifest's real return value, driven off inspect-source's real output.

    Args:
      None.

    Returns:
      The request with its ``transfer`` block.

    Raises:
      None.
    """
    return b.handler({**_planned_output(), "guardResults": [_REFUSED]}, None)


def _summary_output() -> dict:
    """collect-transfer-results' real return value, driven off the manifest verb's real output.

    Args:
      None.

    Returns:
      The request the terminal summary is shaped from.

    Raises:
      None.
    """
    return c.handler(_manifest_output(), None)


#: The real return value of every Task whose ``OutputPath`` makes the verb's output the whole
#: state. Chained from one another rather than written down, so the availability model below is
#: derived from what the verbs actually emit — a hand-written fixture would agree with a
#: hand-written assertion and prove nothing.
_TASK_OUTPUTS = {
    "ValidateAuthorize": _validated_output,
    "InspectSource": _planned_output,
    "BuildTransferManifest": _manifest_output,
    "CollectTransferResults": _summary_output,
}


def _exit_keys(name: str, state: dict, entry: set) -> set:
    """The top-level keys addressable AFTER a state runs.

    Step Functions' own three rules, and nothing else: an ``OutputPath`` of ``$.Payload``
    replaces the state with the verb's return value, a ``ResultPath`` of ``$.x`` adds one key to
    what was already there, and a ``Pass`` with ``Parameters`` emits exactly what it names.

    Args:
      name: The state's name, which is how its verb's real output is found.
      state: The state.
      entry: The keys addressable on entry.

    Returns:
      The keys addressable on exit.

    Raises:
      None.
    """
    if state.get("Type") == "Pass" and not state.get("ResultPath"):
        return {key.removesuffix(".$") for key in state.get("Parameters", {})}
    if state.get("OutputPath") == "$.Payload":
        # NOT a fallback to `entry`: a Task whose output replaces the state and whose real
        # output this file does not know is a model that has quietly gone wrong, and every
        # availability set downstream of it would be stale while still passing.
        assert name in _TASK_OUTPUTS, (
            f"{name} replaces the state with its verb's output, which this model does not know "
            f"— add it to _TASK_OUTPUTS or the catch walk below is checking a stale key set"
        )
        return set(_TASK_OUTPUTS[name]())
    result_path = state.get("ResultPath")
    if isinstance(result_path, str) and result_path.startswith("$."):
        return entry | {result_path[2:].split(".")[0]}
    return entry


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
    raw = re.sub(r":\s*\$\{([a-z_]+)\}", r': "\1"', path.read_text())
    return json.loads(re.sub(r"\$\{([a-z_]+)\}", r"\1", raw))


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


def _machine() -> dict:
    """The state machine, with template placeholders neutralised so it parses as JSON.

    Args:
      None.

    Returns:
      The parsed ASL document.

    Raises:
      None.
    """
    # Two steps, because a placeholder in a VALUE position is a number (TimeoutSeconds,
    # MaxConcurrency) and a quoted one is a string.
    raw = re.sub(r":\s*\$\{[a-z_0-9]+\}", ": 0", _ASL.read_text())
    return json.loads(re.sub(r"\$\{[a-z_0-9]+\}", "PLACEHOLDER", raw))


def _validated_reads(states: dict) -> set[str]:
    """The keys ``Validated`` reads out of validate-authorize's output."""
    return _reads_through(states, "ValidateAuthorize", "Validated")


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


def test_the_only_write_into_a_users_space_is_an_inbox():
    """FR-004 AC1. The scoping is the isolation: this role is on the user-space bucket's
    principal allowlist, so an unscoped PutObject would let a bug in any verb write anywhere in
    anybody's prefix. Read from the NAMED-placeholder form, because the collapsed one cannot
    tell the two data buckets from the admin bucket.

    Matched by GLOB rather than by the literal action, so a statement widened to ``s3:*`` or
    ``s3:Put*`` is caught as the write it is instead of slipping past a name comparison."""
    writes = [
        statement
        for statement in _raw_policy(_EXECUTION_POLICY)["Statement"]
        if statement["Effect"] == "Allow"
        and any(
            fnmatch.fnmatch("s3:PutObject", action)
            for action in _actions({"Statement": [statement]})
        )
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


def test_the_delete_deny_still_covers_every_bucket_this_plane_touches():
    """FR-004 AC2. A send is a copy: it never deletes the sender's copy and is meant never to
    overwrite at the destination, so the Deny makes "this plane deletes nothing" structural
    rather than behavioural — including over the admin bucket, whose artifacts a lifecycle rule
    expires."""
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


# ── SPEC-166 FR-002: the Distributed Map's own shape ────────────────────────


def _states_including_map_items(states: dict, prefix: str = ""):
    """Every state, including the ones inside a Map's ItemProcessor.

    Args:
      states: A states block.
      prefix: The qualified-name prefix for nested states.

    Yields:
      ``(qualified name, state)``.

    Raises:
      None.
    """
    for name, state in states.items():
        yield prefix + name, state
        if "ItemProcessor" in state:
            yield from _states_including_map_items(
                state["ItemProcessor"]["States"], f"{prefix}{name}/"
            )


# ── SPEC-166: the couplings a Task-to-Task chain hides ──────────────────────
#
# The three below are the ASL↔verb contracts this file exists for and did not cover: a Map's
# ResultPath, an ItemSelector, and the five field names the Map's own reader and writer take
# from a verb's output. Each was mutation-tested — renaming any of them left the whole suite
# green while the machine produced a send that reported success and copied nothing.


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


@pytest.mark.parametrize("state", ["ValidateFailureSeed", "RecordFailure"])
def test_the_failure_terminal_reads_only_seeded_keys(state):
    """A narrower restatement of the fleet guard, kept local so this plane's own suite fails
    on it rather than a shared one three directories away."""
    states = _machine()["States"]
    seeded = set(states["ValidateFailureSeed"]["Parameters"]) | {
        k.removesuffix(".$") for k in states["ValidateFailureSeed"]["Parameters"]
    }

    assert _read_paths(states[state]["Parameters"]) <= seeded
