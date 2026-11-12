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
_PLANES = os.path.join(_ROOT, "infra", "planes")
_INFRA = os.path.join(_ROOT, "infra")
_CONTROL_PLANE = os.path.join(_INFRA, "modules", "control-plane", "main.tf")

EXPECTED_PLANES = 6


def _has_ceiling(asl_path: str) -> bool:
    """Reports whether a machine template declares a top-level ``TimeoutSeconds``.

    The template is a `.tftpl`, so interpolations are replaced with a scalar before parsing —
    reading the KEY's presence, never its value, which is the plane's own business.

    Args:
      asl_path: Path to the plane's `state-machine.asl.json.tftpl`.

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
    """Derives the population: every plane whose machine sets a top-level ceiling.

    Args:
      None.

    Returns:
      ``{plane name: the plane's root file}`` for each plane carrying a ceiling.

    Raises:
      None.
    """
    found = {}
    for name in sorted(os.listdir(_PLANES)):
        asl = os.path.join(_PLANES, name, "state-machine.asl.json.tftpl")
        if os.path.isfile(asl) and _has_ceiling(asl):
            found[name] = os.path.join(_INFRA, f"plane-{name}.tf")
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
    all_planes = [n for n in os.listdir(_PLANES) if os.path.isdir(os.path.join(_PLANES, n))]

    assert POPULATION, "the ceiling detection matched nothing"
    assert len(POPULATION) < len(all_planes), (
        "the ceiling detection matched every plane and no longer discriminates"
    )
    assert len(POPULATION) == EXPECTED_PLANES, (
        f"planes with a ceiling are now {sorted(POPULATION)}; if one was added or removed, "
        "update EXPECTED_PLANES deliberately"
    )


def test_every_plane_with_a_ceiling_declares_the_rule() -> None:
    """The infra half, for the whole fleet: a ceiling in the ASL is a ceiling in the call, and the
    module turns the call's ceiling into the rule.

    Both directions on the call, because the module creates the rule FROM the call's `ceiling`: a
    plane whose ASL has a ceiling and whose call has none ships the ceiling with no door, and a
    call with a ceiling over an ASL without one ships a rule for a timeout that cannot happen.
    The rule itself is written once, in the module, and is read once.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane's call and its ASL disagree about the ceiling, the call names a
        notifier other than notify-failure, or the module's rule is missing a part or lets
        `FAILED` into the pattern.
    """
    for name in sorted(os.listdir(_PLANES)):
        with open(os.path.join(_INFRA, f"plane-{name}.tf"), encoding="utf-8") as handle:
            text = handle.read()
        declares = re.search(r"^\s*ceiling\s*=\s*\{", text, re.MULTILINE) is not None
        assert declares == (name in POPULATION), (
            f"{name}'s ASL {'sets' if name in POPULATION else 'sets no'} a TimeoutSeconds and its "
            f"call {'passes' if declares else 'passes no'} `ceiling`; the rule exists only from "
            "the call's ceiling, so the two must agree"
        )
        if declares:
            assert 'notifier_verb    = "notify-failure"' in text, (
                f"{name}'s ceiling must be told through its notify-failure verb"
            )

    with open(_CONTROL_PLANE, encoding="utf-8") as handle:
        module = handle.read()
    for resource in ("aws_cloudwatch_event_rule", "aws_cloudwatch_event_target", "aws_lambda_permission"):
        block = module.split(f'resource "{resource}" "execution_timed_out"')
        assert len(block) == 2, f"the control-plane module has no {resource} for a timed-out run"
        assert "count = var.ceiling == null ? 0 : 1" in block[1].split("\n}\n")[0], (
            f"the module's {resource} is not created from the call's ceiling"
        )
    assert 'status          = ["TIMED_OUT"]' in module, "the module's rule does not match TIMED_OUT"
    pattern = module.split("event_pattern")[1].split("})")[0]
    assert "FAILED" not in pattern, (
        "the rule would double-notify: every whole-request failure the shared Catch takes "
        "already reaches NotifyFailure"
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
