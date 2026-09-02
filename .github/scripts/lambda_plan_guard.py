#!/usr/bin/env python3
"""Asserts the Lambda fleet's shape over a rendered OpenTofu plan.

The guard the cutover needs is "every function is packaged the way we think it is, and nothing
else about any of them moved". Both halves have to be derived from the PLAN rather than from a
list somebody maintains: a function left behind by a partial cutover has to fail, not be missed,
and a list of 86 names is exactly the artefact that goes stale silently.

**Why the plan and not the source.** `.tf` text says what was written; the plan says what Terraform
resolved, including values that come from a variable or another module. The cutover changes 86
functions across 14 modules, and reading the source would mean re-implementing HCL evaluation to
find out what `image_uri` actually is.

**The trap this file is written around.** A NO-OP plan carries refreshed values for every
attribute, including ones the configuration never set — `memory_size` reads 128 because that is
what AWS has. A REPLACEMENT plan carries only what the configuration sets; anything else is
*unknown*, and unknown is absent from `after`. So a naive comparison of the two sees "128" against
"missing" for exactly the fields most likely to have moved, and the obvious repair — skip what the
new plan lacks — makes the comparison vacuous. Here an unknown parity field is a HARD FAILURE, and
the module the cutover uses declares every one of them explicitly so it cannot arise.

Usage:
    lambda_plan_guard.py capture --plan plan.json --out fixture.json
    lambda_plan_guard.py check   --plan plan.json --fixture fixture.json \\
                                 --package-type Zip [--image-repository URL] \\
                                 --table .github/lambda-functions.json \\
                                 --project dat --environment prod

Attributes:
    PARITY_FIELDS: The attributes SPEC-213 FR-002 promises the cutover does not change. Compared
        for every function, in both directions, against a fixture captured before it.
    PACKAGING_FIELDS: The three the cutover is ALLOWED to change. Named explicitly rather than
        skipping unknown keys, so a field nobody meant to move is still caught.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

PARITY_FIELDS = (
    "environment",
    "timeout",
    "memory_size",
    "architectures",
    "role",
    "reserved_concurrent_executions",
    "vpc_config",
)

PACKAGING_FIELDS = ("package_type", "image_uri", "image_config")


def _has_unknown_leaf(marker) -> bool:
    """Whether a Terraform `after_unknown` marker contains any genuinely unknown value.

    `after_unknown` PRESERVES THE STRUCTURE of the attribute it describes, and that is the whole
    reason this function exists rather than a truthiness test. Measured against a real create plan
    of `infra/modules/docker-lambda`:

        environment   after=[{"variables": {"FOO": "bar"}}]   after_unknown=[{"variables": {}}]
        architectures after=["x86_64"]                        after_unknown=[false]
        timeout       after=60                                after_unknown=null

    A fully-KNOWN list is `[false]` and a fully-known block is `[{}]` — both truthy in Python. So
    `if unknown.get(field)` reports every list and every block as unknown, which on the cutover's
    replacement plan is roughly 250 false failures, and on any plan that merely CREATES a function
    is a capture that refuses to run. Only a `true` leaf means unknown.

    Args:
      marker: One `after_unknown` value: a bool, a list, a dict, or None.

    Returns:
      True when any leaf is unknown.

    Raises:
      None.
    """
    if isinstance(marker, bool):
        return marker
    if isinstance(marker, dict):
        return any(_has_unknown_leaf(v) for v in marker.values())
    if isinstance(marker, list):
        return any(_has_unknown_leaf(v) for v in marker)
    return False


def _comparable(field: str, value):
    """Normalises a parity value so the two plan KINDS can be compared at all.

    `vpc_config` carries `vpc_id`, which the provider reads back: a no-op plan has it and a
    create plan omits the key entirely, so a raw comparison fails for every VPC-attached function
    no matter what the configuration says — and the guard's usual remedy, "declare it explicitly",
    is impossible for an attribute that is not settable. Only the sub-attributes the configuration
    sets are compared.

    Args:
      field: The parity field's name.
      value: Its planned value.

    Returns:
      The value reduced to what a configuration can actually control.

    Raises:
      None.
    """
    if field != "vpc_config" or not value:
        return value
    return [
        {
            "subnet_ids": sorted(block.get("subnet_ids") or []),
            "security_group_ids": sorted(block.get("security_group_ids") or []),
        }
        for block in value
    ]


def _functions(plan: dict) -> dict[str, dict]:
    """Every `aws_lambda_function` in the plan, keyed by its deployed name.

    Keyed by NAME rather than by resource address deliberately: the cutover moves every function
    from `module.<plane>.aws_lambda_function.functions["x"]` to
    `module.<plane>.module.<call>["x"].aws_lambda_function.this`, so an address-keyed fixture would
    match nothing on the far side and the comparison would pass having compared nothing.

    Args:
      plan: A parsed `tofu show -json` document.

    Returns:
      A mapping of function name to `{"after": ..., "unknown": ...}`.

    Raises:
      SystemExit: When two resources claim the same function name, which would silently drop one.
    """
    found: dict[str, dict] = {}
    for change in plan.get("resource_changes", []):
        if change.get("type") != "aws_lambda_function":
            continue
        after = (change.get("change") or {}).get("after") or {}
        unknown = (change.get("change") or {}).get("after_unknown") or {}
        name = after.get("function_name")
        if name is None:
            # A function whose very name is unknown cannot be compared to anything. That is not a
            # case to skip: it means the plan cannot tell us what is being built.
            sys.exit(
                f"{change.get('address')} has an unknown function_name; the plan cannot say what "
                "this function is, so nothing below could be checked against it"
            )
        if name in found:
            sys.exit(f"two resources both plan a function named {name}")
        found[name] = {"after": after, "unknown": unknown, "address": change.get("address")}
    return found


def _short(name: str, project: str, environment: str) -> str:
    """Strips the project/environment prefix, giving the name the deploy table uses.

    Args:
      name: A deployed function name.
      project: The project prefix.
      environment: The environment segment.

    Returns:
      The suffix the deploy table and the `lambdas/` directories use.

    Raises:
      None.
    """
    prefix = f"{project}-{environment}-"
    return name.removeprefix(prefix)


def capture(plan: dict) -> dict:
    """Extracts the parity values for every function in the plan.

    Args:
      plan: A parsed `tofu show -json` document.

    Returns:
      The fixture document.

    Raises:
      SystemExit: When a parity value is unknown, which makes the fixture unusable.
    """
    functions = _functions(plan)
    if not functions:
        sys.exit("the plan carries no aws_lambda_function at all; nothing would be captured")

    captured = {}
    for name, entry in sorted(functions.items()):
        row = {}
        for field in PARITY_FIELDS:
            if _has_unknown_leaf(entry["unknown"].get(field)):
                sys.exit(
                    f"{name}: {field} is unknown in this plan, so it cannot be captured as the "
                    "value the cutover must preserve. Capture from a plan with no pending changes."
                )
            row[field] = _comparable(field, entry["after"].get(field))
        # The handler is captured for a different reason: it IS the command the container function
        # takes, and deriving the expected command from the new code would agree with itself.
        row["handler"] = entry["after"].get("handler")
        captured[name] = row
    return {
        "note": (
            "FROZEN. Captured from the pre-cutover plan and never regenerated: the whole point is "
            "to compare the cutover against what was there before, and re-capturing from "
            "post-cutover code makes both sides derive from the same source and agree with "
            "nothing. The handler is here because it is the string the image command must equal."
        ),
        "functions": captured,
    }


def check(plan: dict, fixture: dict, package_type: str, image_repository: str | None,
          table: list, project: str, environment: str) -> list[str]:
    """Asserts packaging, population and parity over a plan.

    Args:
      plan: A parsed `tofu show -json` document.
      fixture: The frozen pre-cutover capture.
      package_type: The packaging every function must have — `Zip` before the cutover, `Image`
        after, so this file lands proven against the world as it is.
      image_repository: The registry URI every `image_uri` must name, for the Image case.
      table: The parsed deploy table.
      project: The project prefix.
      environment: The environment segment.

    Returns:
      Every problem found, empty when the fleet is as expected.

    Raises:
      SystemExit: When the plan carries no functions, which would make every check vacuous.
    """
    functions = _functions(plan)
    if not functions:
        sys.exit("the plan carries no aws_lambda_function at all; every check below is vacuous")

    problems = []

    # ── Packaging, derived from the plan rather than from a list ──
    for name, entry in sorted(functions.items()):
        actual = entry["after"].get("package_type")
        if actual != package_type:
            problems.append(f"{name}: package_type is {actual!r}, expected {package_type!r}")
        if package_type == "Image":
            uri = entry["after"].get("image_uri") or ""
            if image_repository and not uri.startswith(f"{image_repository}:"):
                problems.append(
                    f"{name}: image_uri {uri!r} does not name the fleet's repository "
                    f"{image_repository!r}"
                )
            command = (entry["after"].get("image_config") or [{}])[0].get("command") or []
            expected = fixture["functions"].get(name, {}).get("handler")
            if expected and list(command) != [expected]:
                problems.append(
                    f"{name}: command is {command!r}, expected [{expected!r}] — the handler the "
                    "zip-packaged function carried"
                )

    # ── Population: the plan and the deploy table must name the same fleet ──
    planned = {_short(n, project, environment) for n in functions}
    declared = {row["name"] for row in table}
    for missing in sorted(declared - planned):
        problems.append(f"{missing}: in the deploy table, but Terraform plans no such function")
    for extra in sorted(planned - declared):
        problems.append(f"{extra}: Terraform plans it, but the deploy table does not name it")

    # ── Parity: every field the spec promises is unchanged ──
    expected_names = set(fixture["functions"])
    for name in sorted(expected_names - set(functions)):
        problems.append(f"{name}: in the parity fixture, but absent from the plan")
    for name in sorted(set(functions) - expected_names):
        problems.append(f"{name}: in the plan, but absent from the parity fixture")

    for name in sorted(expected_names & set(functions)):
        entry, want = functions[name], fixture["functions"][name]
        for field in PARITY_FIELDS:
            if _has_unknown_leaf(entry["unknown"].get(field)):
                problems.append(
                    f"{name}: {field} is UNKNOWN in this plan. That is not 'no change' — an "
                    "attribute the configuration does not set is unknown in a replacement plan "
                    "and refreshed in a no-op one, so skipping it would make this comparison "
                    "vacuous for the fields most likely to have moved. Declare it explicitly."
                )
                continue
            got = _comparable(field, entry["after"].get(field))
            if got != want[field]:
                problems.append(f"{name}: {field} moved from {want[field]!r} to {got!r}")

    return problems


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
      argv: Command-line arguments, defaulting to `sys.argv[1:]`.

    Returns:
      0 when the fleet is as expected, 1 otherwise.

    Raises:
      None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    cap = sub.add_parser("capture")
    cap.add_argument("--plan", required=True)
    cap.add_argument("--out", required=True)

    chk = sub.add_parser("check")
    chk.add_argument("--plan", required=True)
    chk.add_argument("--fixture", required=True)
    chk.add_argument("--package-type", required=True, choices=("Zip", "Image"))
    chk.add_argument("--image-repository", default=None)
    chk.add_argument("--table", required=True)
    chk.add_argument("--project", required=True)
    chk.add_argument("--environment", required=True)

    args = parser.parse_args(argv)
    plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8"))

    if args.mode == "capture":
        pathlib.Path(args.out).write_text(
            json.dumps(capture(plan), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"captured {len(capture(plan)['functions'])} functions to {args.out}")
        return 0

    fixture_path = pathlib.Path(args.fixture)
    if not fixture_path.is_file():
        # Never a soft skip. A gate that passes when its own input is missing reads as
        # enforcement while enforcing nothing.
        print(f"::error::the parity fixture {args.fixture} is missing; capture it first")
        return 1

    problems = check(
        plan,
        json.loads(fixture_path.read_text(encoding="utf-8")),
        args.package_type,
        args.image_repository,
        json.loads(pathlib.Path(args.table).read_text(encoding="utf-8")),
        args.project,
        args.environment,
    )
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        print(f"{len(problems)} problem(s) in the planned Lambda fleet.")
        return 1
    print(f"all {len(_functions(plan))} functions are {args.package_type}-packaged and unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
