"""Pins the file-operations ceiling the BROWSER mirrors against the one that defines it.

Nothing at runtime reports that the two have drifted. Why the browser holds a copy at all, and
what an early or late expiry does to a user: ``lambdas/info/planes/file-ops.md``.

Attributes:
  ROOT: The repository root.
  PLANE: The file-operations plane's root call, whose ``ceiling`` defines the machine's timeout.
  BROWSER_CONSTANTS: The browser module that mirrors it.
"""

import pathlib
import re

from tf_blocks import argument, module_calls

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLANE = ROOT / "infra" / "plane-file-ops.tf"
BROWSER_CONSTANTS = ROOT / "apps" / "portal" / "src" / "features" / "file-browser" / "fileOps.constants.ts"


def _terraform_seconds() -> int:
    """Reads the state machine's timeout out of the Terraform that sets it.

    Args:
      None.

    Returns:
      The ceiling, in seconds.

    Raises:
      AssertionError: If the call carries no ceiling or the seconds are not a plain number, which
        would otherwise make every comparison below vacuous.
      ValueError: If the call or its ``ceiling`` argument is missing.
    """
    ceiling = argument(module_calls(PLANE.read_text())["file_ops"], "ceiling").strip()
    assert ceiling.startswith("{") and ceiling.endswith("}"), f"the file-ops ceiling is not a map: {ceiling}"
    seconds = argument(ceiling[1:-1], "seconds")
    assert re.fullmatch(r"\d+", seconds), f"the file-ops ceiling's seconds is not a literal: {seconds}"
    return int(seconds)


def _browser_seconds() -> int:
    """Reads the mirrored ceiling out of the browser constant.

    Args:
      None.

    Returns:
      The mirrored value, in seconds.

    Raises:
      AssertionError: If the constant is absent or has been renamed.
    """
    source = BROWSER_CONSTANTS.read_text()
    match = re.search(r"FILE_OPS_MACHINE_TIMEOUT_SECONDS\s*=\s*([\d_]+)\s*;", source)
    assert match, "FILE_OPS_MACHINE_TIMEOUT_SECONDS is not declared in fileOps.constants.ts"
    return int(match.group(1).replace("_", ""))


def test_the_browser_mirrors_the_machines_own_ceiling():
    """The in-flight expiry bound is the state machine's timeout, not a number beside it."""
    assert _browser_seconds() == _terraform_seconds()
