"""Every plane with a state-machine ceiling has BOTH halves of its timed-out door.

This guard exists because the defect it prevents was found by a live check rather than by a test,
months after it shipped. ``table-builder`` set a top-level ``TimeoutSeconds`` and had neither the
EventBridge rule nor the handler's detail-type dispatch, so a build that hit the hour notified
nobody — and nothing here would have gone red, because the two planes that guard this at all guard
only themselves.

**Why a ceiling implies a door.** A top-level ``TimeoutSeconds`` expiry terminates the execution
outright. Catchers are per-state, so no ``Catch`` covers it and the machine's own NotifyFailure path
is unreachable on that one failure. EventBridge is the only route left.

**Why the rule alone is not the door.** A status-change event carries no top-level ``actor``. A
handler without the dispatch reads one, finds nothing, and takes its no-actor branch — which is
indistinguishable from the silence the rule was added to close. Both halves or neither.

The population is DERIVED from the ASL rather than listed, so a new plane that ships a ceiling joins
it automatically instead of being remembered into it.

Attributes:
  EXPECTED_PLANES: The number of planes carrying a ceiling when this was written. A change is a
    real change to the fleet and should be read, not silently absorbed.
"""

import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODULES = os.path.join(_ROOT, "infra", "modules")

EXPECTED_PLANES = 6


def _has_ceiling(asl_path: str) -> bool:
    """Reports whether a machine template declares a top-level ``TimeoutSeconds``.

    The template is a `.tftpl`, so interpolations are replaced with a scalar before parsing —
    reading the KEY's presence, never its value, which is the plane's own business.

    Args:
      asl_path: Path to the module's `state-machine.asl.json.tftpl`.

    Returns:
      True when the machine sets a top-level ceiling.

    Raises:
      None. An unparseable template reads as no ceiling, which the population assertion catches.
    """
    with open(asl_path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        return "TimeoutSeconds" in json.loads(re.sub(r"\$\{[^}]*\}", "1", text))
    except ValueError:
        return False


def _planes_with_a_ceiling() -> dict:
    """Derives the population: every module whose machine sets a top-level ceiling.

    Args:
      None.

    Returns:
      ``{module name: module directory}`` for each plane carrying a ceiling.

    Raises:
      None.
    """
    found = {}
    for name in sorted(os.listdir(_MODULES)):
        module = os.path.join(_MODULES, name)
        asl = os.path.join(module, "state-machine.asl.json.tftpl")
        if os.path.isfile(asl) and _has_ceiling(asl):
            found[name] = module
    return found


POPULATION = _planes_with_a_ceiling()


def test_the_derivation_still_selects_a_real_population() -> None:
    """Guard the guard: a detection gone trivial reads exactly like a clean pass.

    Both directions. Matching nothing means the template shape changed under the sweep and every
    claim below became vacuous; matching every module means it stopped discriminating between a
    plane with a ceiling and one without.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derivation collapsed in either direction.
    """
    all_modules = [
        n for n in os.listdir(_MODULES) if os.path.isdir(os.path.join(_MODULES, n))
    ]

    assert POPULATION, "the ceiling detection matched nothing"
    assert len(POPULATION) < len(all_modules), (
        "the ceiling detection matched every module and no longer discriminates"
    )
    assert len(POPULATION) == EXPECTED_PLANES, (
        f"planes with a ceiling are now {sorted(POPULATION)}; if one was added or removed, "
        "update EXPECTED_PLANES deliberately"
    )


def test_every_plane_with_a_ceiling_declares_the_rule() -> None:
    """The infra half, for the whole fleet rather than the two planes that guarded themselves.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane with a ceiling is missing the rule, its target, its invoke
        permission, or lets `FAILED` into the pattern.
    """
    for name, module in sorted(POPULATION.items()):
        with open(os.path.join(module, "stepfunction.tf"), encoding="utf-8") as handle:
            text = handle.read()

        assert 'resource "aws_cloudwatch_event_rule" "execution_timed_out"' in text, (
            f"{name} sets a TimeoutSeconds and no Catch can cover it, so it needs the rule"
        )
        assert 'resource "aws_cloudwatch_event_target" "execution_timed_out"' in text, (
            f"{name} declares the rule and nothing to deliver to"
        )
        assert 'resource "aws_lambda_permission" "execution_timed_out"' in text, (
            f"{name}'s rule has no resource-based invoke grant"
        )
        assert 'status          = ["TIMED_OUT"]' in text, f"{name} does not match TIMED_OUT"
        pattern = text.split("event_pattern")[1].split("})")[0]
        assert "FAILED" not in pattern, (
            f"{name} would double-notify: every other whole-request failure already reaches "
            "NotifyFailure through the shared Catch"
        )


def test_every_plane_with_a_ceiling_dispatches_in_its_handler() -> None:
    """The handler half. The rule alone deploys green and still notifies nobody.

    Asserted on the assigned constant and the call graph, never on a substring: a presence check
    for the detail-type is satisfied by a docstring that merely mentions it, which is how the first
    draft of this plane's own guard passed with the dispatch renamed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane with a ceiling has no detail-type door in its notify-failure.
    """
    import ast

    for name in sorted(POPULATION):
        door = os.path.join(_ROOT, "lambdas", f"{name}-notify-failure")
        sources = [
            os.path.join(door, f)
            for f in sorted(os.listdir(door))
            if f.endswith(".py") and not f.startswith("test_")
        ]
        assert sources, f"{name} has a ceiling and no notify-failure handler"

        joined = ""
        constants: dict = {}
        calls: set = set()
        for path in sources:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            joined += text
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = node.value.value
                if isinstance(node, ast.Call):
                    func = node.func
                    calls.add(
                        func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                    )

        assert "Step Functions Execution Status Change" in constants.values(), (
            f"{name} declares the rule but its handler has no detail-type to dispatch on, so the "
            "event reaches the ASL branch, finds no top-level actor and notifies nobody"
        )
        assert "trusted_actor" in calls, (
            f"{name}'s door must take the actor from the identity block, not from the body"
        )
