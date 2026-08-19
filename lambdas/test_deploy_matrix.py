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
#:
#: All nine flat modules are listed for accuracy — the four added by SPEC-153 (``config``,
#: ``auth``, ``cache``, ``notify``) were missing, and ``:157`` silently ``continue``d past them.
#: Completing the map does NOT close SPEC-137's shape, though: all nine ship in ONE layer behind
#: ONE flag, so a module that never reaches the zip is invisible here no matter how complete this
#: dict is. ``test_the_layer_copy_list_matches_the_layer_directory`` below is what closes it.
LAYER_PACKAGES = {
    "focommon": "focommon",
    "cpcommon": "cpcommon",
    "tbcommon": "tbcommon",
    "tscommon": "tscommon",
    "dqcommon": "dqcommon",
    "fscommon": "fscommon",
    "arcommon": "arcommon",
    "polars": None,  # two different polars layers — resolved per function below
    **dict.fromkeys(
        ("config", "casio", "auth", "registry", "membership", "cache", "notify", "messages",
         "teardown"),
        "layer",
    ),
}

#: Layer source directories packaged by an EXPLICIT per-file copy list in deploy-lambdas.yml,
#: mapped to the shell loop that names the files. Every other layer copies a whole package
#: directory (``cp -r lambdas/<x>-common/<x>common``) or pip-installs into the layer root, so a
#: new module there ships automatically and there is no list to drift from — those are exempt for
#: that named reason, and ``test_no_unchecked_explicit_copy_list_was_added`` fails if a second
#: explicit list appears without being added here.
EXPLICIT_COPY_LISTS = {"shared-space-common": re.compile(r"for m in ([a-z0-9_ ]+); do")}

#: Files under a layer source directory that are deliberately NOT shipped.
_NOT_SHIPPED = ("test_", "conftest.py", "fakes.py", "__init__.py")

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


def _copy_list(directory):
    """The module names the layer job copies for ``directory``, as a set."""
    match = EXPLICIT_COPY_LISTS[directory].search(WORKFLOW.read_text())
    assert match, f"no copy list found for {directory} in {WORKFLOW.name} — did the job change?"
    return set(match.group(1).split())


def _shipped_modules(directory):
    """The production Python modules present in ``lambdas/<directory>/``, as a set."""
    return {
        path.stem
        for path in (LAMBDAS / directory).glob("*.py")
        if not path.name.startswith(_NOT_SHIPPED)
    }


@pytest.mark.parametrize("directory", sorted(EXPLICIT_COPY_LISTS))
def test_the_layer_copy_list_matches_the_layer_directory(directory):
    """SPEC-137's shape, at the layer boundary rather than the flag map.

    The flag map above says *which functions attach the layer*. Nothing said what the layer
    CONTAINS. Add a module to ``lambdas/shared-space-common/``, import it from a function whose
    row already reads ``layer: true``, and every existing check passes — the matrix test is
    satisfied, the deploy goes green, and the function raises ``ModuleNotFoundError`` at cold
    start. That is SPEC-137 again, straight through the gate built to stop it.

    Set equality in both directions: a module in the directory and not the list never ships, and
    a module in the list and not the directory makes the layer job's ``cp`` fail at deploy time.
    """
    listed, present = _copy_list(directory), _shipped_modules(directory)
    assert listed == present, (
        f"{WORKFLOW.name}'s layer copy list and lambdas/{directory}/ disagree — "
        f"in the directory but never shipped: {sorted(present - listed) or 'none'}; "
        f"listed but absent from the directory: {sorted(listed - present) or 'none'}"
    )


@pytest.mark.parametrize("directory", sorted(EXPLICIT_COPY_LISTS))
def test_the_layer_copy_list_was_actually_parsed(directory):
    """Guards the guard: two empty sets are equal, so an unparsed list passes vacuously."""
    assert len(_copy_list(directory)) >= 8, f"only parsed {_copy_list(directory)} for {directory}"
    assert len(_shipped_modules(directory)) >= 8, f"only found {_shipped_modules(directory)}"


def test_no_lambda_directory_shadows_a_flat_layer_module():
    """Guards the flat entries in ``LAYER_PACKAGES`` against a false positive.

    ``config``, ``auth``, ``cache`` and ``notify`` are resolved to the shared-space layer by
    NAME alone — there is no package prefix to disambiguate a flat module. If a verb ever
    grows its own ``config.py``, ``import config`` in that verb would be read as an import
    of the layer's, and ``test_every_imported_layer_package_is_attached`` would demand
    ``layer: true`` on a function that needs no layer at all. ``config.py`` is the single
    most likely local module name in this fleet, so the collision is worth failing on here —
    where the message says what happened — rather than inside a confusing packaging assertion.
    """
    flat = {root for root, flag in LAYER_PACKAGES.items() if flag == "layer"}
    shadows = sorted(
        f"lambdas/{directory}/{module}.py"
        for directory in HANDLER_DIRS
        for module in flat
        if (LAMBDAS / directory / f"{module}.py").exists()
    )

    assert not shadows, (
        f"these shadow a flat shared-space layer module, so LAYER_PACKAGES would resolve "
        f"their imports to the layer: {shadows}"
    )


def test_no_unchecked_explicit_copy_list_was_added():
    """A second per-file layer list must join ``EXPLICIT_COPY_LISTS``, not drift unchecked."""
    loops = re.findall(r"for m in [a-z0-9_ ]+; do", WORKFLOW.read_text())
    assert len(loops) == len(EXPLICIT_COPY_LISTS), (
        f"{WORKFLOW.name} has {len(loops)} per-file layer copy loops but "
        f"{len(EXPLICIT_COPY_LISTS)} are checked — add the new one to EXPLICIT_COPY_LISTS"
    )


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
