"""``everActive`` is written once, never cleared, and never written false.

The field decides whether deleting a shared workspace empties it or destroys it. Everything
downstream — the delete route, the guard refusing new members, the refusal to re-create a name —
reads it as a one-way door, and every one of those reads fails toward destruction if the field
can go away. So the property is swept rather than reviewed: a reviewer reads what is there, and
what would break this is a line somebody adds later.

It is a regression guard, not a driver. It passes before the field exists and it passes today;
its value is entirely in the run where somebody has written ``record.pop("everActive")`` into a
teardown path and nothing else notices.
"""

import ast
import pathlib

LAMBDAS = pathlib.Path(__file__).resolve().parent

FIELD = "everActive"


def _source_files():
    """Every non-test Python module under ``lambdas/``.

    Args:
      None.

    Returns:
      The module paths.

    Raises:
      None.
    """
    return [
        path
        for path in sorted(LAMBDAS.rglob("*.py"))
        if "__pycache__" not in path.parts
        and not path.name.startswith("test_")
        and path.name not in ("conftest.py", "fakes.py")
    ]


def _writes(path):
    """Every write of the field in one module, as ``(line, description)`` pairs.

    Three shapes reach the field, and a sweep seeing only the first would miss the two that
    matter: assigning through a subscript, naming it in a dict literal, and removing it with
    ``pop`` or ``del``. The removals are the dangerous ones and they look nothing like an
    assignment.

    Args:
      path: The module to read.

    Returns:
      The writes found, each with the value's unparsed source or the removal's form.

    Raises:
      SyntaxError: If the module does not parse.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == FIELD
                ):
                    found.append((node.lineno, ast.unparse(node.value)))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if isinstance(key, ast.Constant) and key.value == FIELD:
                    found.append((key.lineno, ast.unparse(value)))
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == FIELD
                ):
                    found.append((node.lineno, "del"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "pop"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == FIELD
        ):
            found.append((node.lineno, "pop"))
    return found


def test_the_sweep_found_the_writers():
    """Guards the guard: a sweep matching nothing asserts nothing.

    A version of this that silently found zero writes would pass forever, which is this repo's
    recorded failure mode for exactly this kind of check.
    """
    writers = {path.name: _writes(path) for path in _source_files() if _writes(path)}

    assert "registry.py" in writers, sorted(writers)
    assert len(writers["registry.py"]) >= 2, writers["registry.py"]


def test_the_field_is_only_ever_written_true():
    offenders = [
        (str(path.relative_to(LAMBDAS)), line, value)
        for path in _source_files()
        for line, value in _writes(path)
        if value != "True"
    ]

    assert offenders == [], (
        f"{offenders} write {FIELD} to something other than True. It is a one-way door: the "
        "delete route, the add guard and the re-create refusal all read it, and each of them "
        "fails toward destroying a live workspace if it can be cleared."
    )
