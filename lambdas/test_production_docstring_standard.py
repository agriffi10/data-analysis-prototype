"""Every production module under ``lambdas/`` carries no comments and documents every definition.

The rule is ``lambdas/info/best-practices/python/python.md`` §14's, and it is absolute for this
tree: the only ``#`` permitted is a lint directive, and every module, class, method and function —
``_private`` and nested ones included — has a docstring, a function's writing out ``Args:``,
``Returns:`` (``Yields:`` for a generator) and ``Raises:``. Nothing held it, and ninety-odd comments
and an undocumented closure accumulated across fourteen modules before an audit swept them by
hand. A rule that has to be re-swept by hand is not being held.

**The scope is production code.** Test modules, ``conftest.py`` and ``fakes.py`` are left out: they
are not shipped as handlers, and the suites carry comments and undocumented helpers throughout, so
including them would be a different decision from the one this file enforces.

The checks read TOKENS for comments and the AST for docstrings, so a ``#`` inside a string is never
a comment and a docstring is never mistaken for one. Each check owns a plant in the corpus below
that must redden it, and a clean module that must not.

Attributes:
  LAMBDAS: The tree the sweep walks.
  NOT_OURS: Directory names holding code this repo does not write.
  SUPPORT_FILES: Non-test basenames that exist only to serve the suites.
  DIRECTIVE: A comment that is a lint directive rather than prose.
"""

import ast
import io
import pathlib
import re
import tokenize

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
NOT_OURS = frozenset({"__pycache__", "node_modules", "build", "dist", "venv", ".venv"})
SUPPORT_FILES = frozenset({"conftest.py", "fakes.py"})
DIRECTIVE = re.compile(r"#\s*(noqa\b|type:\s*ignore\b)")


def _production_modules() -> list[pathlib.Path]:
    """Lists every production module under the tree, in a stable order.

    Args:
      None.

    Returns:
      The module paths.

    Raises:
      None.
    """
    return sorted(
        path
        for path in LAMBDAS.rglob("*.py")
        if not NOT_OURS.intersection(path.relative_to(LAMBDAS).parts)
        and not path.name.startswith("test_")
        and path.name not in SUPPORT_FILES
    )


def _comments(source: str) -> list[str]:
    """Finds every comment in a module that is not a lint directive or a shebang.

    Args:
      source: The module's text.

    Returns:
      ``"line N"`` for each offending comment.

    Raises:
      tokenize.TokenError: If the source cannot be tokenized.
    """
    found = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if token.start[0] == 1 and token.string.startswith("#!"):
            continue
        if DIRECTIVE.match(token.string):
            continue
        found.append(f"line {token.start[0]}: comment")
    return found


def _missing_sections(node: ast.FunctionDef | ast.AsyncFunctionDef, doc: str) -> list[str]:
    """Names the docstring sections a function leaves out.

    A generator documents what it yields, and ``Returns:`` is accepted in its place because the
    fleet's existing generators say so either way.

    Args:
      node: The function.
      doc: Its docstring.

    Returns:
      The missing section headers.

    Raises:
      None.
    """
    generator = any(isinstance(inner, ast.Yield | ast.YieldFrom) for inner in ast.walk(node))
    produces = ("Yields:", "Returns:") if generator else ("Returns:",)
    missing = [
        header
        for header in ("Args:", "Raises:")
        if not re.search(rf"^\s*{header}", doc, re.MULTILINE)
    ]
    if not any(re.search(rf"^\s*{header}", doc, re.MULTILINE) for header in produces):
        missing.append(produces[0])
    return missing


def offences(source: str) -> list[str]:
    """Every way one module breaks the standard.

    Args:
      source: The module's text.

    Returns:
      One entry per offence, empty for a module that holds the standard.

    Raises:
      SyntaxError: If the source does not parse.
    """
    found = _comments(source)
    tree = ast.parse(source)
    if not ast.get_docstring(tree):
        found.append("line 1: module has no docstring")
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            found.append(f"line {node.lineno}: {node.name} has no docstring")
        elif not isinstance(node, ast.ClassDef):
            for header in _missing_sections(node, doc):
                found.append(f"line {node.lineno}: {node.name} has no {header}")
    return found


def test_no_production_module_breaks_the_standard():
    """The sweep, over every production module in the tree."""
    modules = _production_modules()
    broken = {
        str(path.relative_to(LAMBDAS)): found
        for path in modules
        if (found := offences(path.read_text(encoding="utf-8")))
    }

    assert len(modules) > 100, "the sweep found almost nothing to read — its scope is wrong"
    assert broken == {}


_DOCUMENTED = '''
def f(a):
    """Does f.

    Args:
      a: A.

    Returns:
      None.

    Raises:
      None.
    """
'''


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('"""M."""\n' + _DOCUMENTED + "x = 1  # explained here\n", "comment"),
        ('"""M."""\n# a block comment\n' + _DOCUMENTED, "comment"),
        (_DOCUMENTED, "module has no docstring"),
        ('"""M."""\ndef f():\n    return 1\n', "f has no docstring"),
        ('"""M."""\n' + _DOCUMENTED.replace("    Args:\n      a: A.\n\n", ""), "f has no Args:"),
        ('"""M."""\n' + _DOCUMENTED.replace("    Returns:\n      None.\n\n", ""), "f has no Returns:"),
        ('"""M."""\n' + _DOCUMENTED.replace("\n    Raises:\n      None.\n", ""), "f has no Raises:"),
        (
            '"""M."""\n' + _DOCUMENTED.replace('    """\n', '    """\n    def inner():\n        pass\n', 1),
            "inner has no docstring",
        ),
        ('"""M."""\nclass C:\n    pass\n', "C has no docstring"),
    ],
    ids=[
        "trailing-comment",
        "block-comment",
        "module-docstring",
        "function-docstring",
        "args",
        "returns",
        "raises",
        "nested-closure",
        "class-docstring",
    ],
)
def test_each_check_names_the_offence_it_was_planted_for(source, expected):
    """Each check reddens on its own plant, and names the offence rather than just counting one."""
    found = offences(source)

    assert any(entry.endswith(expected) for entry in found), found


@pytest.mark.parametrize(
    "source",
    [
        '"""M."""\n' + _DOCUMENTED + "x = 1  # noqa: E501 - long by design\n",
        '"""M."""\n' + _DOCUMENTED + "x = f(1)  # type: ignore[arg-type]\n",
        '#!/usr/bin/env python3\n"""M."""\n' + _DOCUMENTED,
        '"""M."""\n' + _DOCUMENTED + 'URL = "https://example.test/#anchor"\n',
        '"""M."""\nclass C:\n    """A C, whose docstring needs no sections."""\n',
        '"""M."""\n'
        + _DOCUMENTED.replace("def f(a)", "def g(a)").replace("    Returns:", "    Yields:")
        + "    yield a\n",
    ],
    ids=["noqa", "type-ignore", "shebang", "hash-in-a-string", "class-summary", "generator-yields"],
)
def test_what_the_standard_permits_stays_silent(source):
    """A directive, a shebang, a ``#`` inside a string, a class summary and a generator's
    ``Yields:`` are all within the standard, and a check that fired on one would be switched off
    rather than obeyed."""
    assert offences(source) == []
