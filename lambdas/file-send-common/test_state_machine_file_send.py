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
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_build_transfer_manifest as b
import file_send_check_target_absent as g
import file_send_collect_transfer_results as c
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
    # Two steps, because a placeholder in a VALUE position is a number (TimeoutSeconds,
    # MaxConcurrency) and a quoted one is a string.
    raw = re.sub(r":\s*\$\{[a-z_0-9]+\}", ": 0", _ASL.read_text())
    return json.loads(re.sub(r"\$\{[a-z_0-9]+\}", "PLACEHOLDER", raw))


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


def _entry_keys(states: dict) -> dict:
    """What is addressable on entry to every state on the SUCCESS path, derived by walking it.

    This is the model the catch walk needs, and deriving it is the whole point: the earlier
    version read the immediately preceding ``Pass``, which was true while the machine was two
    Tasks and silently gave up the moment a Map or a Choice sat between them — reporting an
    empty set, which every assertion passes against.

    A state reachable by two paths gets the INTERSECTION of what they supply, because a key that
    only one branch adds is not one a downstream state may read. ``mapRun`` is exactly that: the
    Choice's skip branch reaches the collector without it.

    Args:
      states: The machine's states.

    Returns:
      State name to the set of top-level keys addressable on entry.

    Raises:
      None.
    """
    entry = {"ValidateAuthorize": set()}
    frontier = ["ValidateAuthorize"]
    while frontier:
        name = frontier.pop()
        state = states[name]
        out = _exit_keys(name, state, entry[name])
        targets = [state.get("Next")] if state.get("Next") else []
        if state.get("Type") == "Choice":
            targets = [choice["Next"] for choice in state["Choices"]] + [state.get("Default")]
        for target in targets:
            if not target or target not in states:
                continue
            merged = out if target not in entry else entry[target] & out
            if target not in entry or merged != entry[target]:
                entry[target] = merged
                frontier.append(target)
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


def test_the_summary_reads_only_keys_the_collector_emits():
    """The same cross-check at the machine's OTHER end (SPEC-166). ``ShapeSummary`` is the last
    Pass and the execution's output, so a key renamed between the collector and it kills a run
    that has already copied everything — the most expensive moment on this plane to fail.

    Read as first path SEGMENTS, because the summary reaches into ``$.actor.username``: a
    JSONPath into an absent PARENT is the same uncatchable States.Runtime as a missing key.
    """
    states = _machine()["States"]
    reads = {path.split(".")[0] for path in _reads_through(states, "CollectTransferResults", "ShapeSummary")}

    assert reads, "the summary reads nothing through the collector's output path"
    assert reads <= set(_summary_output()), (
        f"the machine reads {sorted(reads - set(_summary_output()))} which "
        f"collect-transfer-results does not return"
    )


def test_the_summary_carries_everything_SPEC_167_notifies_from():
    """The other direction, and narrower than "every key the verb emits" deliberately: the
    collector passes the whole request through, so most of what it returns is plumbing the
    terminal is right to drop. What the summary must NOT drop is the four things a notification
    is built from — who sent it, what they sent, how much of it, and every recipient's outcome.
    """
    emitted = set(_machine()["States"]["ShapeSummary"]["Parameters"])

    assert {"sender.$", "itemNames.$", "objectCount.$", "recipients.$"} <= emitted


