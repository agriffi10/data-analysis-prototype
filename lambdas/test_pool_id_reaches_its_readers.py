"""``COGNITO_USER_POOL_ID`` reaches every module that reads it, and no module that does not.

It used to be a fleet-wide contract: a name in ``cpcommon.config._REQUIRED_VARS``, set by every
control plane's Terraform, asserted per plane by the common-environment guard. When the planes
stopped verifying tokens it lost that status — only the three that look a *recipient* up still
need it — and it moved to a lazy ``config.require`` at the call site.

**That trade left a hole this file closes.** A required variable that goes missing raises at cold
start on every function; a lazily-required one raises on the first invocation that reaches the
call, which on these planes is the first time somebody sends a file or adds a member. Nothing
offline tied the three Terraform environments to the five reader sites, so pruning the variable
from one module's ``variables.tf`` — an obvious tidy, since nothing else in that module names it —
would produce a ``RuntimeError`` mid-request with the whole suite green.

**What this does and does not close.** It pins two populations — the modules that read the
variable, and the Terraform modules that set it — so that changing either without the other is a
failure. Pruning the variable from one plane's `lambda.tf` reddens it, which is the tidy this
exists to stop.

It does **not** relate a consumer to a setter. A verb on a plane that sets nothing could import
`cpcommon.cognito` and reach `user_exists`, and only the first assertion would catch it — by
noticing that `cognito.py` is still the reader, which it is. That gap is real and the honest
version of closing it is a call-graph walk from each reader back to the verbs that import it and
on to the deploy matrix, which `test_actor_fleet.py` does for its own population. It is not built
here because the three-plane set is small enough to check by hand and the first assertion makes a
NEW reader loud; if a fourth plane ever needs a recipient lookup, build the walk rather than
adding a row.

The detection is also literal-text: a module naming the variable through a constant is invisible
to it. That is the same extractor weakness that let a retired tripwire pass wrongly, and it is
tolerable only because the population it guards is two files.

Attributes:
  LAMBDAS: The fleet root.
  INFRA: The Terraform root.
  POOL_VAR: The environment variable under test.
  READER_MODULES: The layer modules whose code reads it, as an assertion rather than a list — the
    test derives the real set and compares, so a fourth reader appearing is a failure here rather
    than a surprise in production.
  EXPECTED_PLANES: The Terraform modules expected to set it, for the same reason.
"""

import pathlib
import re

LAMBDAS = pathlib.Path(__file__).resolve().parent
INFRA = LAMBDAS.parent / "infra" / "modules"

POOL_VAR = "COGNITO_USER_POOL_ID"

READER_MODULES = {
    "control-plane-common/cpcommon/cognito.py",
    "shared-space-common/membership.py",
}

EXPECTED_PLANES = {"shared-spaces", "file-send", "table-share"}


def _modules_reading_the_pool() -> set[str]:
    """Every shipped module naming the variable.

    Args:
      None.

    Returns:
      The module paths, relative to the fleet root.

    Raises:
      None.
    """
    return {
        str(path.relative_to(LAMBDAS))
        for path in LAMBDAS.rglob("*.py")
        if not path.name.startswith(("test_", "conftest."))
        and "__pycache__" not in path.parts
        and POOL_VAR in path.read_text(encoding="utf-8")
    }


def _planes_setting_the_pool() -> set[str]:
    """Every Terraform module whose Lambda environment sets the variable.

    Args:
      None.

    Returns:
      The module directory names.

    Raises:
      None.
    """
    setter = re.compile(rf"^\s*{POOL_VAR}\s*=", re.MULTILINE)
    return {
        path.parent.name
        for path in INFRA.rglob("lambda.tf")
        if setter.search(path.read_text(encoding="utf-8"))
    }


def test_the_readers_are_the_ones_this_file_knows_about() -> None:
    """A fourth reader is a fourth plane that needs the grant, and it must not arrive quietly.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the set of modules reading the variable changed.
    """
    found = _modules_reading_the_pool()

    assert found == READER_MODULES, (
        f"the modules reading {POOL_VAR} are now {sorted(found)}. It is no longer a fleet-wide "
        "required variable, so a new reader needs the variable added to its plane's Terraform "
        "environment — and this file updated to say so"
    )


def test_every_plane_whose_verbs_can_reach_a_reader_sets_the_variable() -> None:
    """The set of planes granting the variable is the set expected to need it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane sets the variable without needing it, or needs it without
        setting it.
    """
    setting = _planes_setting_the_pool()

    assert setting == EXPECTED_PLANES, (
        f"{POOL_VAR} is set by {sorted(setting)}, expected {sorted(EXPECTED_PLANES)}. A plane "
        "that resolves a recipient and does NOT set it raises RuntimeError mid-request rather "
        "than at cold start — the variable is lazily required now, so nothing else catches it"
    )
