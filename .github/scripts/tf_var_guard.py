#!/usr/bin/env python3
"""Refuses a `TF_VAR_*` Actions variable that the OpenTofu run beside it is not given.

A variable named for a Terraform input does nothing by being set: a workflow has to hand it to
`tofu` as `TF_VAR_<name>`, and nothing says so when one is set and never handed over. The variable
then reads as configuration while Terraform builds from its own default, and any workflow that
builds a resource name from the same variable points at a resource Terraform never built.

The guard runs INSIDE the step that invokes `tofu`, from the same working directory, so the
environment and the module it reads are the ones Terraform reads rather than a second description
of them. Two things must hold for a variable to count as handed over, because OpenTofu ignores
anything else without a word: the environment key's suffix is EXACTLY a variable the module declares —
OpenTofu matches that spelling case-sensitively, while GitHub stores the Actions variable's name
upper-cased — and the value is the same. The value matters because `TF_VAR_max_upload_bytes`
reaches Terraform from a differently named variable, so a variable called that would pass a
name-only check while Terraform used something else.

Usage:
    REPO_VARS='${{ toJSON(vars) }}' tf_var_guard.py    # from the directory `tofu` runs in

Attributes:
    PREFIX: The prefix OpenTofu reads input variables from, and the one that marks an Actions
        variable as meant for it.
"""

import json
import os
import pathlib
import re
import sys
from collections.abc import Mapping

PREFIX = "TF_VAR_"


def declared(module: pathlib.Path) -> set[str]:
    """Reads the input variable names a root module declares, spelled as OpenTofu matches them.

    Args:
      module: The directory `tofu` runs in.

    Returns:
      Every name in a top-level `variable "<name>"` block of the directory's `.tf` files.

    Raises:
      None.
    """
    return {
        name
        for path in sorted(module.glob("*.tf"))
        for name in re.findall(r'^variable\s+"([^"]+)"\s*\{', path.read_text(encoding="utf-8"), re.MULTILINE)
    }


def unreceived(
    variables: Mapping[str, object], environment: Mapping[str, str], names: set[str]
) -> list[str]:
    """Names every `TF_VAR_*` Actions variable Terraform is not given unchanged, with why.

    Values are never reported, only names.

    Args:
      variables: The Actions variables, as `toJSON(vars)` renders them.
      environment: The environment of the step that invokes `tofu`.
      names: The variables the module declares, from `declared`.

    Returns:
      One sentence per offending variable, sorted by name; empty when every one reaches Terraform.

    Raises:
      None.
    """
    given = {
        key.upper(): value
        for key, value in environment.items()
        if key.startswith(PREFIX) and key[len(PREFIX) :] in names
    }
    problems = []
    for name in sorted(variables, key=str.upper):
        key = name.upper()
        if not key.startswith(PREFIX):
            continue
        if key not in given:
            problems.append(f"{key} is set, and this run does not give it to Terraform")
        elif given[key] != variables[name]:
            problems.append(f"{key} is set, and Terraform is given a different value under that name")
    return problems


def main() -> int:
    """Checks the Actions variables in `REPO_VARS` against this process's environment and module.

    The refusals before the comparison exist because each condition would otherwise pass as
    clean: with no `REPO_VARS` there is nothing to find, with no `TF_VAR_*` in the environment the
    guard is not running in the step it guards, and with no variable declared in the working
    directory it is not running where `tofu` does.

    Args:
      None.

    Returns:
      0 when every set `TF_VAR_*` variable reaches Terraform unchanged, 1 when one does not, and
      2 when the guard cannot tell.

    Raises:
      None.
    """
    raw = os.environ.get("REPO_VARS")
    if raw is None:
        print("::error title=TF_VAR guard::REPO_VARS is not set; pass it `${{ toJSON(vars) }}`.")
        return 2
    try:
        variables = json.loads(raw)
    except json.JSONDecodeError:
        variables = None
    if not isinstance(variables, dict):
        print("::error title=TF_VAR guard::REPO_VARS is not a JSON object of variable names.")
        return 2
    if not any(name.startswith(PREFIX) for name in os.environ):
        print(
            "::error title=TF_VAR guard::no TF_VAR_ name in this step's environment, so it is not "
            "the step that invokes tofu; run the guard inside that step."
        )
        return 2
    names = declared(pathlib.Path.cwd())
    if not names:
        print(
            "::error title=TF_VAR guard::the working directory declares no variable, so it is not "
            "where tofu runs; give the guard the step's working-directory."
        )
        return 2

    problems = unreceived(variables, os.environ, names)
    for problem in problems:
        print(
            f"::error title=Unused Terraform input::{problem}. Setting it changes nothing "
            "Terraform builds. Delete the variable — handing it to tofu instead is a change to "
            "the deploy, and Step 3 of .github/workflows/README.md says what it would rename."
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