def test_the_summary_drops_what_the_run_no_longer_needs():
    """The state that becomes the execution OUTPUT should not carry the plan key, the transfer
    block or the selection: they are the heaviest terms on the state and nothing downstream
    reads them."""
    emitted = {key.removesuffix(".$") for key in _machine()["States"]["ShapeSummary"]["Parameters"]}

    assert not emitted & {"copyPlanKey", "transfer", "mapRun", "guardResults", "source"}


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
      is that input plus ``x``. The input is what ``_entry_keys`` derived by walking the success
      path — which is what makes this work across a Map and a Choice, where reading the
      immediately preceding ``Pass`` gave an empty set and every assertion passed vacuously.
    * Without one, the error REPLACES the state, so nothing is addressable at ``$.something`` —
      which is why a pre-identity seed can only read the context object.
    """
    on_entry = _entry_keys(states)
    for name, state in states.items():
        # A Map's ItemProcessor states are walked with the ITEM as their input, which is what
        # the ItemSelector builds — the guard's per-item Catch is a Pass reading two JSONPaths
        # on a failure path, which is exactly what this file exists to guard and was the one
        # such Pass the walk could not see.
        if "ItemProcessor" in state:
            item_keys = {key.removesuffix(".$") for key in state.get("ItemSelector", {})}
            for inner, inner_state in state["ItemProcessor"]["States"].items():
                for catch in inner_state.get("Catch", []) or []:
                    if not catch.get("Next"):
                        continue
                    result_path = catch.get("ResultPath", "$")
                    available = set(item_keys) if result_path != "$" else set()
                    if result_path not in (None, "$"):
                        available |= {str(result_path)[2:].split(".")[0]}
                    yield f"{name}/{inner}", f"{name}/{catch['Next']}", available
        for catch in state.get("Catch", []) or []:
            if not catch.get("Next"):
                continue
            available = set(on_entry.get(name, set()))
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
    nested = {
        f"{name}/{inner}": inner_state
        for name, state in states.items()
        if "ItemProcessor" in state
        for inner, inner_state in state["ItemProcessor"]["States"].items()
    }
    reachable = {**states, **nested}

    for failing, entry, available in sorted(_catches(states)):
        supplied, frontier, seen = set(available), [entry], set()
        while frontier:
            name = frontier.pop()
            if not name or name in seen or name not in reachable:
                continue
            seen.add(name)
            state = reachable[name]
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

    assert {
        "ValidateFailureSeed",
        "RequestFailureSeed",
        "Failed",
        "GuardRecipients/RecipientFaulted",
    } == {t for _f, t, _a in catches}
    assert any(available for _f, _t, available in catches), (
        "no catch on this machine preserves anything — the availability model has gone trivial "
        "and every assertion above passes against an empty set"
    )


def test_every_post_validate_catch_reaches_the_one_shared_seed():
    """SPEC-166 added four more catches, and every one of them must land on the seed that
    supplies ``$.raw`` — the field ``RecordFailure`` reads unconditionally and which no
    post-validate state carries. A catch routed straight at ``RecordFailure``, as every other
    plane's are, raises an uncatchable States.Runtime BEFORE ``NotifyFailure``."""
    states = _machine()["States"]
    post_validate = {
        failing: target
        for failing, target, _a in _catches(states)
        if failing != "ValidateAuthorize" and "/" not in failing
    }

    assert post_validate == {
        "InspectSource": "RequestFailureSeed",
        "GuardRecipients": "RequestFailureSeed",
        "BuildTransferManifest": "RequestFailureSeed",
        "TransferObjects": "RequestFailureSeed",
        "CollectTransferResults": "RequestFailureSeed",
        "NotifyFailure": "Failed",
    }


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
    assert _machine()["States"]["RequestFailureSeed"]["Parameters"]["actor.$"] == "$.actor"


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


def test_the_state_machine_role_holds_the_distributed_maps_permissions():
    """FR-004 AC3. It is the STATE MACHINE that starts each child execution and that reads the
    ItemReader object and writes the ResultWriter export."""
    actions = _actions(_policy(_SFN_POLICY))

    assert "states:StartExecution" in actions
    assert "states:DescribeExecution" in actions
    assert {"s3:GetObject", "s3:PutObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"} <= actions


