#!/usr/bin/env python3
"""Refuses a plan that changes what the Lambda fleet's image must serve while Lambda builds are off.

While the repository variable `LAMBDA_BUILDS_ENABLED` is not `true`, nothing builds a commit's
Lambda image or points a function at one, but the infrastructure apply still runs on every merge.
So a merge reaches a function's configuration and never its code, and two kinds of change break a
function silently. A function the plan CREATES starts from the image the fleet already runs, which
may not hold its handler. A function whose `image_config` (the handler command) or `environment`
changes keeps its old code, which may not know the new command or the renamed variable. Either
merges green and fails at invoke. A timeout, a memory size or an IAM policy changes nothing the
code reads, so those pass.

Usage:
    LAMBDA_BUILDS_ENABLED=... frozen_fleet_guard.py --plan infra/plan.json

Attributes:
    SWITCH: The environment variable carrying the repository variable's value.
    WATCHED: The function attributes whose change the code that runs them must agree with.
"""

import argparse
import json
import os
import pathlib
import sys
from collections.abc import Mapping
from typing import Any

SWITCH = "LAMBDA_BUILDS_ENABLED"
WATCHED = ("image_config", "environment")


def _unknown(value: Any) -> bool:
    """Whether a plan's `after_unknown` entry marks any part of an attribute as unknown until apply.

    Args:
      value: The attribute's entry in `after_unknown`: a boolean, or a list or mapping of them.

    Returns:
      True when any leaf is true.

    Raises:
      None.
    """
    if isinstance(value, Mapping):
        return any(_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(_unknown(item) for item in value)
    return value is True


def refusals(plan: Mapping[str, Any]) -> list[str]:
    """Names each Lambda function the plan creates, or whose handler command or environment it changes.

    Args:
      plan: The plan rendered by `tofu show -json`.

    Returns:
      One sentence per refused change, empty when the frozen image can serve the plan.

    Raises:
      None.
    """
    problems = []
    for resource in plan.get("resource_changes") or []:
        if resource.get("type") != "aws_lambda_function":
            continue
        change = resource.get("change") or {}
        actions = change.get("actions") or []
        address = resource.get("address", "?")
        if "create" in actions:
            problems.append(
                f"{address} is created, and would start from an image that may not hold its handler"
            )
            continue
        if "update" not in actions:
            continue
        before = change.get("before") or {}
        after = change.get("after") or {}
        unknown = change.get("after_unknown") or {}
        for field in WATCHED:
            if before.get(field) != after.get(field) or _unknown(unknown.get(field)):
                problems.append(
                    f"{address} changes {field}, which its running code was not built against"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Reads the plan and reports each refusal as a workflow error, unless Lambda builds are on.

    Args:
      argv: The command-line arguments, or None for the process's own.

    Returns:
      0 when the plan passes or builds are on, 1 when it is refused, 2 when the plan is unreadable.

    Raises:
      None.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    if os.environ.get(SWITCH, "").lower() == "true":
        print(
            f"{SWITCH} is on: this commit's image is built and pointed, so nothing is refused."
        )
        return 0
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"::error title=Frozen fleet guard::cannot read the plan: {error}")
        return 2
    if not isinstance(plan, dict) or "planned_values" not in plan:
        print(
            "::error title=Frozen fleet guard::the file is not plan output, so nothing was checked."
        )
        return 2
    problems = refusals(plan)
    for problem in problems:
        print(
            f"::error title=Lambda builds are off::{problem}. Turn Lambda builds back on first, "
            "in the order .github/workflows/README.md gives, then merge this."
        )
    if not problems:
        print(
            "No Lambda function is created, and none changes its handler command or environment."
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
