"""Pins the add-members cap the BROWSER mirrors against the API bound that enforces it.

The browser refuses a longer paste in words so the user never meets the API's generic
"over its limit" sentence, and nothing at runtime reports that the two numbers drifted.

Attributes:
  ROOT: The repository root.
  BROWSER_MODULE: The browser module that mirrors the bound.
"""

import pathlib
import re

from api.apicommon import bounds

ROOT = pathlib.Path(__file__).resolve().parent.parent
BROWSER_MODULE = ROOT / "apps" / "portal" / "src" / "features" / "shared-spaces" / "memberInput.ts"


def _browser_cap() -> int:
    """Reads the mirrored cap out of the browser module.

    Args:
      None.

    Returns:
      The mirrored cap.

    Raises:
      AssertionError: If the constant is absent or has been renamed.
    """
    match = re.search(r"export const ADD_MEMBERS_MAX\s*=\s*([\d_]+)\s*;", BROWSER_MODULE.read_text())
    assert match, "ADD_MEMBERS_MAX is not declared in memberInput.ts"
    return int(match.group(1).replace("_", ""))


def test_the_browser_mirrors_the_apis_member_bound():
    """The dialog's cap is the bound the API refuses at, not a number beside it."""
    assert _browser_cap() == bounds.MAX_MEMBERS_PER_REQUEST
