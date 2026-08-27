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
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess

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


#: Files in a FUNCTION directory that the deploy does not copy into the package.
#:
#: Deliberately NOT ``_NOT_SHIPPED``, which serves the layer copy lists and excludes
#: ``__init__.py`` — right for a layer publishing flat modules, wrong here: a function laid out
#: as a package ships its ``__init__.py`` and a layer import inside one is exactly as fatal as
#: anywhere else. Two rules because there are genuinely two questions.
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
    # Not merely tidiness, since change detection: the `layers` job is gated on the
    # FUNCTION list being non-empty, so a layer with no attaching function could be marked
    # for republishing and never republished — going stale silently. Deleting this
    # assertion as harmless would open that hole.
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


def test_the_import_scan_reads_more_than_the_entry_point() -> None:
    """The blind spot this scan had, pinned so it cannot come back quietly.

    The scan used to walk only modules defining a top-level ``handler``, because that is how the
    fleet answers "which directories are Lambdas". A layer import in any sibling module was
    therefore invisible, and once a function is laid out as a package, so is every module under
    it — the failure being guarded against is a cold-start ``ModuleNotFoundError`` that no test
    and no deploy can see, which is the outage this whole file exists because of.

    Asserted against a real function rather than a synthetic one, so it stays true as the tree
    changes.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the scan reads only entry points, or misses a subpackage.
    """
    for name, handler_modules in HANDLER_DIRS.items():
        packaged = _packaged_modules(LAMBDAS / name)
        assert set(handler_modules) <= set(packaged), (
            f"{name}: the scan no longer covers its own entry point"
        )

    wider = [
        name
        for name, handler_modules in HANDLER_DIRS.items()
        if len(_packaged_modules(LAMBDAS / name)) > len(handler_modules)
    ]
    assert wider, (
        "no function has a module beyond its entry point, so this assertion proves nothing — "
        "if that is genuinely true of the fleet, this test needs a synthetic subject instead"
    )


