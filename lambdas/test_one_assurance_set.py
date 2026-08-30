"""One module in the fleet decides which principal kinds a control plane will act on.

``cpcommon.actor.ACCEPTED_ASSURANCE`` is that module's set. A plane that declared its own would
widen quietly — and the widening that matters is the one a later arc makes when it mints a
machine-facing principal, where "whichever plane relaxed first accepts it" is the outcome the
single set exists to prevent.

The agreement between that set and the value the API mints is asserted separately, by import, in
``api/test_assurance_literal_agreement.py`` — ``apicommon`` is not a layer, so it is importable
only from the API's own suite.

Attributes:
  LAMBDAS: The fleet root, and the sweep's subject.
  EXCLUDED_NAMES: Files that are not shipped modules.
  ONE_ACCEPTED_SET: Where the fleet's only accepted-assurance set is allowed to live.
"""

import ast
import pathlib

from cpcommon import actor as cpactor

LAMBDAS = pathlib.Path(__file__).resolve().parent

EXCLUDED_NAMES = ("test_", "conftest.")

ONE_ACCEPTED_SET = "control-plane-common/cpcommon/actor.py"


def _shipped_modules() -> list[pathlib.Path]:
    """Every module that reaches a Lambda, selected by path.

    Args:
      None.

    Returns:
      The sorted module paths.

    Raises:
      None.
    """
    return sorted(
        path
        for path in LAMBDAS.rglob("*.py")
        if not path.name.startswith(EXCLUDED_NAMES) and "__pycache__" not in path.parts
    )


def _builds_an_assurance_set(path: pathlib.Path) -> bool:
    """Reports whether a module builds a set or frozenset containing an assurance value.

    Parsed rather than grepped: a module may explain in prose why it does not declare its own
    accepted set without tripping the check on its own docstring.

    Args:
      path: The module to parse.

    Returns:
      True if the module constructs a set literal or ``frozenset`` call holding a known value.

    Raises:
      None.
    """
    values = {cpactor.ASSURANCE_INTERACTIVE, "delegated"}
    names = {"ASSURANCE_INTERACTIVE", "ASSURANCE_DELEGATED"}

    def _holds(node: ast.AST) -> bool:
        """Matches a member written as a literal OR as the constant naming it.

        Both spellings, because the module this sweep exists to pin uses the second one — a
        literal-only match found zero declarers including its own subject, which the
        subject assertion above is what caught.

        Args:
          node: The set literal or the frozenset call's first argument.

        Returns:
          True if any member is a known assurance value.

        Raises:
          None.
        """
        for element in getattr(node, "elts", []):
            if isinstance(element, ast.Constant) and element.value in values:
                return True
            if isinstance(element, ast.Name) and element.id in names:
                return True
            if isinstance(element, ast.Attribute) and element.attr in names:
                return True
        return False

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Set) and _holds(node):
            return True
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "frozenset"
            and node.args
            and _holds(node.args[0])
        ):
            return True
    return False


def test_no_second_module_declares_an_accepted_assurance_set() -> None:
    """A per-plane accepted set is a plane that quietly widens while the shared one holds.

    The subject set is asserted first: a filter that excluded everything would read as a clean
    pass on the claim below.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the sweep lost its subject, or a second module declares the set.
    """
    modules = _shipped_modules()
    relative = {str(path.relative_to(LAMBDAS)) for path in modules}

    assert len(relative) > 50, f"the sweep's subject collapsed to {len(relative)} modules"
    assert ONE_ACCEPTED_SET in relative, "the sweep lost the module it exists to pin"

    declarers = [
        str(path.relative_to(LAMBDAS))
        for path in modules
        if _builds_an_assurance_set(path)
    ]

    assert declarers == [ONE_ACCEPTED_SET], (
        f"{declarers} declare an accepted-assurance set — one widening in one module is what "
        "keeps a machine principal from being accepted by whichever plane relaxed first"
    )
