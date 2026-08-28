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
* **An instrumentation check cannot see it.** Asserting these modules are *instrumented* is
  exactly what put the unresolvable import there.

So this test reads the deploy table as data and joins it against what each module actually
imports. It is the only place in the suite where a Lambda's PACKAGING is checked rather than its
behaviour.

The table lives in ``.github/lambda-functions.json`` rather than in the workflow's
``strategy.matrix``, because the per-function jobs are now sharded — see ``_matrix_rows``. That
move added a second way to deploy nothing while reporting success (a shard expression that
selects no functions), which ``test_every_function_lands_in_exactly_one_shard`` closes.
"""

import ast
import importlib.util
import json
import pathlib
import re

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
WORKFLOW = LAMBDAS.parent / ".github" / "workflows" / "deploy-lambdas.yml"
#: The function table the deploy shards read. Split out of the workflow's `strategy.matrix`
#: when the per-function jobs were sharded for cost — see `_matrix_rows`.
FUNCTIONS = LAMBDAS.parent / ".github" / "lambda-functions.json"
#: The layer table the single `layers` job builds from. Ten one-minute jobs became one for
#: the same rounding reason as the deploy matrix; the per-layer build differences turned out
#: to be three shapes over this table.
LAYERS = LAMBDAS.parent / ".github" / "lambda-layers.json"
#: The script that attaches layers, whose hardcoded order is the one that actually reaches
#: `update-function-configuration`.
DEPLOY_SCRIPT = LAMBDAS.parent / ".github" / "scripts" / "deploy-lambda.sh"

_plan_spec = importlib.util.spec_from_file_location(
    "plan_deploy", LAMBDAS.parent / ".github" / "scripts" / "plan_deploy.py"
)
plan_deploy = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(plan_deploy)

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

#: Layer source directories packaged by an EXPLICIT per-file module list (a ``modules`` key in
#: the layer table), mapped to that list. Every other layer copies a whole package directory or
#: pip-installs into the layer root, so a new module there ships automatically and there is no
#: list to drift from — those are exempt for that named reason, and
#: ``test_no_unchecked_explicit_copy_list_was_added`` fails if a second explicit list appears
#: without being added here.
EXPLICIT_COPY_LISTS = {"shared-space-common"}

#: Files under a layer source directory that are deliberately NOT shipped.
_NOT_SHIPPED = ("test_", "conftest.py", "fakes.py", "__init__.py")

#: The two polars layers are the same import with different flags: table-builder's verb attaches
#: `polars`, data-quality's attaches `dqpolars`. Either satisfies the import.
POLARS_FLAGS = ("polars", "dqpolars")


def _matrix_rows():
    """Every function in the deploy table, as ``{name: {flag: True}}``.

    The table used to be a ``strategy.matrix`` in the workflow and this used to be a regex over
    the raw YAML. It moved to ``.github/lambda-functions.json`` when the per-function matrix was
    sharded for cost: a matrix creates one job per entry, GitHub bills every job a whole minute,
    and 73 twenty-nine-second jobs were 46% of the repo's Actions spend. A shard job has to read
    its share of the table as DATA, which a matrix cannot express.

    Only true flags are stored, so a flag is absent rather than ``False``. Every consumer below
    reads through ``.get()``, for which the two are the same answer.
    """
    table = json.loads(FUNCTIONS.read_text())
    return {entry["name"]: dict.fromkeys(entry["layers"], True) for entry in table}


MATRIX = _matrix_rows()


def _handler_dirs():
    """Every ``lambdas/<name>/`` holding a module that defines a top-level ``handler``.

    One definition of "is a Lambda", so harnesses over the fleet cannot drift into covering
    different sets.
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


#: Files in a FUNCTION directory that the deploy does not copy into the package.
#:
#: Deliberately NOT ``_NOT_SHIPPED``, which serves the layer copy lists. That tuple excludes
#: ``__init__.py`` AND ``fakes.py``, and the deploy script prunes NEITHER from a function
#: directory — an ``__init__.py`` is how a package is a package, and a function's ``fakes.py``
#: ships like any other module. Both would therefore go unscanned, and a layer import inside
#: either is exactly as fatal as anywhere else. Two rules because there are genuinely two
#: questions; do not "simplify" this to the other one.
_NOT_PACKAGED = ("test_", "conftest.py")