def test_the_lambda_execution_role_gains_nothing_from_the_map():
    """FR-004 AC3 — THE SWAP NOTHING ELSE WOULD CATCH. Granting the Map's permissions to the
    execution role renders green, applies green and passes every other policy assertion in this
    repo; it fails on the first real send, at the ItemReader, with an AccessDenied naming a role
    nobody was looking at. Inherited from SPEC-160 FR-006 rather than rediscovered.

    It is asserted as ``StartExecution`` plus a named allowance rather than "no states: actions
    at all", because SPEC-166 gave this role one of its own: the timeout door reads a timed-out
    execution's input back, from a Lambda EventBridge invokes outside any execution. A blanket
    rule would have had to be deleted to add it, taking the guard with it.
    """
    statements = {
        s.get("Sid"): s
        for s in _raw_policy(_EXECUTION_POLICY)["Statement"]
        if any(a.startswith("states:") for a in _actions({"Statement": [s]}))
    }

    assert "states:StartExecution" not in _actions(_policy(_EXECUTION_POLICY)), (
        "the Distributed Map's StartExecution is on the LAMBDA execution role"
    )
    assert set(statements) == {"ReadTimedOutExecutionInput"}, (
        f"the execution role has states: actions beyond the timeout door: {sorted(statements)}"
    )
    assert statements["ReadTimedOutExecutionInput"]["Action"] == "states:DescribeExecution"


def test_stop_execution_is_not_granted():
    """Nothing here stops a child; StartExecution + DescribeExecution is the documented
    least-privilege pair."""
    assert "states:StopExecution" not in _actions(_policy(_SFN_POLICY))


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


def test_the_transfer_grants_name_THIS_planes_prefix_and_machine():
    """The copy-paste this file's own provenance makes likely, and the one thing the action-set
    assertions above cannot see.

    ``_policy`` collapses every ARN placeholder to one literal, so a policy still pointing at
    ``${admin_bucket_arn}/table-share/*`` — or starting executions of table-share's machine —
    renders, applies and passes every other test here, then fails on the first real send at the
    ItemReader. Read from the NAMED-placeholder form, where those two are different strings.
    """
    statements = {s["Sid"]: s for s in _raw_policy(_SFN_POLICY)["Statement"]}

    for sid in ("ReadTransferManifest", "WriteTransferResults"):
        assert _resources(statements[sid]) == ["admin_bucket_arn/file-send/*"], (
            f"{sid} does not scope to this plane's own admin-bucket prefix"
        )
    assert _resources(statements["StartDistributedMapChildExecutions"]) == ["state_machine_arn"]
    assert _resources(statements["DescribeDistributedMapChildExecutions"]) == [
        "child_execution_arn_wildcard"
    ]


def test_the_copy_timeout_matches_this_planes_deployed_verb():
    """The budget every makespan bound in ``cpcommon.transfer`` divides by, held against the
    function that actually has it.

    The equivalent test in ``control-plane-common`` reads TABLE-SHARE's locals and nothing else,
    so before this one, lowering file-send's ``copy-objects`` timeout would have left the engine
    computing batch sizes against a budget this plane no longer had — with a green suite.
    """
    from cpcommon.transfer import config as transfer_config

    locals_tf = (_HERE.parent.parent / "infra" / "modules" / "file-send" / "locals.tf").read_text()

    assert re.search(
        rf'"copy-objects"\s*=\s*\{{[^}}]*timeout\s*=\s*{transfer_config.COPY_TIMEOUT_SECONDS}\b',
        locals_tf,
    ), f"file-send's copy-objects timeout is not {transfer_config.COPY_TIMEOUT_SECONDS}s"


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


def _distributed_maps(states: dict):
    """Every state whose ItemProcessor runs in DISTRIBUTED mode, qualified by nesting."""
    return [
        name
        for name, state in _states_including_map_items(states)
        if (state.get("ItemProcessor") or {}).get("ProcessorConfig", {}).get("Mode") == "DISTRIBUTED"
    ]


def test_the_transfer_map_is_top_level_and_not_nested():
    """FR-002 AC3, and the reason the copy is not simply the guard Map's third step: a
    Distributed Map inside another Map is the structure SPEC-160 rejected, because one fan-out
    over a flat (recipient x object) manifest covers every recipient and the nesting question
    never arises. Asserted on the QUALIFIED name, so a Map moved inside the guard fails here."""
    maps = _distributed_maps(_machine()["States"])

    assert maps == ["TransferObjects"], f"the distributed maps are {maps}"


def test_the_guard_map_stays_inline():
    """It is one listing per recipient whose refusal must not abort a sibling — a distributed
    fan-out would buy nothing and cost a child execution each."""
    guard = _machine()["States"]["GuardRecipients"]

    assert guard["ItemProcessor"]["ProcessorConfig"] == {"Mode": "INLINE"}
    assert guard["ItemProcessor"]["States"]["CheckTargetAbsent"]["Catch"][0]["Next"] == "RecipientFaulted"


