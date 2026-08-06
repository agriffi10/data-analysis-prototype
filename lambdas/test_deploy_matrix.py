"""The deploy matrix must attach a layer for every layer package a function imports.

**This is the test that was missing when signup broke.** SPEC-137 added
``from cpcommon import observability`` to ``pre_signup.py``, ``post_confirmation.py`` and
``notifications_writer.py`` and never set ``cpcommon: true`` on their rows in
``deploy-lambdas.yml``. All three deployed code that could not import, and on pre-signup that is
a Cognito trigger — so real signups failed with a trigger error.

Nothing existing could have caught it, and the reasons are worth stating because they are all
still true:

* **pytest cannot see it.** ``conftest.py`` puts every layer package root on ``sys.path``, so
  every import that would fail in Lambda succeeds under test, by design.
* **The deploy cannot see it.** ``update-function-code`` succeeds against a function that raises
  ``ModuleNotFoundError`` at cold start; the deploy job went green.
* **The instrumentation harness cannot see it.** ``test_instrumentation_coverage.py`` asserts
  these modules are *instrumented*, which is exactly what put the unresolvable import there.

So this test reads the workflow's matrix as data and joins it against what each module actually
imports. It is the only place in the suite where a Lambda's PACKAGING is checked rather than its
behaviour.
"""

import ast
import pathlib
import re

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
WORKFLOW = LAMBDAS.parent / ".github" / "workflows" / "deploy-lambdas.yml"

#: Top-level package (or flat module) name → the matrix flag whose layer provides it.
#:
#: ``shared-space-common`` publishes FLAT modules rather than a package (deploy-lambdas.yml's
#: `layer` job copies `$m.py` for each), which is why its entries are individual module names.
LAYER_PACKAGES = {
    "cpcommon": "cpcommon",
    "tbcommon": "tbcommon",
    "tscommon": "tscommon",
    "dqcommon": "dqcommon",
    "polars": None,  # two different polars layers — resolved per function below
    **dict.fromkeys(("casio", "registry", "membership", "teardown", "messages"), "layer"),
}

#: The two polars layers are the same import with different flags: table-builder's verb attaches
#: `polars`, data-quality's attaches `dqpolars`. Either satisfies the import.
POLARS_FLAGS = ("polars", "dqpolars")

_ROW_RE = re.compile(r"^\s*-\s*\{\s*name:\s*([a-z0-9-]+)\s*,(.*)\}\s*$")
_FLAG_RE = re.compile(r"(\w+)\s*:\s*(true|false)")


def _matrix_rows():
    """Every ``- { name: …, flag: bool, … }`` row in the deploy matrix, as (name, flags).

    Deliberately a regex over the raw file rather than a YAML parse: PyYAML is not a test
    dependency, and the rows are a fixed one-line shape that a reader can check by eye. A row
    reformatted onto several lines stops matching — which the row-count guard below turns into a
    failure rather than a silent skip.
    """
    rows = {}
    for line in WORKFLOW.read_text().splitlines():
        match = _ROW_RE.match(line)
        if match:
            name, rest = match.groups()
            rows[name] = {k: v == "true" for k, v in _FLAG_RE.findall(rest)}
    return rows


MATRIX = _matrix_rows()


def _handler_dirs():
    """Every ``lambdas/<name>/`` holding a module that defines a top-level ``handler``.

    Same definition of "is a Lambda" as ``test_instrumentation_coverage.py`` uses, so the two
    harnesses cannot drift into covering different fleets.
    """
    found = {}
    for directory in sorted(LAMBDAS.iterdir()):
        if not directory.is_dir() or directory.name.startswith((".", "_")):
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text())
            if any(
                isinstance(node, ast.FunctionDef) and node.name == "handler"
                for node in tree.body
            ):
                found.setdefault(directory.name, []).append(path)
    return found


HANDLER_DIRS = _handler_dirs()
_DIR_IDS = sorted(HANDLER_DIRS)


def _imported_roots(paths):
    """The top-level package names imported by any module in one function's directory.

    Walks the whole tree rather than only ``tree.body``: ``post_confirmation.py`` imports
    ``cpcommon`` below its ``logging`` setup, and a lazily-imported layer package inside a
    function body needs the layer attached just as much as a top-level one does.
    """
    roots = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_matrix_was_actually_parsed():
    """Guards the guard: a regex that matches nothing makes every test below vacuous."""
    assert len(MATRIX) >= 30, f"only parsed {len(MATRIX)} matrix rows from {WORKFLOW.name}"
    # A row with a known-good, multi-layer shape, so a partial parse fails here rather than
    # passing a function whose flags were silently dropped.
    assert MATRIX.get("data-quality-inspect-source") == {
        "layer": False,
        "polars": False,
        "tbcommon": False,
        "cpcommon": True,
        "dqcommon": True,
        "dqpolars": True,
    }, "the reference row did not parse as expected — the matrix format changed"


def test_the_handler_sweep_found_the_fleet():
    assert len(HANDLER_DIRS) >= 30, f"only found {len(HANDLER_DIRS)} Lambda directories"


@pytest.mark.parametrize("name", _DIR_IDS)
def test_every_lambda_directory_is_in_the_deploy_matrix(name):
    """A function with code and no matrix row is never deployed at all — the quietest failure
    of the set, because everything about it looks finished.
    """
    assert name in MATRIX, f"lambdas/{name}/ has a handler but no row in {WORKFLOW.name}"


@pytest.mark.parametrize("name", _DIR_IDS)
def test_every_imported_layer_package_is_attached(name):
    """The signup break, as an assertion.

    An import of a layer package with the matching flag unset is a ``ModuleNotFoundError`` at
    cold start — after a green test run and a green deploy.
    """
    flags = MATRIX.get(name)
    if flags is None:
        pytest.skip("covered by test_every_lambda_directory_is_in_the_deploy_matrix")

    missing = []
    for root in sorted(_imported_roots(HANDLER_DIRS[name])):
        if root not in LAYER_PACKAGES:
            continue
        if root == "polars":
            if not any(flags.get(f) for f in POLARS_FLAGS):
                missing.append(f"{root} (needs one of {' / '.join(POLARS_FLAGS)})")
            continue
        flag = LAYER_PACKAGES[root]
        if not flags.get(flag):
            missing.append(f"{root} (needs `{flag}: true`)")

    assert not missing, (
        f"lambdas/{name}/ imports {', '.join(missing)} but its {WORKFLOW.name} row does not "
        f"attach the layer — the function will raise ModuleNotFoundError at cold start"
    )
