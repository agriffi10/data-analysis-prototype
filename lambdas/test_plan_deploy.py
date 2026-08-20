"""The deploy planner, driven over the REAL tables.

Deploy Lambdas no longer deploys all 73 functions on every push, and the thing standing
between that and a cold-start outage is `.github/scripts/plan_deploy.py`. A function it
wrongly omits keeps running code compiled against a layer that has moved on, or never
receives the fix that was just merged — and both are invisible until a cold start, which
is exactly how SPEC-137 broke real Cognito signups.

So these tests are written against the shipped tables rather than fixtures wherever the
question is "does this rule hold for the actual fleet", and the omission cases are stated
as their consequence rather than as their mechanism.
"""

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FUNCTIONS = json.loads((ROOT / ".github" / "lambda-functions.json").read_text())
LAYERS = json.loads((ROOT / ".github" / "lambda-layers.json").read_text())

_spec = importlib.util.spec_from_file_location(
    "plan_deploy", ROOT / ".github" / "scripts" / "plan_deploy.py"
)
plan_deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_deploy)

ALL_NAMES = {f["name"] for f in FUNCTIONS}


def plan(changed, force_all=False):
    """The planner over the real tables."""
    return plan_deploy.plan(set(changed), FUNCTIONS, LAYERS, force_all)


def test_a_lone_function_change_deploys_only_that_function():
    """The whole point: the median push touches four directories, not seventy-three."""
    result = plan(["lambdas/log-sweep/log_sweep.py"])
    assert result["functions"] == ["log-sweep"]
    assert result["publish"] == []
    assert result["shard_count"] == 1


def test_a_changed_layer_redeploys_EVERY_function_that_attaches_it():
    """A republished layer is a NEW ARN, and a function pins its layers by ARN.

    Left undeployed, the function keeps pointing at the old version — which is not merely
    stale, it is the defect this whole mechanism exists to avoid: the fix that was just
    merged into the layer is not running, and nothing says so.
    """
    result = plan(["lambdas/file-ops-common/focommon/paths.py"])
    expected = {f["name"] for f in FUNCTIONS if "focommon" in f["layers"]}
    assert expected, "fixture assumption: some function attaches focommon"
    assert set(result["functions"]) == expected
    assert result["publish"] == ["focommon"]


def test_a_cpcommon_change_deploys_the_whole_fleet():
    """Every function attaches cpcommon, so this is the worst case and it must be complete."""
    result = plan(["lambdas/control-plane-common/cpcommon/observability.py"])
    assert set(result["functions"]) == ALL_NAMES
    assert result["publish"] == ["cpcommon"]
    assert result["shard_count"] == 6


def test_a_layer_directorys_TESTS_do_not_republish_the_layer():
    """The saving would be illusory if a test change redeployed the fleet.

    `lambdas/control-plane-common/` holds the cpcommon package and its suite side by side,
    and every one of the 73 functions attaches cpcommon — so watching the directory rather
    than the package would make the common case (editing a test) the most expensive push
    in the repository.
    """
    result = plan(["lambdas/control-plane-common/test_observability.py"])
    assert result["functions"] == []
    assert result["publish"] == []


def test_a_shared_space_module_republishes_only_via_its_listed_modules():
    """The flat-module layer is matched per module, not per directory."""
    listed = plan(["lambdas/shared-space-common/registry.py"])
    assert listed["publish"] == ["layer"]
    assert set(listed["functions"]) == {f["name"] for f in FUNCTIONS if "layer" in f["layers"]}

    unlisted = plan(["lambdas/shared-space-common/test_registry.py"])
    assert unlisted["publish"] == []


@pytest.mark.parametrize("path", plan_deploy.GLOBAL_PATHS)
def test_every_global_path_falls_back_to_the_whole_fleet(path):
    """These change what the plan is computed FROM, so no narrower answer is trustworthy.

    A row's layer set moving, or deploy-lambda.sh changing, can affect any function without
    touching its directory — including this planner itself, whose own bug would otherwise
    be able to suppress the deploy that fixes it.
    """
    result = plan([path])
    assert set(result["functions"]) == ALL_NAMES, f"{path} did not force a full deploy"
    assert set(result["publish"]) == {layer["flag"] for layer in LAYERS}


