"""The feedback caps the browser mirrors, held against the ones the route enforces.

The route is the control and the dialog's checks are a courtesy — but a courtesy that disagrees
is worse than none. A browser cap ABOVE the route's lets a user write four thousand and one
characters and lose the overflow to a refusal they were given no warning of; one BELOW it refuses
a message the server would have taken. Neither shows up in either suite alone, because each side
tests against its own number.

The Python side is read as the source and the TypeScript is parsed out of the constants module,
rather than both being read from a third literal here — a third copy agrees with itself while the
two that matter drift.

Attributes:
  ROUTE: The handler declaring the caps.
  CONSTANTS: The browser module mirroring them.
"""

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
ROUTE = REPO / "lambdas" / "api" / "routes" / "feedback.py"
CONSTANTS = REPO / "apps" / "portal" / "src" / "features" / "feedback" / "feedback.constants.ts"


def _python_cap(name: str) -> int:
    """Reads one module-level integer constant from the route.

    Parsed rather than imported: importing the route pulls in the whole API package and its
    configuration, which this file has no reason to stand up.

    Args:
      name: The constant's name.

    Returns:
      Its value.

    Raises:
      AssertionError: If the route does not declare it, which means it was renamed and the mirror
        below is now pinned to nothing.
    """
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == name for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            return int(node.value.value)
    raise AssertionError(f"{ROUTE.name} declares no {name}")


def _typescript_cap(name: str) -> int:
    """Reads one exported numeric constant from the browser's constants module.

    Args:
      name: The constant's name.

    Returns:
      Its value.

    Raises:
      AssertionError: If the module does not export it.
    """
    found = re.search(
        rf"^export const {name} = (\d+);$", CONSTANTS.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert found, f"{CONSTANTS.name} exports no {name}"
    return int(found.group(1))


def test_both_files_are_where_this_test_thinks_they_are() -> None:
    """Guard the guard: over a missing file every comparison below is unreachable, not passing."""
    assert ROUTE.is_file(), ROUTE
    assert CONSTANTS.is_file(), CONSTANTS


@pytest.mark.parametrize(
    ("python_name", "typescript_name"),
    [("MAX_MESSAGE_CHARS", "MAX_FEEDBACK_MESSAGE_CHARS")],
)
def test_the_browsers_cap_is_the_routes_cap(python_name: str, typescript_name: str) -> None:
    """Equal, not merely ordered: a mirror that is only "no larger" still refuses a valid message."""
    enforced = _python_cap(python_name)
    mirrored = _typescript_cap(typescript_name)

    assert mirrored == enforced, (
        f"the dialog caps the message at {mirrored} and the route enforces {enforced}. A higher "
        "mirror loses a user's overflow to a refusal they were not warned about; a lower one "
        "refuses a message the server would have accepted."
    )


def test_the_dialog_stops_typing_at_the_cap_rather_than_only_checking_it() -> None:
    """The `maxLength` is what makes the mirror a courtesy rather than a second refusal.

    Without it the constant is only read at submit, so a user writes past the limit and is told
    afterwards — which is exactly the experience the server-side cap already provides.
    """
    dialog = (CONSTANTS.parent / "FeedbackDialog.tsx").read_text(encoding="utf-8")

    assert "maxLength={MAX_FEEDBACK_MESSAGE_CHARS}" in dialog, (
        "the message field does not bound typing at the mirrored cap"
    )
