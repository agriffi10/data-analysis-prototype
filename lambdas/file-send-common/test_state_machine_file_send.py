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


def test_the_success_path_reads_only_keys_the_verb_emits():
    """The happy-path half nothing else covers."""
    states = _machine()["States"]
    validated = _validated_output()

    reads = {
        value[len("$.result.validated.") :]
        for key, value in states["Validated"]["Parameters"].items()
        if key.endswith(".$") and str(value).startswith("$.result.validated.")
    }

    assert reads, "the Validated state no longer reads through $.result.validated"
    assert reads <= set(validated), (
        f"the machine reads {sorted(reads - set(validated))} which validate-authorize does not "
        f"return — an absent key raises an uncatchable States.Runtime on the SUCCESS path"
    )


def test_the_verb_emits_nothing_the_machine_silently_drops():
    """The other direction, which is not a crash but a contract drift: a field the verb went to
    the trouble of computing and that no state carries forward is either dead or a bug."""
    states = _machine()["States"]
    validated = _validated_output()

    carried = {
        value[len("$.result.validated.") :]
        for key, value in states["Validated"]["Parameters"].items()
        if key.endswith(".$") and str(value).startswith("$.result.validated.")
    }

    assert set(validated) == carried


def test_the_raw_request_survives_a_validate_failure():
    """SPEC-152's guarantee on this plane depends on it. The Catch merges the error beside the
    captured request rather than replacing it, so notify-failure can recover the sender from
    the token — without which it would take its no-recipient branch on every failure."""
    states = _machine()["States"]

    catches = states["ValidateAuthorize"]["Catch"]
    assert all(c.get("ResultPath") == "$.error" for c in catches), (
        "the validate Catch no longer merges — the request, and with it the only copy of the "
        "caller's token, is replaced by the error object"
    )
    assert "raw" in _read_paths(states["ValidateFailureSeed"]["Parameters"])
    assert "raw" in _read_paths(states["RecordFailure"]["Parameters"])


def test_the_capture_state_runs_before_anything_else():
    machine = _machine()

    assert machine["StartAt"] == "CaptureRequest"
    assert machine["States"]["CaptureRequest"]["Parameters"] == {"raw.$": "$"}


def test_the_verb_is_handed_the_captured_request_and_not_the_wrapper():
    """A wrapper the verb was never taught about would make every request malformed."""
    task = _machine()["States"]["ValidateAuthorize"]

    assert task["Parameters"]["Payload.$"] == "$.raw"


@pytest.mark.parametrize("state", ["ValidateFailureSeed", "RecordFailure"])
def test_the_failure_terminal_reads_only_seeded_keys(state):
    """A narrower restatement of the fleet guard, kept local so this plane's own suite fails
    on it rather than a shared one three directories away."""
    states = _machine()["States"]
    seeded = set(states["ValidateFailureSeed"]["Parameters"]) | {
        k.removesuffix(".$") for k in states["ValidateFailureSeed"]["Parameters"]
    }

    assert _read_paths(states[state]["Parameters"]) <= seeded