def test_an_unavailable_diff_deploys_everything():
    """"I do not know what changed" must never be read as "nothing did"."""
    result = plan([], force_all=True)
    assert set(result["functions"]) == ALL_NAMES
    assert set(result["publish"]) == {layer["flag"] for layer in LAYERS}


def test_an_unrelated_change_deploys_nothing():
    """A docs-only push reaching this workflow must not redeploy the fleet."""
    result = plan(["docs/architecture.md", "apps/portal/src/App.tsx"])
    assert result["functions"] == []
    assert result["shards"] == []
    assert result["shard_count"] == 0


def test_a_function_directory_prefix_does_not_match_a_sibling():
    """`lambdas/archive-notify/` must not be matched by a change to `archive-notify-failure`.

    Prefix matching on names that share a prefix is the classic way a planner silently
    deploys the wrong thing — and this fleet is full of such pairs.
    """
    pairs = [
        (a["name"], b["name"])
        for a in FUNCTIONS
        for b in FUNCTIONS
        if a["name"] != b["name"] and b["name"].startswith(a["name"])
    ]
    assert pairs, "fixture assumption: this fleet has prefix-sharing function names"
    for shorter, longer in pairs:
        result = plan([f"lambdas/{longer}/handler.py"])
        assert shorter not in result["functions"], (
            f"a change to {longer} wrongly selected {shorter}"
        )
        assert longer in result["functions"]


def test_every_layer_in_the_table_has_at_least_one_watched_source():
    """A layer with no watched source is never republished, however much it changes.

    It would go stale silently and forever — the deploy would keep resolving it to the
    version last published by a full run.
    """
    unwatched = [
        layer["flag"] for layer in LAYERS if not plan_deploy.layer_sources(layer)
    ]
    assert not unwatched, f"layers nothing would ever republish: {unwatched}"


def test_every_watched_layer_source_exists_on_disk():
    """A watched path that does not exist matches nothing and silently never fires."""
    missing = [
        source
        for layer in LAYERS
        for source in plan_deploy.layer_sources(layer)
        if not (ROOT / source).exists()
    ]
    assert not missing, f"watched layer sources that do not exist: {missing}"


def test_every_function_directory_exists_on_disk():
    """Same failure for the function side of the match."""
    missing = [f["name"] for f in FUNCTIONS if not (ROOT / "lambdas" / f["name"]).is_dir()]
    assert not missing, f"function rows with no directory: {missing}"


def test_the_shard_count_keeps_each_job_over_a_billed_minute():
    """Sharding four functions across six jobs would spend six minutes to save none.

    The count scales with the work, which is the whole reason the matrix is computed rather
    than fixed.
    """
    assert plan(["lambdas/log-sweep/log_sweep.py"])["shard_count"] == 1
    for size, expected in ((1, 1), (12, 1), (13, 2), (24, 2), (25, 3), (73, 6), (500, 6)):
        table = [{"name": f"fn-{i}", "layers": ["cpcommon"]} for i in range(size)]
        result = plan_deploy.plan(set(), table, LAYERS, force_all=True)
        assert result["shard_count"] == expected, f"{size} functions -> {result['shard_count']}"
        assert result["shards"] == list(range(expected))


def test_the_selection_is_always_a_subset_of_the_table():
    """Guards the guard: a planner returning names that are not functions would deploy nothing."""
    for changed in (
        ["lambdas/control-plane-common/cpcommon/config.py"],
        ["lambdas/log-sweep/log_sweep.py"],
        ["lambdas/archive-common/arcommon/keys.py"],
    ):
        assert set(plan(changed)["functions"]) <= ALL_NAMES