def _packaged_modules(directory):
    """Every module the deploy actually copies into one function's package.

    **This is deliberately NOT ``_handler_dirs``, and the difference is the whole point.**
    That function answers "which directories are Lambdas", by looking for a module defining a
    top-level ``handler`` — a definition it shares with the instrumentation harness so the two
    cannot drift into covering different fleets. Reusing it to decide *what to scan for imports*
    conflated two questions: only the entry point was ever read, so a layer import in any
    sibling module was invisible, and after the packaging change a layer import anywhere under a
    subpackage was invisible too.

    The set is derived from the rule ``deploy-lambda.sh`` copies by — every ``*.py`` at any
    depth, minus tests, minus ``conftest.py``, minus hidden directories — because the property
    being asserted is "everything in the package can import what it names", and the package is
    what the deploy puts there. A hand-kept list would answer a different question tomorrow.

    Args:
      directory: The function directory.

    Returns:
      The sorted module paths that reach the package.

    Raises:
      None.
    """
    return sorted(
        path
        for path in directory.rglob("*.py")
        if not path.name.startswith(_NOT_PACKAGED)
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    )


def _imported_roots(paths):
    """The top-level package names imported by any of the given modules.

    Walks the whole tree rather than only ``tree.body``: ``post_confirmation.py`` imports
    ``cpcommon`` below its ``logging`` setup, and a lazily-imported layer package inside a
    function body needs the layer attached just as much as a top-level one does.

    Args:
      paths: The modules to read.

    Returns:
      The set of top-level package names they import.

    Raises:
      None.
    """
    roots = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _layer_table():
    """Every layer definition, keyed by its flag."""
    return {entry["flag"]: entry for entry in json.loads(LAYERS.read_text())}


def _copy_list(directory):
    """The module names the layer build copies for ``directory``, as a set."""
    for entry in json.loads(LAYERS.read_text()):
        if entry.get("sourceDir", "").endswith(directory):
            listed = set(entry.get("modules", []))
            assert listed, f"the layer entry for {directory} names no modules"
            return listed
    raise AssertionError(f"no layer entry with a sourceDir for {directory} in {LAYERS.name}")


def _shipped_modules(directory):
    """The production Python modules present in ``lambdas/<directory>/``, as a set."""
    return {
        path.stem
        for path in (LAMBDAS / directory).glob("*.py")
        if not path.name.startswith(_NOT_SHIPPED)
    }


def test_the_handler_sweep_found_the_fleet():
    assert len(HANDLER_DIRS) >= 30, f"only found {len(HANDLER_DIRS)} Lambda directories"


@pytest.mark.parametrize("name", _DIR_IDS)
def test_every_lambda_directory_is_in_the_deploy_matrix(name):
    """A function with code and no matrix row is never deployed at all — the quietest failure
    of the set, because everything about it looks finished.
    """
    assert name in MATRIX, f"lambdas/{name}/ has a handler but no row in {FUNCTIONS.name}"


@pytest.mark.parametrize("name", _DIR_IDS)
def test_every_imported_layer_package_is_attached(name):
    """The signup break, as an assertion.

    An import of a layer package with the matching flag unset is a ``ModuleNotFoundError`` at
    cold start — after a green test run and a green deploy.

    Scanned over EVERY module the deploy ships, not only the entry point. The entry point is
    where the outage happened to be, and scanning only it left the rest of a function's own
    package unguarded against the identical failure — silently, and for a function whose
    modules a reader would assume were covered.
    """
    flags = MATRIX.get(name)
    if flags is None:
        pytest.skip("covered by test_every_lambda_directory_is_in_the_deploy_matrix")

    missing = []
    for root in sorted(_imported_roots(_packaged_modules(LAMBDAS / name))):
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
        f"lambdas/{name}/ imports {', '.join(missing)} but its {FUNCTIONS.name} row does not "
        f"attach the layer — the function will raise ModuleNotFoundError at cold start"
    )


def _shard_bindings():
    """The deploy job's three sharding inputs, as written in the workflow.

    All three now come from the SAME plan job, which is what makes them unable to
    disagree — the earlier design declared the shard list and the divisor independently,
    so ``SHARD_COUNT: 6`` beside ``shard: [0, 1, 2, 3]`` was valid YAML that silently never
    deployed a third of the fleet.
    """
    text = WORKFLOW.read_text()
    found = {}
    for name, pattern in (
        ("shards", r"^\s*shard:\s*(.+?)\s*$"),
        ("count", r"^\s*SHARD_COUNT:\s*(.+?)\s*$"),
        ("planned", r"^\s*PLANNED:\s*(.+?)\s*$"),
    ):
        match = re.search(pattern, text, re.MULTILINE)
        assert match, f"no {name} binding found in {WORKFLOW.name} — did the deploy job change?"
        found[name] = match.group(1)
    return found


def _attach_order():
    """The layer order ``deploy-lambda.sh`` actually attaches in.

    Extracted from the script rather than restated here: the whole point of this pair of
    tests is that the order in the script is the one that reaches AWS, so a copy in the test
    would let the two drift while both looked right.
    """
    match = re.search(r"^for flag in ((?:\w+ ?)+); do$", DEPLOY_SCRIPT.read_text(), re.MULTILINE)
    assert match, "no literal attach-order loop found in deploy-lambda.sh"
    return match.group(1).split()
