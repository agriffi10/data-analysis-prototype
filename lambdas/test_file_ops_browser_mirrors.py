"""Pins the file-operations values the BROWSER mirrors against the ones that define them.

The browser holds a copy of the state machine's ``TimeoutSeconds`` because it is the outer bound
on an in-flight record: past it the execution is gone, no notification is coming, and there is
nothing left to correlate. Nothing at runtime reports that the two have drifted — an entry
expiring early tells a user an operation is over while it is still running, and one expiring late
holds that space's submit gate long after anything could settle it.

Lives under ``lambdas/`` because that is where pytest runs, alongside ``test_feature_flags_config``
and ``test_deploy_matrix`` — the other files here that read the repo as data rather than exercising
a Lambda.

Attributes:
  ROOT: The repository root.
  LOCALS: The file-operations module's locals, which define the machine's ceiling.
  BROWSER_CONSTANTS: The browser module that mirrors it.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCALS = ROOT / "infra" / "modules" / "file-ops" / "locals.tf"
BROWSER_CONSTANTS = ROOT / "apps" / "portal" / "src" / "features" / "file-browser" / "fileOps.constants.ts"


def _terraform_seconds() -> int:
    """Reads the state machine's timeout out of the Terraform that sets it.

    Args:
      None.

    Returns:
      The ceiling, in seconds.

    Raises:
      AssertionError: If the local is absent or has been reshaped, which would otherwise make
        every comparison below vacuous.
    """
    match = re.search(r"^\s*state_machine_timeout_seconds\s*=\s*(\d+)\s*$", LOCALS.read_text(), re.MULTILINE)
    assert match, "state_machine_timeout_seconds is not declared in the file-ops locals"
    return int(match.group(1))


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