FUNCTIONS_TABLE = ".github/lambda-functions.json"
LAYERS_TABLE = ".github/lambda-layers.json"


def test_adding_a_function_deploys_only_the_new_function():
    """Adding a verb is among the commonest pushes here, and it affects one function.

    Before narrowing, editing the table forced all 73 — which made "add a lambda", the
    single most routine change in a spec-driven repo, the most expensive push available.
    """
    added = {"name": "brand-new-verb", "layers": ["cpcommon"]}
    result = plan_deploy.plan(
        {FUNCTIONS_TABLE, "lambdas/brand-new-verb/handler.py"},
        [*FUNCTIONS, added], LAYERS, False, FUNCTIONS, LAYERS,
    )
    assert result["functions"] == ["brand-new-verb"]
    assert result["publish"] == []


def test_changing_a_rows_layer_set_deploys_that_function_only():
    """The SPEC-137 remediation shape: a missing layer flag is added to one row.

    That fix must reach the function — and must not be diluted into a 73-function deploy
    that takes twenty minutes to apply a one-line correction.
    """
    patched = [
        {**f, "layers": ["cpcommon", "focommon"]} if f["name"] == "log-sweep" else f
        for f in FUNCTIONS
    ]
    result = plan_deploy.plan({FUNCTIONS_TABLE}, patched, LAYERS, False, FUNCTIONS, LAYERS)
    assert result["functions"] == ["log-sweep"]


def test_an_unchanged_row_is_not_deployed_when_someone_elses_row_changes():
    """The whole value of diffing the table rather than reacting to the file."""
    patched = [*FUNCTIONS, {"name": "unrelated-new", "layers": ["cpcommon"]}]
    result = plan_deploy.plan({FUNCTIONS_TABLE}, patched, LAYERS, False, FUNCTIONS, LAYERS)
    assert "log-sweep" not in result["functions"]
    assert result["functions"] == ["unrelated-new"]


def test_changing_a_layers_DESCRIPTION_republishes_it():
    """`description` is passed to publish-layer-version, so it is part of what a version is.

    Narrowing to "build inputs only" would leave the published description permanently
    disagreeing with the table, with nothing to reconcile it.
    """
    patched = [
        {**layer, "description": "reworded"} if layer["flag"] == "focommon" else layer
        for layer in LAYERS
    ]
    result = plan_deploy.plan({LAYERS_TABLE}, FUNCTIONS, patched, False, FUNCTIONS, LAYERS)
    assert result["publish"] == ["focommon"]
    assert set(result["functions"]) == {f["name"] for f in FUNCTIONS if "focommon" in f["layers"]}


@pytest.mark.parametrize("table", [FUNCTIONS_TABLE, LAYERS_TABLE])
def test_a_table_change_without_its_previous_content_deploys_everything(table):
    """Force-push, first run, shallow clone: the diff is unavailable and narrowing is a guess.

    This is the branch that makes every narrowing above safe to trust — it is the only way
    the planner is allowed to be wrong, and it is wrong toward deploying too much.
    """
    result = plan_deploy.plan({table}, FUNCTIONS, LAYERS, False, None, None)
    assert set(result["functions"]) == ALL_NAMES
    assert set(result["publish"]) == {layer["flag"] for layer in LAYERS}


def test_a_removed_function_row_deploys_nothing_for_itself():
    """A deleted row means the function is going away; Terraform owns removing it."""
    trimmed = [f for f in FUNCTIONS if f["name"] != "log-sweep"]
    result = plan_deploy.plan({FUNCTIONS_TABLE}, trimmed, LAYERS, False, FUNCTIONS, LAYERS)
    assert result["functions"] == []


def test_a_hard_global_path_still_ignores_the_table_diff():
    """The executor changing is not narrowable, even when the tables are perfectly readable."""
    result = plan_deploy.plan(
        {".github/scripts/deploy-lambda.sh"}, FUNCTIONS, LAYERS, False, FUNCTIONS, LAYERS,
    )
    assert set(result["functions"]) == ALL_NAMES