def test_the_fleet_assertion_scans_the_PACKAGE_and_not_the_entry_points() -> None:
    """A wiring guard, and it is structural because nothing behavioural can do the job.

    Measured before writing it: **no function in the fleet currently has a non-handler module
    importing a layer its entry point does not**, so the narrow scan and the wide one return
    identical results for all 82. Every behavioural assertion therefore passes either way —
    including the two below, which drive the helper directly — and reverting the fleet
    assertion's subject to ``HANDLER_DIRS`` is invisible.

    That is the whole reason this reads the source instead. The gap it guards is not
    hypothetical: it is the state this file was in until the scan was widened, and the thing
    that made it survive was exactly this equivalence.

    If a function ever does import a layer only from a sibling, replace this with that.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the fleet assertion reads entry points rather than the package.
    """
    tree = ast.parse(pathlib.Path(__file__).read_text())
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_every_imported_layer_package_is_attached"
    )
    called = {
        node.func.id
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    read = {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}

    assert "_packaged_modules" in called, (
        "the fleet assertion no longer scans everything the deploy ships — a layer import "
        "outside the entry point is invisible again, and no other test in this file can see it"
    )
    assert "HANDLER_DIRS" not in read, (
        "the fleet assertion reads the entry-point map; that map answers which directories are "
        "Lambdas, not which modules must be able to import"
    )


def test_a_layer_import_in_a_non_handler_module_is_caught(tmp_path) -> None:
    """The fix, driven end to end: the property, not the plumbing.

    Built as a real directory tree rather than by calling the internals, so it exercises the
    same walk the fleet assertion does — including into a subpackage, which is where the gap
    grew after functions stopped being flat.

    Args:
      tmp_path: Scratch directory.

    Returns:
      None.

    Raises:
      AssertionError: If an import outside the entry point escapes the scan.
    """
    function = tmp_path / "some-function"
    (function / "helpers").mkdir(parents=True)
    (function / "helpers" / ".cache").mkdir()

    (function / "handler.py").write_text("def handler(event, context):\n    return 1\n")
    (function / "router.py").write_text("import tbcommon\n")
    (function / "helpers" / "__init__.py").write_text("")
    (function / "helpers" / "work.py").write_text("from dqcommon import messages\n")
    (function / "test_router.py").write_text("import arcommon\n")
    (function / "conftest.py").write_text("import fscommon\n")
    (function / "helpers" / ".cache" / "stale.py").write_text("import tscommon\n")

    roots = _imported_roots(_packaged_modules(function))

    assert "tbcommon" in roots, "a sibling module's import escaped the scan"
    assert "dqcommon" in roots, "a subpackage module's import escaped the scan"
    assert "arcommon" not in roots, "a test module was scanned — it does not reach the package"
    assert "fscommon" not in roots, "conftest was scanned — it does not reach the package"
    assert "tscommon" not in roots, "a hidden directory was scanned"


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


def test_the_sharding_inputs_all_come_from_the_one_plan():
    """Three values that must describe one partition, so all three have one source.

    If the shard list came from anywhere other than the job that computed the divisor and
    the function list, the three could disagree and the run would still go green — every
    job that ran would have succeeded, having deployed a subset nobody asked for.
    """
    bindings = _shard_bindings()
    assert bindings["shards"] == "${{ fromJSON(needs.plan.outputs.shards) }}"
    assert bindings["count"] == "${{ needs.plan.outputs.shard_count }}"
    assert bindings["planned"] == "${{ needs.plan.outputs.functions }}"


def test_the_shard_filter_selects_from_the_PLAN_not_the_whole_table():
    """Reading the table here would deploy all 73 regardless of what the plan decided."""
    text = WORKFLOW.read_text()
    assert '<<<"$PLANNED"' in text, (
        "the shard filter no longer reads $PLANNED — if it reads the function table "
        "instead, every push deploys the whole fleet and the plan job is decorative"
    )


@pytest.mark.parametrize("size", [1, 4, 12, 13, 25, 73, 200])
def test_the_workflows_own_filter_partitions_the_plan(size):
    """The real jq filter, over the real planner's shard count, for many fleet sizes.

    Re-implementing ``index % count == shard`` in Python made this vacuous: it asserted a
    fact about modular arithmetic rather than about the deploy. Extracting the filter is
    what makes the two failures below reachable — a function in no shard is never deployed,
    and a function in two shards is deployed twice concurrently, racing
    ``update-function-code`` against ``update-function-configuration`` on one function.
    """
    table = [{"name": f"fn-{i}", "layers": ["cpcommon"]} for i in range(size)]
    computed = plan_deploy.plan(set(), table, json.loads(LAYERS.read_text()), force_all=True)
    names = computed["functions"]

    match = re.search(
        r"jq -r --argjson s \"\$SHARD\" --argjson n \"\$SHARD_COUNT\" \\\n\s*'([^']+)'",
        WORKFLOW.read_text(),
    )
    assert match, "could not extract the shard jq filter from the workflow"
    jq = shutil.which("jq")
    assert jq, "jq is not on PATH — the workflow's own shard filter cannot be evaluated"

    placements = {}
    for shard in computed["shards"]:
        out = subprocess.run(  # noqa: S603
            [jq, "-r", "--argjson", "s", str(shard),
             "--argjson", "n", str(computed["shard_count"]), match.group(1)],
            input=json.dumps(names), capture_output=True, text=True, check=True,
        )
        for name in out.stdout.split():
            placements.setdefault(name, []).append(shard)

    assert set(placements) == set(names), (
        f"never deployed: {sorted(set(names) - set(placements))}"
    )
    duplicated = sorted(n for n, s in placements.items() if len(s) > 1)
    assert not duplicated, f"deployed concurrently by two shards: {duplicated}"


def test_the_deploy_table_has_no_duplicate_names():
    """Two rows for one function would make the shard partition above unprovable.

    The table is a list, so a duplicated name survives the file but collapses in every dict
    built from it — including ``MATRIX``, which would then check one row and deploy the other.
    """
    names = [entry["name"] for entry in json.loads(FUNCTIONS.read_text())]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    assert not duplicated, f"duplicate rows in {FUNCTIONS.name}: {duplicated}"


def test_the_deploy_workflow_triggers_on_everything_it_reads():
    """A file the deploy reads but does not trigger on is a change that never deploys.

    The workflow's behaviour moved out of the YAML and into two JSON tables and two shell
    scripts. A merge that only re-points a layer, adds a function, or fixes the deploy script
    touches none of ``lambdas/**`` — so without these in the path filter it reaches main having
    deployed nothing, and the change rides silently on whatever unrelated push comes next.

    This is the trap #320 hit from the other side: the workflow itself was added to the filter
    after an action bump merged completely unexercised.
    """
    text = WORKFLOW.read_text()
    trigger = text[: text.index("jobs:")]

    # Derived from the planner rather than restated, so the two cannot drift: EVERY path
    # that forces a full deploy must also be able to TRIGGER one. A path the planner treats
    # as global but the filter does not name is the worst combination available — the
    # planner would correctly demand a full deploy, on a run that never starts.
    required = ["lambdas/**", *plan_deploy.GLOBAL_PATHS]
    missing = [
        path
        for path in required
        # `lambdas/**` covers anything beneath it, so a global path there needs no entry.
        if path not in trigger and not (path.startswith("lambdas/") and "lambdas/**" in trigger)
    ]
    assert not missing, (
        f"{WORKFLOW.name}'s push path filter does not name {missing} — a change to those "
        f"deploys nothing and goes green"
    )


def _attach_order():
    """The layer order ``deploy-lambda.sh`` actually attaches in.

    Extracted from the script rather than restated here: the whole point of this pair of
    tests is that the order in the script is the one that reaches AWS, so a copy in the test
    would let the two drift while both looked right.
    """
    match = re.search(r"^for flag in ((?:\w+ ?)+); do$", DEPLOY_SCRIPT.read_text(), re.MULTILINE)
    assert match, "no literal attach-order loop found in deploy-lambda.sh"
    return match.group(1).split()


def test_the_attach_order_is_the_layer_table_order():
    """Layer order is load-bearing and was previously asserted only in a comment.

    Layers land on ``/opt`` in the order given and a later one shadows an earlier one's
    modules — and ``cpcommon``, ``polars`` and ``dqpolars`` all pip-install into the same
    ``python/`` root, so a shared transitive dependency at two versions is decided by exactly
    this order.

    Holding the script's literal loop equal to the table's order is what lets the loop be
    rewritten as ``for flag in "${FLAGS[@]}"`` — an obvious-looking simplification, since the
    same script already iterates ``FLAGS`` for the size guard — without silently changing
    which version of a shared dependency wins. Before the function rows were normalised, 17 of
    them stored their layers in the opposite order, so that refactor would NOT have been a
    no-op.
    """
    assert _attach_order() == [entry["flag"] for entry in json.loads(LAYERS.read_text())], (
        "deploy-lambda.sh's attach order and the layer table disagree — one of them changed "
        "without the other, and layer shadowing on /opt follows the script"
    )


def test_every_function_stores_its_layers_in_attach_order():
    """The stored order and the attach order must be the same list.

    They are two independent orderings over the same set, and nothing forces them to agree.
    Keeping them identical is what makes the distinction unable to matter — and makes the
    `FLAGS`-order refactor above provably safe rather than merely currently harmless.
    """
    order = _attach_order()
    wrong = {
        entry["name"]: entry["layers"]
        for entry in json.loads(FUNCTIONS.read_text())
        if entry["layers"] != [flag for flag in order if flag in entry["layers"]]
    }
    assert not wrong, f"stored out of attach order: {wrong}"


def test_no_function_row_has_an_empty_layer_set():
    """Offline mirror of deploy-lambda.sh's runtime refusal.

    Every function in this fleet attaches at least cpcommon. An empty set sends the deploy
    down the bundle-requirements branch AND skips the layer attachment whole, so the function
    ships with no layer and the run goes green — SPEC-137, reached from a malformed table.
    Caught here, it costs nothing; caught at cold start, it broke real signups.
    """
    empty = [e["name"] for e in json.loads(FUNCTIONS.read_text()) if not e["layers"]]
    assert not empty, f"functions with no layers: {empty}"


def test_every_json_written_to_github_output_is_compact():
    """A pretty-printed value breaks ``$GITHUB_OUTPUT``, and it breaks it LATE.

    ``$GITHUB_OUTPUT`` is a ``key=value`` file, so a multi-line value fails the step with
    "Invalid format". jq PRETTY-PRINTS BY DEFAULT, so the bug is an omitted ``-c`` — and it
    surfaced only after all ten layers had already published new versions, because the write
    is the last thing the step does. The deploy job then had no layer map at all.

    Checks the shape rather than one instance: every ``jq`` whose result reaches
    ``$GITHUB_OUTPUT`` must be compact.
    """
    text = WORKFLOW.read_text()

    # Assignments whose value comes from jq and are later written to $GITHUB_OUTPUT.
    written = set(re.findall(r"printf\s+'(\w+)=", text))
    assert written, "no $GITHUB_OUTPUT writes found — did the workflow change?"

    offenders = []
    for name in sorted(written):
        # `printf 'x=%s' "$FOO"` — find what FOO was assigned from, if it was a jq call.
        for match in re.finditer(rf"^\s*{name.upper()}=\$\(.*?\bjq\b(?P<flags>[^']*)'", text,
                                 re.MULTILINE | re.DOTALL):
            if "c" not in match.group("flags").replace("--", ""):
                offenders.append(name)

    # The map is built into MAP and written as `layers=`; check it by name too, since the
    # assignment and the write use different identifiers.
    for var in re.findall(r"^\s*(\w+)=\$\(printf[^\n]*\|\s*jq\s+(-\S+)", text, re.MULTILINE):
        if "c" not in var[1]:
            offenders.append(var[0])

    assert not offenders, (
        f"jq output written to $GITHUB_OUTPUT without -c: {sorted(set(offenders))} — jq "
        f"pretty-prints by default and a multi-line value fails the step with 'Invalid format'"
    )
