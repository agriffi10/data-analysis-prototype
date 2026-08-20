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

So this test reads the deploy table as data and joins it against what each module actually
imports. It is the only place in the suite where a Lambda's PACKAGING is checked rather than its
behaviour.

The table lives in ``.github/lambda-functions.json`` rather than in the workflow's
``strategy.matrix``, because the per-function jobs are now sharded — see ``_matrix_rows``. That
move added a second way to deploy nothing while reporting success (a shard expression that
selects no functions), which ``test_every_function_lands_in_exactly_one_shard`` closes.
"""

import ast
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
    """Guards the guard: a table that loads empty makes every test below vacuous."""
    assert len(MATRIX) >= 30, f"only read {len(MATRIX)} rows from {FUNCTIONS.name}"
    # A row with a known-good, multi-layer shape, so a partial read fails here rather than
    # passing a function whose flags were silently dropped.
    assert MATRIX.get("data-quality-inspect-source") == {
        "cpcommon": True,
        "dqcommon": True,
        "dqpolars": True,
    }, "the reference row did not read as expected — the table format changed"


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
        f"{LAYERS.name}'s layer copy list and lambdas/{directory}/ disagree — "
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
    listed = {e["flag"] for e in json.loads(LAYERS.read_text()) if e.get("modules")}
    checked = {
        e["flag"]
        for e in json.loads(LAYERS.read_text())
        if any(e.get("sourceDir", "").endswith(d) for d in EXPLICIT_COPY_LISTS)
    }
    assert listed == checked, (
        f"{LAYERS.name} has per-file module lists for {sorted(listed)} but "
        f"{sorted(checked)} are checked — add the new one to EXPLICIT_COPY_LISTS"
    )


def test_every_layer_a_function_attaches_actually_exists():
    """The two tables are joined by flag, and nothing in Actions checks that join.

    A function row naming a flag the layer table does not define deploys with that layer
    silently absent — SPEC-137's failure, arrived at from the other side. The reverse (a layer
    nothing attaches) is harmless but is a minute of build time every run, so it is reported
    too rather than tolerated indefinitely.
    """
    defined = set(_layer_table())
    used = {flag for flags in MATRIX.values() for flag in flags}
    assert not (used - defined), (
        f"functions attach layers that {LAYERS.name} does not define: {sorted(used - defined)} — "
        f"they would deploy with the layer missing and fail at cold start"
    )
    assert not (defined - used), (
        f"{LAYERS.name} builds layers no function attaches: {sorted(defined - used)}"
    )


def test_every_layer_entry_builds_something():
    """A layer entry naming no source publishes an EMPTY layer, which attaches fine.

    The build script refuses at runtime; this is the same refusal offline, where it costs no
    deploy. Each entry must carry at least one of the three shapes.
    """
    empty = [
        e["flag"]
        for e in json.loads(LAYERS.read_text())
        if not (e.get("requirements") or e.get("package") or e.get("modules"))
    ]
    assert not empty, f"layer entries that would build empty: {empty}"


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


def _shard_config():
    """The deploy job's shard list and its ``SHARD_COUNT``, read from the workflow.

    Read rather than duplicated: these two are only correct RELATIVE TO EACH OTHER, and a
    constant here would keep asserting a covering partition after someone changed the workflow.
    """
    text = WORKFLOW.read_text()
    count = re.search(r"^\s*SHARD_COUNT:\s*(\d+)\s*$", text, re.MULTILINE)
    assert count, f"no SHARD_COUNT found in {WORKFLOW.name} — did the deploy job change?"
    listed = re.search(r"^\s*shard:\s*\[([\d,\s]+)\]\s*$", text, re.MULTILINE)
    assert listed, f"no `shard:` matrix list found in {WORKFLOW.name} — did the deploy job change?"
    return [int(s) for s in listed.group(1).split(",")], int(count.group(1))


def test_the_shard_list_and_the_shard_count_agree():
    """The two halves of the sharding are declared separately and must describe one partition.

    ``SHARD_COUNT`` is the divisor in the job's ``select(.key % $n == $s)``; the matrix's
    ``shard:`` list is which remainders actually get a job. Nothing in Actions relates them, so
    ``SHARD_COUNT: 6`` beside ``shard: [0, 1, 2, 3]`` is valid YAML that silently never deploys a
    third of the fleet — green, because every job that ran, succeeded.
    """
    listed, count = _shard_config()
    assert sorted(listed) == list(range(count)), (
        f"shard list {listed} does not cover 0..{count - 1} — functions whose index mod "
        f"{count} is unlisted are never deployed, and the run still goes green"
    )


def test_every_function_lands_in_exactly_one_shard():
    """The sharded deploy must be a COVERING PARTITION of the table.

    Under one job per function this was true by construction. Sharding makes it an expression
    that can be wrong in two directions, both of them quiet: a function in no shard is never
    deployed (the same silent failure ``test_every_lambda_directory_is_in_the_deploy_matrix``
    exists for), and a function in two shards is deployed twice concurrently, which races
    ``update-function-code`` against ``update-function-configuration`` on one function.

    Mirrors the workflow's own ``to_entries[] | select(.key % $n == $s)`` against the shards the
    matrix ACTUALLY lists, so an unlisted remainder shows up here as unplaced functions.
    """
    names = [entry["name"] for entry in json.loads(FUNCTIONS.read_text())]
    listed, count = _shard_config()

    placements = {}
    for shard in listed:
        for index, name in enumerate(names):
            if index % count == shard:
                placements.setdefault(name, []).append(shard)

    unplaced = sorted(set(names) - set(placements))
    assert not unplaced, f"never deployed — in no shard: {unplaced}"
    duplicated = sorted(n for n, shards in placements.items() if len(shards) > 1)
    assert not duplicated, f"deployed concurrently by two shards: {duplicated}"


def test_the_deploy_table_has_no_duplicate_names():
    """Two rows for one function would make the shard partition above unprovable.

    The table is a list, so a duplicated name survives the file but collapses in every dict
    built from it — including ``MATRIX``, which would then check one row and deploy the other.
    """
    names = [entry["name"] for entry in json.loads(FUNCTIONS.read_text())]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    assert not duplicated, f"duplicate rows in {FUNCTIONS.name}: {duplicated}"
