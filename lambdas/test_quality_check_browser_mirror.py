"""Pins the folders the BROWSER refuses a data-quality check on against the plane's own list.

The plane refuses these as ``forbidden``, whose sentence is "You don't have access", which is false
of a folder the user can open. The browser refuses first, in words, and only while its list is the
plane's: a folder missing from it reaches the false sentence again, and an extra one refuses a
check the plane would run.

Attributes:
  ROOT: The repository root.
  BROWSER_MODULE: The browser module that mirrors the list.
"""

import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "data-quality-common"))

from dqcommon import config  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BROWSER_MODULE = ROOT / "apps" / "portal" / "src" / "features" / "data-quality" / "qualityCheckRefusal.ts"


def _browser_roots() -> set[str]:
    """Reads the mirrored folder names out of the browser module.

    Args:
      None.

    Returns:
      The folder names the browser refuses.

    Raises:
      AssertionError: If the constant is absent or has been reshaped.
    """
    match = re.search(
        r"export const QUALITY_CHECK_RESERVED_ROOTS = \[(.*?)\] as const;", BROWSER_MODULE.read_text(), re.DOTALL
    )
    assert match, "QUALITY_CHECK_RESERVED_ROOTS is not declared in qualityCheckRefusal.ts"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_the_browser_refuses_exactly_the_folders_the_plane_does():
    """Set equality, so neither a missing nor an extra folder passes."""
    assert _browser_roots() == set(config.RESERVED_PREFIXES)
