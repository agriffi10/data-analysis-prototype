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

import os
import pathlib
import re
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "control-plane-common"))
sys.path.insert(0, str(_HERE.parent / "file-send-validate-authorize"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_validate_authorize as v

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
    import json

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
    import json

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


def _validated_state_prefix(states: dict) -> str:
    """The JSONPath prefix at which the verb's output sits when ``Validated`` runs.

    DERIVED FROM THE MACHINE, never hard-coded, and that is the whole point of this helper. An
    earlier version of this file matched the literal ``"$.result.validated."`` — so deleting the
    ``ResultSelector`` or renaming the ``ResultPath`` left every assertion below passing against
    a machine that raised an uncatchable ``States.Runtime`` on its first real execution.
    Verified by mutation: both edits kept the whole suite green.

    Args:
      states: The machine's states.

    Returns:
      The prefix ``Validated``'s Parameters must read through, e.g. ``"$."``.

    Raises:
      AssertionError: If the task's output plumbing is a shape this cross-check cannot follow,
        which is itself a finding rather than something to route around.
    """
    task = states["ValidateAuthorize"]
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


def _validated_reads(states: dict) -> set[str]:
    """The verb-output keys the ``Validated`` state reads, at whatever prefix the machine uses.

    Args:
      states: The machine's states.

    Returns:
      The leaf key names.

    Raises:
      None.
    """
    prefix = _validated_state_prefix(states)
    return {
        value[len(prefix) :]
        for key, value in states["Validated"]["Parameters"].items()
        if key.endswith(".$") and str(value).startswith(prefix)
    }


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


def test_the_task_output_plumbing_is_the_shape_the_cross_check_assumes():
    """Stated on its own so a mutation to the plumbing fails HERE, with a message about the
    plumbing, rather than as a confusing key mismatch two tests away."""
    assert _validated_state_prefix(_machine()["States"]) == "$."


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