def test_the_children_are_STANDARD_and_tolerate_every_item_failure():
    """Both halves of FR-003's premise. STANDARD because a batch may hold a multi-GiB object
    whose multipart copy would blow EXPRESS's five-minute ceiling, and because EXPRESS's
    at-least-once semantics would re-run whole batches. ToleratedFailurePercentage 100 because
    the Map Run MUST finish for the collector to attribute it — a run that failed would take
    every recipient's outcome with it."""
    transfer = _machine()["States"]["TransferObjects"]

    assert transfer["ItemProcessor"]["ProcessorConfig"]["ExecutionType"] == "STANDARD"
    assert transfer["ToleratedFailurePercentage"] == 100


def test_the_batch_copier_has_no_catch_of_its_own():
    """A batch that fails after its retries must FAIL its child execution: that is what files it
    under FAILED_n.json, where the collector can attribute every item it carried. A Catch here
    would succeed the child and lose the whole batch silently."""
    copy_state = _machine()["States"]["TransferObjects"]["ItemProcessor"]["States"]["CopyObjects"]

    assert "Catch" not in copy_state
    assert copy_state["End"] is True


def test_the_map_is_skipped_by_a_choice_that_tests_IsPresent_first():
    """FR-002 AC5. An ItemReader pointed at a manifest that was never written fails the state,
    so the empty case must not reach it — and the guard on that Choice is not optional: a Choice
    on an ABSENT path raises States.Runtime, which is uncatchable and which ``Default`` does NOT
    cover. Asserted as ORDER, because IsPresent second is the bug."""
    choice = _machine()["States"]["HasTransferItems"]
    conditions = choice["Choices"][0]["And"]

    assert conditions[0] == {"Variable": "$.transfer.itemCount", "IsPresent": True}
    assert conditions[1]["NumericGreaterThan"] == 0
    assert choice["Default"] == "CollectTransferResults"


def test_both_choice_branches_reach_the_one_shaping_verb():
    """One verb on both branches rather than two paths that can disagree: on the skip branch
    there is no run to read and the guard's refusals are carried forward unchanged."""
    choice = _machine()["States"]["HasTransferItems"]

    assert choice["Choices"][0]["Next"] == "TransferObjects"
    assert _machine()["States"]["TransferObjects"]["Next"] == "CollectTransferResults"


def test_the_map_exports_its_results_and_keeps_only_the_pointer():
    """The state's own output is the small {MapRunArn, ResultWriterDetails} pointer — an array
    of every child's result would breach the 256 KB state limit at the scale this Map exists
    for, and the breach lands ON the Map, destroying every per-recipient outcome."""
    transfer = _machine()["States"]["TransferObjects"]

    assert transfer["ResultWriter"]["Resource"] == "arn:aws:states:::s3:putObject"
    assert transfer["ResultPath"] == "$.mapRun"
    assert transfer["ItemReader"]["ReaderConfig"]["InputType"] == "JSONL"


def test_the_rendered_batch_numbers_are_the_engines_own():
    """FR-002 AC4. Terraform cannot import Python, so the ASL carries literals fed from
    locals.tf — and the locals are held against ``cpcommon.transfer.config`` by the cap suite.
    What this asserts is the other half: that the ASL reads those locals rather than hard-coding
    numbers beside them."""
    raw = _ASL.read_text()

    assert '"MaxItemsPerBatch": ${transfer_max_items_per_batch}' in raw
    assert '"MaxConcurrency": ${transfer_map_max_concurrency}' in raw


def test_the_machine_declares_a_top_level_timeout():
    """FR-005 AC1. Without it a Standard workflow's ceiling is Step Functions' own default of
    ONE YEAR. TOP-LEVEL, not a task field — the distinction SPEC-157 settled — so it is asserted
    at the document root rather than anywhere it might merely look right."""
    machine = _machine()

    assert "TimeoutSeconds" in machine, "the machine can run for a year"
    assert '"TimeoutSeconds": ${state_machine_timeout_seconds}' in _ASL.read_text()
    assert not any(
        "TimeoutSeconds" in state for _name, state in _states_including_map_items(machine["States"])
    )


