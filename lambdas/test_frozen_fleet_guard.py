"""The frozen fleet guard over the plans a merge can carry while Lambda builds are off, silence included.

Silence is pinned as carefully as each refusal: a guard that refused a timeout change would be
switched off, and one that passed a created function is the defect it exists for. Each refusal is
asserted by its sentence, because every refusal returns the same exit code.

Attributes:
  ROOT: The repository root.
  GUARD_PATH: The script under test.
  GUARD: The script under test, imported by path because `.github/scripts` is not a package.
  ENV: A function's environment as a plan renders it.
  CORPUS: Resource changes, and the refusals the guard must report for them.
"""

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / ".github" / "scripts" / "frozen_fleet_guard.py"

_spec = importlib.util.spec_from_file_location("frozen_fleet_guard", GUARD_PATH)
GUARD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GUARD)

ENV = [{"variables": {"QUEUE_URL": "https://sqs/q"}}]


def _function(
    actions, before=None, after=None, unknown=None, kind="aws_lambda_function"
):
    """Builds one resource change as `tofu show -json` renders it.

    Args:
      actions: The change's actions.
      before: The attributes before the change.
      after: The attributes after the change.
      unknown: The change's `after_unknown`.
      kind: The resource type.

    Returns:
      The resource change.

    Raises:
      None.
    """
    return {
        "address": "module.x.aws_lambda_function.this",
        "type": kind,
        "change": {
            "actions": actions,
            "before": before,
            "after": after,
            "after_unknown": unknown or {},
        },
    }


CORPUS = [
    pytest.param(
        _function(["create"], after={"environment": ENV}), ["is created"], id="created"
    ),
    pytest.param(_function(["delete", "create"]), ["is created"], id="replaced"),
    pytest.param(
        _function(
            ["update"],
            {"image_config": [{"command": ["a.h"]}]},
            {"image_config": [{"command": ["b.h"]}]},
        ),
        ["changes image_config"],
        id="handler-command",
    ),
    pytest.param(
        _function(
            ["update"],
            {"environment": ENV},
            {"environment": [{"variables": {"QUEUE": "https://sqs/q"}}]},
        ),
        ["changes environment"],
        id="renamed-variable",
    ),
    pytest.param(
        _function(
            ["update"],
            {"environment": ENV},
            {"environment": ENV},
            {"environment": [{"variables": {"QUEUE_URL": True}}]},
        ),
        ["changes environment"],
        id="unknown-until-apply",
    ),
    pytest.param(
        _function(
            ["update"],
            {"environment": ENV, "timeout": 30},
            {"environment": ENV, "timeout": 60},
        ),
        [],
        id="timeout-only",
    ),
    pytest.param(_function(["delete"], before={"environment": ENV}), [], id="deleted"),
    pytest.param(
        _function(["no-op"], {"environment": ENV}, {"environment": ENV}),
        [],
        id="unchanged",
    ),
    pytest.param(_function(["create"], kind="aws_iam_role"), [], id="not-a-function"),
]


@pytest.mark.parametrize(("resource", "reasons"), CORPUS)
def test_the_guard_refuses_exactly_what_old_code_cannot_serve(resource, reasons):
    """Each change is refused for its own reason, and the changes old code can serve are silent.

    Args:
      resource: One resource change.
      reasons: The phrase each expected refusal carries, in order.

    Returns:
      None.

    Raises:
      AssertionError: If the refusals differ in number or reason.
    """
    problems = GUARD.refusals({"planned_values": {}, "resource_changes": [resource]})

    assert len(problems) == len(reasons)
    for problem, reason in zip(problems, reasons, strict=True):
        assert reason in problem


@pytest.mark.parametrize(("switch", "code"), [("", 1), ("false", 1), ("TRUE", 0)])
def test_the_switch_decides_whether_a_refused_plan_fails(
    tmp_path, monkeypatch, capsys, switch, code
):
    """A refused plan fails while builds are off, in any spelling, and passes once they are on.

    Args:
      tmp_path: A scratch directory for the plan file.
      monkeypatch: Sets the switch.
      capsys: Captures the guard's report.
      switch: The variable's value.
      code: The exit code the guard must return.

    Returns:
      None.

    Raises:
      AssertionError: If the exit code or the report is wrong.
    """
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"planned_values": {}, "resource_changes": [_function(["create"])]})
    )
    monkeypatch.setenv("LAMBDA_BUILDS_ENABLED", switch)

    assert GUARD.main(["--plan", str(plan)]) == code
    assert ("is created" in capsys.readouterr().out) is (code == 1)


def test_a_file_that_is_not_plan_output_is_an_error_not_a_pass(tmp_path, monkeypatch):
    """A missing or foreign file exits 2, because checking nothing is not a clean result.

    Args:
      tmp_path: A scratch directory for the file.
      monkeypatch: Turns the switch off.

    Returns:
      None.

    Raises:
      AssertionError: If an unreadable or foreign file passes.
    """
    monkeypatch.delenv("LAMBDA_BUILDS_ENABLED", raising=False)
    foreign = tmp_path / "other.json"
    foreign.write_text(json.dumps({"resource_changes": []}))

    assert GUARD.main(["--plan", str(foreign)]) == 2
    assert GUARD.main(["--plan", str(tmp_path / "absent.json")]) == 2
