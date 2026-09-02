"""The shared-space machine's transfer branch, and the infrastructure the operator door rests on.

Read from the Terraform rather than from a description of it, because every property here is one
that ships green and fails later: a Choice that routes every request into a refusal, a seed the
notifier cannot use, a reader running under the role its own boundary is meant to exclude.
"""

import json
import pathlib
import re

import pytest
from tf_blocks import (
    argument,
    lambda_declaration,
    lambda_input,
    module_calls,
    strip_noise,
)

_MODULE = pathlib.Path(__file__).resolve().parents[2] / "infra" / "modules" / "shared-spaces"
_ASL = _MODULE / "state-machine.asl.json.tftpl"


def _machine():
    """Parses the state machine with its Terraform placeholders stubbed.

    Returns:
      The parsed definition.

    Raises:
      None.
    """
    return json.loads(re.sub(r"\$\{[^}]+\}", "STUB", _ASL.read_text()))


def _states():
    """The machine's states, by name.

    Returns:
      The states mapping.

    Raises:
      None.
    """
    return _machine()["States"]


def test_the_router_has_a_branch_for_the_transfer_verb():
    """FR-001: reached by a new Choice branch on the existing orchestrator."""
    choices = _machine()["States"]["Route"]["Choices"]
    matched = [c for c in choices if c.get("StringEquals") == "transfer_ownership"]
    assert len(matched) == 1
    assert matched[0]["Next"] == "TransferOwnership"


def test_the_refusal_branch_is_first_and_cannot_match_a_present_null():
    """The trap this machine sets for itself, and the one this repo already paid for on file-ops.

    ``IsPresent`` is TRUE for a field that is present and null, and this plane's own
    ``ValidateFailureSeed`` teaches the opposite habit in bold — "a null VALUE is fine; a missing
    key is fatal". Under a null seed a bare ``IsPresent`` would route CREATE, ADD, LEAVE, DELETE
    and everything else into the refusal branch, and no graph walk would see it.

    First, because a refused request must never reach a verb whatever action it names.
    """
    choices = _machine()["States"]["Route"]["Choices"]
    first = choices[0]

    assert first["Next"] == "RefusedSeed", "the refusal branch must be evaluated before any action"
    conditions = {(c["Variable"], k): v for c in first["And"] for k, v in c.items() if k != "Variable"}
    assert conditions[("$.refusal", "IsPresent")] is True
    assert conditions[("$.refusal", "IsNull")] is False, (
        "IsPresent alone matches a present-and-null field, which is every request on this plane"
    )


@pytest.mark.parametrize("state", ["RefusedSeed", "TransferOwnership"])
def test_every_arm_of_the_new_branch_reaches_the_notifier_before_it_fails(state):
    """FR-005: a pre-verb failure notifies the requester, walked rather than asserted by reading.

    Every path from either new state to ``Failed`` must pass through ``NotifyFailure``. The
    failure this catches is a state whose Catch or Next skips the notifier — the execution still
    fails, correctly, and the user is simply never told.
    """
    states = _states()
    seen, terminals = set(), []

    def walk(name, path):
        """Follows every edge out of one state to a terminal.

        Args:
          name: The state to walk from.
          path: The states already traversed.

        Returns:
          None.

        Raises:
          AssertionError: If a path reaches Failed without passing the notifier.
        """
        if (name, tuple(path)) in seen:
            return
        seen.add((name, tuple(path)))
        node = states[name]
        here = [*path, name]
        nexts = [node["Next"]] if "Next" in node else []
        nexts += [c["Next"] for c in node.get("Catch", [])]
        nexts += [c["Next"] for c in node.get("Choices", [])]
        if "Default" in node:
            nexts.append(node["Default"])
        if not nexts:
            terminals.append(here)
            return
        for step in nexts:
            walk(step, here)

    walk(state, [])

    failing = [p for p in terminals if p[-1] == "Failed"]
    assert failing, f"{state} reaches no failure terminal at all, so this asserts nothing"
    for path in failing:
        assert "NotifyFailure" in path, f"{state} can fail without notifying: {' -> '.join(path)}"