# ── SPEC-166: the couplings a Task-to-Task chain hides ──────────────────────
#
# The three below are the ASL↔verb contracts this file exists for and did not cover: a Map's
# ResultPath, an ItemSelector, and the five field names the Map's own reader and writer take
# from a verb's output. Each was mutation-tested — renaming any of them left the whole suite
# green while the machine produced a send that reported success and copied nothing.


def test_the_guard_maps_result_lands_where_the_manifest_verb_reads_it():
    """A Map's ``ResultPath`` is a string in Terraform and a ``.get()`` in Python, and nothing
    joins them. Renamed, ``_accepted()`` sees nothing, every recipient contributes no lines, the
    Map is skipped, and the run reports a SUCCESSFUL send that copied nothing.

    Driven rather than compared: the guard's records are put where the ASL says they go, the
    real verb runs, and the manifest either has lines in it or does not.
    """
    result_path = _machine()["States"]["GuardRecipients"]["ResultPath"]
    cleared = {
        "status": "ok",
        "recipient": {"kind": "user", "name": "bob", "destBucket": "user-bkt", "destRoot": "bob/"},
        "reason": "",
        "detail": "",
    }

    transfer = b.handler({**_planned_output(), result_path[2:]: [cleared]}, None)["transfer"]

    assert transfer["itemCount"] > 0, (
        f"the guard Map writes its records to {result_path} and build-transfer-manifest reads "
        f"none of them — every send would report success having copied nothing"
    )


def test_the_maps_reader_and_writer_read_only_fields_the_manifest_verb_emits():
    """FR-002 AC1/AC4. The ItemReader's Bucket/Key and the ResultWriter's Bucket/Prefix are
    JSONPaths into a block ONE verb produces. A renamed field there is an uncatchable failure at
    the ItemReader on every non-empty send — and the collector reads two more of the same
    block."""
    transfer = _machine()["States"]["TransferObjects"]
    emitted = set(_manifest_output()["transfer"])
    read = {
        transfer["ItemReader"]["Parameters"]["Bucket.$"],
        transfer["ItemReader"]["Parameters"]["Key.$"],
        transfer["ResultWriter"]["Parameters"]["Bucket.$"],
        transfer["ResultWriter"]["Parameters"]["Prefix.$"],
        _machine()["States"]["HasTransferItems"]["Choices"][0]["And"][0]["Variable"],
    }

    fields = {path.removeprefix("$.transfer.") for path in read}
    assert all(path.startswith("$.transfer.") for path in read), read
    assert fields <= emitted, (
        f"the machine reads $.transfer.{sorted(fields - emitted)}, which "
        f"build-transfer-manifest does not emit"
    )


def test_the_guard_map_hands_its_verb_exactly_what_that_verb_reads():
    """The ItemSelector is the other half of the same class of coupling. Dropping ``request.$``
    leaves check-target-absent with no selection — it now fails closed rather than clearing
    everybody, but every send fails, and nothing else in the suite notices.

    Driven through the real verb with the real selector, so what is asserted is that the item
    the machine builds is one the verb can actually work with.
    """
    guard = _machine()["States"]["GuardRecipients"]
    request = _planned_output()
    item = {
        key.removesuffix(".$"): (request if value == "$" else {"kind": "user", "name": "bob"})
        for key, value in guard["ItemSelector"].items()
    }

    record = g.handler(item, None)

    assert record["status"] == "ok", f"the guard cannot work with the item the Map builds: {record}"
    assert guard["ItemsPath"] == "$.recipients"


def test_the_guard_maps_concurrency_comes_from_the_named_local():
    """The cap suite computes the guard's contribution to the machine's timeout budget from
    ``guard_map_max_concurrency``. Hard-coded here instead, that term would be computed from a
    number the machine no longer uses."""
    assert '"MaxConcurrency": ${guard_map_max_concurrency}' in _ASL.read_text()
