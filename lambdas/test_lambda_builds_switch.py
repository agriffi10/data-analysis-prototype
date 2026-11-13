"""The Lambda builds switch: exactly the jobs that build, prove or point the Lambda image wait on it.

Feature work paused for the move to the client environment, so the Lambda fleet's image build, its
pull-request matrix and the pointing of every function at it carry
``vars.LAMBDA_BUILDS_ENABLED == 'true'`` in their ``if``, and the variable is unset. Every other
deploy runs: the infrastructure apply, the SPA deploys and the flag publish. The test derives which
jobs a push, a pull request or a schedule could start from the workflow directory, and holds the
ones the switch keeps off to an exact list, so a Lambda job that loses its switch fails here and so
does a deploy that quietly gains it.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The directory the jobs are derived from.
  GATE: The condition that keeps a job off while the variable is unset.
  MANUAL_EVENTS: The one trigger a person chooses to fire; every other event counts as automatic.
  HELD_OFF: The jobs the switch keeps off: the Lambda image build and its matrix, and the four
    jobs of the Lambda pointing, whose last two follow the first by skip propagation.
"""

import pathlib
import re
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATE = "vars.LAMBDA_BUILDS_ENABLED == 'true'"
MANUAL_EVENTS = frozenset({"workflow_dispatch"})
HELD_OFF = frozenset(
    {
        "deploy-lambda-image.yml:push",
        "lambda-image.yml:matrix",
        "deploy-lambdas.yml:plan",
        "deploy-lambdas.yml:deploy",
        "deploy-lambdas.yml:pointed",
        "deploy-lambdas.yml:probe",
    }
)


def _gated(condition: str) -> bool:
    """Whether a job condition is false whenever the switch is off.

    The switch has to be a conjunct of the whole expression: ``A || GATE`` runs whenever ``A``
    holds, and ``A || B && GATE`` binds the switch to ``B`` alone, so only the switch on its own
    or ``<left> && GATE`` with no bare ``||`` in ``<left>`` counts. Quoted literals are blanked
    first, so a parenthesis inside a string cannot balance the scan.

    Args:
      condition: The job's ``if`` expression, without ``${{ }}``.

    Returns:
      True when the switch being off makes the condition false.

    Raises:
      None.
    """
    condition = condition.strip()
    if condition == GATE:
        return True
    suffix = f" && {GATE}"
    if not condition.endswith(suffix):
        return False
    left = re.sub(r"'[^']*'", "''", condition[: -len(suffix)]).strip()
    if "||" not in left:
        return True
    if not (left.startswith("(") and left.endswith(")")):
        return False
    depth = 0
    for index, char in enumerate(left):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and index < len(left) - 1:
            return False
    return depth == 0


def _runnable_without_switch(document: dict[Any, Any]) -> set[str]:
    """The jobs in one workflow that can still run while the switch is off.

    A job with no switch runs if it has no ``needs``, or if its condition overrides the default
    skip propagation with a status function, or if any job it needs can itself run. GitHub reads
    function names in any case, so the condition is lowered before the status functions are
    looked for.

    Args:
      document: The parsed workflow.

    Returns:
      The names of the jobs that are not held off by the switch.

    Raises:
      None.
    """
    jobs = document.get("jobs") or {}
    runnable: dict[str, bool] = {}

    def can_run(name: str) -> bool:
        if name not in runnable:
            job = jobs[name]
            condition = str(job.get("if", ""))
            if _gated(condition):
                runnable[name] = False
            else:
                needs = job.get("needs") or []
                needs = [needs] if isinstance(needs, str) else needs
                overrides = any(
                    fn in condition.lower()
                    for fn in ("always()", "failure()", "cancelled()")
                )
                runnable[name] = (
                    not needs or overrides or any(can_run(need) for need in needs)
                )
        return runnable[name]

    return {name for name in jobs if can_run(name)}


def _triggers(document: dict[Any, Any]) -> set[str]:
    """The events a workflow declares, whichever of YAML's spellings of ``on`` it was parsed as.

    Args:
      document: The parsed workflow.

    Returns:
      The event names.

    Raises:
      None.
    """
    on = document.get("on", document.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def test_the_switch_holds_off_exactly_the_lambda_build_jobs() -> None:
    """The automatically triggered jobs the switch keeps off are the Lambda build jobs and no others.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a Lambda build job could run without the switch, or another job waits on
        it, which would hold off a deploy that is meant to run.
    """
    held = set()
    for path in sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if _triggers(document) - MANUAL_EVENTS:
            jobs = set(document.get("jobs") or {})
            held |= {
                f"{path.name}:{job}"
                for job in jobs - _runnable_without_switch(document)
            }
    assert sorted(HELD_OFF - held) == [], (
        "Lambda build jobs that run without the LAMBDA_BUILDS_ENABLED switch"
    )
    assert sorted(held - HELD_OFF) == [], (
        "jobs the switch holds off that are meant to deploy"
    )


def test_the_switch_must_hold_the_whole_condition() -> None:
    """A switch joined by ``||``, or bound to one side of it, does not keep a job off.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a condition that still runs with the switch off is read as gated, or a
        properly gated one is not.
    """
    assert _gated(GATE)
    assert _gated(f"always() && {GATE}")
    assert _gated(f"(a == 'push' || a == 'workflow_dispatch') && {GATE}")
    assert _gated(f"(a) && (b == '||') && {GATE}")
    assert not _gated(f"a == 'push' || a == 'workflow_dispatch' && {GATE}")
    assert not _gated(f"(a) || (b) && {GATE}")
    assert not _gated(f"{GATE} || a == 'push'")
    assert not _gated("vars.LAMBDA_BUILDS_ENABLED != 'false'")
    assert not _gated(f"(a == '(') || (b) && {GATE}")


def test_a_skipped_job_holds_off_what_needs_it_unless_a_status_function_overrides() -> (
    None
):
    """Skip propagation through ``needs`` counts as gated, and ``always()`` breaks it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derivation misses an ungated root, treats a dependent of a gated job
        as runnable, or treats an ``always()`` dependent as held off.
    """
    document = {
        "jobs": {
            "build": {"if": GATE},
            "deploy": {"needs": ["build"]},
            "report": {"needs": "build", "if": "always()"},
            "notify": {"needs": "build", "if": "Always()"},
            "lint": {},
        }
    }
    assert _runnable_without_switch(document) == {"report", "notify", "lint"}
