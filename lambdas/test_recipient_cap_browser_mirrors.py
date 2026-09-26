"""Pins the recipient caps the BROWSER mirrors against the planes that enforce them.

The browser refuses an over-cap send or share at once, where the plane would refuse it minutes
later by notification after the browser had said "requested". Nothing at runtime reports the two
numbers drifting apart.

Attributes:
  ROOT: The repository root.
  PAIRS: For each plane, its config module, the constant it enforces, the browser service that
    mirrors it, and the mirrored constant's name.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
PORTAL = ROOT.parent / "apps" / "portal" / "src" / "features"

PAIRS = [
    (
        ROOT / "file-send-common" / "fscommon" / "config.py",
        "SEND_MAX_RECIPIENTS",
        PORTAL / "file-send" / "fileSend.service.ts",
        "SEND_MAX_RECIPIENTS",
    ),
    (
        ROOT / "table-share-common" / "tscommon" / "config.py",
        "SHARE_MAX_RECIPIENTS",
        PORTAL / "table-share" / "tableShare.service.ts",
        "SHARE_MAX_RECIPIENTS",
    ),
]


def _declared(path: pathlib.Path, pattern: str, name: str) -> int:
    """Reads one integer constant out of a source file.

    Args:
      path: The file declaring it.
      pattern: The declaration's regex, with one group capturing the digits.
      name: The constant's name, for the failure message.

    Returns:
      The constant's value.

    Raises:
      AssertionError: If the declaration is absent or reshaped, which would make the comparison
        vacuous.
    """
    match = re.search(pattern, path.read_text(), re.MULTILINE)
    assert match, f"{name} is not declared in {path.name}"
    return int(match.group(1).replace("_", ""))


@pytest.mark.parametrize(("plane", "plane_name", "browser", "browser_name"), PAIRS)
def test_the_browser_mirrors_the_planes_recipient_cap(plane, plane_name, browser, browser_name):
    """The service's cap is the number the plane refuses at, not a number beside it."""
    enforced = _declared(plane, rf"^{plane_name}\s*=\s*([\d_]+)\s*$", plane_name)
    mirrored = _declared(browser, rf"export const {browser_name}\s*=\s*([\d_]+)\s*;", browser_name)
    assert mirrored == enforced