def test_the_refusal_seed_carries_what_the_notifier_needs_and_nothing_it_cannot_read():
    """The seed does NOT go through RecordFailure, and that is not a shortcut.

    RecordFailure projects a fixed six-key shape shared by every verb's Catch, and a Pass state's
    JSONPath hard-fails on an ABSENT key — so adding ``message`` there would raise an uncatchable
    States.Runtime on all seven existing arms. The reason code rides as ``$.error`` so the run
    still records WHICH refusal it was; without it every refusal decodes as an unexpected error.
    """
    seed = _states()["RefusedSeed"]
    parameters = seed["Parameters"]

    assert seed["Next"] == "NotifyFailure"
    assert parameters["message.$"] == "$.refusal.message"
    assert parameters["error"]["Error.$"] == "$.refusal.code"
    for required in ("requestId.$", "actor.$", "action.$", "space.$"):
        assert required in parameters, f"the notifier reads {required} and a Pass fails on an absent key"


def test_the_transfer_verb_catches_and_records_like_every_other():
    catch = _states()["TransferOwnership"]["Catch"]
    assert catch[0]["ErrorEquals"] == ["States.ALL"]
    assert catch[0]["ResultPath"] == "$.error", "replacing the state would throw the verified actor away"
    assert catch[0]["Next"] == "RecordFailure"


def test_the_pipe_forwards_the_record_whole():
    """The operator boundary reads ``attributes.SenderId``, which is a message system attribute
    rather than a field of the body. It survives only because the Pipe declares no input template
    — the same property that lets the body be read off the record at all. An input transformer
    added later would strip it silently, and every operator transfer would stop."""
    pipe = (_MODULE / "pipe.tf").read_text()
    assert "input_template" not in pipe, (
        "an input template on this Pipe strips attributes.SenderId, which is the whole of the "
        "operator boundary"
    )


def test_the_reader_does_not_run_under_the_orchestrator_role():
    """The whole of what makes the SenderId comparison mean anything.

    The plane accepts an operator message when the sender names the reader's role. A reader
    sharing the orchestrator role would make that "any verb on this plane may forge one" — true
    of the running system, and invisible to every test, because a test supplies the SenderId
    itself.
    """
    locals_tf = (_MODULE / "locals.tf").read_text()
    lambda_tf = (_MODULE / "lambda.tf").read_text()

    verbs = locals_tf.split("shared_space_functions = {")[1].split("}")[0]
    assert "transfer-reader" not in verbs, (
        "the reader is in the verb map, whose for_each hard-codes the orchestrator role"
    )
    assert "transfer-ownership" in verbs, "the verb, unlike the reader, does belong there"

    block = lambda_declaration(lambda_tf, "transfer_reader")
    role = lambda_input(block, "role")
    assert role == "aws_iam_role.transfer_reader.arn", f"the reader runs as {role}"


def test_the_reader_gets_its_own_log_group():
    """It leaves the for_each that gives every verb one, and a function with no declared log
    group gets one at INFINITE retention on first invoke — which checkov cannot see at all.

    The reader is its own call to the container module, and that module declares the group; so
    what is asserted is the pair. A reader folded back into the verbs' for_each would lose its
    own role, which is the boundary the test above exists for.
    """
    calls = module_calls((_MODULE / "lambda.tf").read_text())
    assert {"functions", "transfer_reader"} <= set(calls), (
        f"the reader is not a call of its own; this module calls {sorted(calls)}"
    )
    assert argument(calls["transfer_reader"], "source") == '"../docker-lambda"'

    module_main = (
        _MODULE.parent / "docker-lambda" / "main.tf"
    ).read_text(encoding="utf-8")
    assert re.search(r"^\s*retention_in_days\s*=", strip_noise(module_main), re.MULTILINE), (
        "the container module no longer declares its log group's retention, so every function "
        "in the fleet keeps its logs forever and checkov's CKV_AWS_66 sees nothing"
    )


def test_the_schedule_names_a_rule_the_deploy_role_can_manage():
    """The grant is scoped to the family wildcard, so the rule's name has to sit inside it. A name
    outside the pattern is denied at PutRule — on the apply, not at plan."""
    locals_tf = (_MODULE / "locals.tf").read_text()
    policy = (
        pathlib.Path(__file__).resolve().parents[2]
        / "infra/modules/base/policies/github-actions-deploy-shared-spaces.json.tftpl"
    ).read_text()

    assert "transfer_schedule_name    = \"${local.transfer_reader_name}-schedule\"" in locals_tf
    grant = json.loads(re.sub(r"\$\{[^}]+\}", "STUB", policy))
    events = [s for s in grant["Statement"] if any(a.startswith("events:") for a in s["Action"])]
    assert len(events) == 1, "one statement, so there is one place the scope can be wrong"
    assert events[0]["Resource"].endswith("-shared-space-*"), (
        "scoped to the rule's own name, this would miss `-shared-space-transfer-reader-schedule`"
    )
