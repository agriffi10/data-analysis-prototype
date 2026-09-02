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


def test_an_unavailable_diff_deploys_everything():
    """"I do not know what changed" must never be read as "nothing did"."""
    result = plan([], force_all=True)
    assert set(result["functions"]) == ALL_NAMES
    assert set(result["publish"]) == {layer["flag"] for layer in LAYERS}

