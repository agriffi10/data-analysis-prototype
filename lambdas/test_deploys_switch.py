"""The deploy switch: no job that builds or deploys runs on its own while ``DEPLOYS_ENABLED`` is unset.

Feature work paused for the move to the client environment, so every job that builds an image,
applies infrastructure, points a Lambda, deploys the SPA or publishes the flag document carries
``vars.DEPLOYS_ENABLED == 'true'`` in its ``if``. The variable is unset, so those jobs report as
skipped. The test derives the jobs a push, a pull request or a schedule could start from the
workflow directory, and holds them to an exact list, so a new deploy workflow without the switch
fails here and so does a check that quietly lost its switch.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The directory the jobs are derived from.
  GATE: The condition that keeps a job off while the variable is unset.
  AUTOMATIC_EVENTS: Triggers that start a run without a person choosing to.
  STILL_RUNNING: The jobs that must keep running with the switch off: the app and Lambda checks,
    the security scans, and the infrastructure plan on pull requests.
"""

import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATE = "vars.DEPLOYS_ENABLED == 'true'"
AUTOMATIC_EVENTS = frozenset({"push", "pull_request", "schedule", "workflow_run"})
STILL_RUNNING = frozenset(
    {
        "ci.yml:ci",
        "ci.yml:lambdas",
        "security.yml:scan",
        "security.yml:dast",
        "deploy-infra.yml:plan",
    }
)


def _gated(condition: str) -> bool:
    """Whether a job condition is false whenever the switch is off.

    The switch has to be a conjunct of the whole expression: ``A || GATE`` runs whenever ``A``
    holds, and ``A || B && GATE`` binds the switch to ``B`` alone, so only the switch on its own
    or ``<left> && GATE`` with no bare ``||`` in ``<left>`` counts.

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
    left = condition[: -len(suffix)].strip()
    if "||" not in left:
        return True
    if not (left.startswith("(") and left.endswith(")")):
        return False
    depth = 0
    for index, char in enumerate(left):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0 and index < len(left) - 1:
            return False
    return True


def _runnable_without_switch(document: dict[Any, Any]) -> set[str]:
    """The jobs in one workflow that can still run while the switch is off.

    A job with no switch runs if it has no ``needs``, or if its condition overrides the default
    skip propagation with a status function, or if any job it needs can itself run.

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
                    fn in condition for fn in ("always()", "failure()", "cancelled()")
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


def test_only_the_checks_and_the_plan_run_while_deploys_are_switched_off() -> None:
    """Every automatically triggered job outside the checks and the plan carries the switch.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a job could run without the switch and is not on the list, or a job on
        the list no longer runs, which would mean the list has gone stale.
    """
    running = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if _triggers(document) & AUTOMATIC_EVENTS:
            running |= {
                f"{path.name}:{job}" for job in _runnable_without_switch(document)
            }
    assert sorted(running - STILL_RUNNING) == [], (
        "jobs that build or deploy without the DEPLOYS_ENABLED switch"
    )
    assert sorted(STILL_RUNNING - running) == [], (
        "jobs the list keeps running that no longer run"
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
    assert not _gated(f"a == 'push' || a == 'workflow_dispatch' && {GATE}")
    assert not _gated(f"(a) || (b) && {GATE}")
    assert not _gated(f"{GATE} || a == 'push'")
    assert not _gated("vars.DEPLOYS_ENABLED != 'false'")


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
            "lint": {},
        }
    }
    assert _runnable_without_switch(document) == {"report", "lint"}
