"""Every notify-failure verb must survive its own cold start (SPEC-152 FR-003).

**This is the guard that matters most for these three functions specifically**, and the
reason is circular in a way worth stating plainly: they exist to report the failures no
verb can catch — and a Lambda that dies at IMPORT is the headline member of that class.
A notify-failure verb that cannot import restores the exact silence SPEC-152 was written
to end, on every failure at once, while every other gate stays green.

SPEC-137 is the precedent and every one of its blind spots still applies:

* **pytest cannot see it.** ``lambdas/conftest.py`` puts the layer roots on ``sys.path``
  for every test, so an import that would fail in Lambda succeeds under test, by design.
* **The deploy cannot see it.** ``update-function-code`` succeeds against a function that
  raises ``ModuleNotFoundError`` at cold start; the job goes green.
* **``test_deploy_matrix.py`` sees only half of it.** It joins a function's imports against
  its matrix row — a real check, and the one SPEC-137 needed — but it reasons about NAMES.
  It cannot tell you the named layer actually provides the module, in the layout the layer
  is really built in.

So this runs a fresh interpreter whose ``sys.path`` is EXACTLY what the deploy matrix
grants that function: the layer roots its row flags, plus the function's own directory.
Nothing else. If the ROW is wrong, the subprocess fails here rather than in production nine
days later.

WHAT IT DOES NOT COVER, stated so nobody reads more into it: the layer roots are SOURCE
TREES, so a module present on disk but absent from a layer's BUILD is invisible to this
probe. That gap is real for exactly one layer — ``shared-space-common`` publishes flat
modules from an explicit list rather than copying a package — and
``test_deploy_matrix.test_the_layer_copy_list_matches_the_layer_directory`` closes it.
That assertion lived here briefly (SPEC-152) and moved to the packaging harness in SPEC-153,
which is the file that reads a Lambda's PACKAGING rather than its behaviour; keeping two
copies of one set-equality is the drift this repo's guards exist to prevent.

THE ENVIRONMENT IS INHERITED, DELIBERATELY, and that is the difference from
``test_layer_import_safety.py``. That test withholds ``cpcommon.config``'s six variables
because its three singletons must import without them. These verbs are the opposite case:
they reach their DOMAIN config through their notifier, whose import-time ``_require`` is
*supposed* to run and which Terraform's common env is *supposed* to satisfy. (``cpcommon``'s
own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what an
import demands from anyone.) Scrubbing here would assert the opposite of the contract. What
is under test is PACKAGING, and ``sys.path`` is the only thing scrubbed.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

LAYER_ROOT = pathlib.Path(__file__).resolve().parent
LAMBDAS = LAYER_ROOT.parent
WORKFLOW = LAMBDAS.parent / ".github" / "workflows" / "deploy-lambdas.yml"
#: The deploy table the shard jobs read. It moved out of the workflow's `strategy.matrix`
#: when the per-function jobs were sharded for Actions cost; `test_deploy_matrix.py` reads
#: the same file, and the two must not drift back to different sources.
FUNCTIONS = LAMBDAS.parent / ".github" / "lambda-functions.json"

#: The functions SPEC-152 added, and the module Lambda loads for each. SPEC-164's file-send
#: notifier joins them: a plane's LAST-RESORT notifier failing at import is the one failure
#: nothing else can report, so it is exactly the function whose imports must be provable.
NOTIFY_FAILURE_VERBS = {
    "table-builder-notify-failure": "tb_notify_failure",
    "table-share-notify-failure": "ts_notify_failure",
    "shared-space-notify-failure": "ss_notify_failure",
    "file-send-notify-failure": "fs_notify_failure",
    "archive-notify-failure": "ar_notify_failure",
    "file-ops-notify-failure": "fo_notify_failure",
}

#: matrix flag -> the directory the layer publishes its contents FROM. ``layer`` is
#: shared-space-common, which publishes FLAT modules at the layer root rather than a
#: package — which is why the root itself is the path, exactly as /opt/python would be.
LAYER_ROOTS = {
    "cpcommon": LAMBDAS / "control-plane-common",
    "tbcommon": LAMBDAS / "table-builder-common",
    "tscommon": LAMBDAS / "table-share-common",
    "dqcommon": LAMBDAS / "data-quality-common",
    "focommon": LAMBDAS / "file-ops-common",
    "fscommon": LAMBDAS / "file-send-common",
    "arcommon": LAMBDAS / "archive-common",
    "layer": LAMBDAS / "shared-space-common",
}

def _matrix_row(function: str) -> dict:
    """The deploy table's layer flags for one function, read as data.

    Only true flags are present, so a flag is absent rather than ``False`` — every caller
    reads through ``.get()`` or iterates the granted set, for which the two are the same
    answer. A function missing from the table yields no flags, which the caller turns into
    a failure rather than a vacuous pass.
    """
    for entry in json.loads(FUNCTIONS.read_text()):
        if entry["name"] == function:
            return dict.fromkeys(entry["layers"], True)
    return {}


#: boto3 IS STUBBED, and the reason is the same one that makes this probe meaningful.
#:
#: The Lambda RUNTIME provides boto3; no layer does, and nothing in `lambdas/` declares it.
#: `observability.init` runs at module scope and — whenever `LOGS_QUEUE_URL` is set, which it
#: is on every deployed function — eagerly builds an SQSSink through `clients.sqs()`. So a
#: faithful cold start really does touch boto3, and in Lambda it is always there.
#:
#: CI's `lambdas` job installs only ruff/pytest, so the real import fails there and passed
#: locally purely because a developer machine happens to have boto3 — the probe would have
#: been asserting a property of the laptop. Stubbing keeps the scope honest: what is under
#: test is whether the LAYERS the matrix row grants satisfy the module's imports.
_PROBE = """
import importlib, sys, types

boto3 = types.ModuleType("boto3")
boto3.client = lambda *a, **k: types.SimpleNamespace()
boto3.resource = lambda *a, **k: types.SimpleNamespace()
sys.modules["boto3"] = boto3

module = importlib.import_module(sys.argv[1])
assert callable(module.handler), "handler is not callable"
print("IMPORT_OK", file=sys.stderr)
"""


@pytest.mark.parametrize(
    ("function", "module"), sorted(NOTIFY_FAILURE_VERBS.items()), ids=lambda v: v
)
def test_a_notify_failure_verb_imports_from_only_the_layers_its_row_grants(function, module):
    """A cold start, simulated honestly: only the granted layer roots are importable."""
    flags = _matrix_row(function)
    assert flags, (
        f"{function} has no row in {FUNCTIONS.name}. It cannot deploy, and this probe "
        "would otherwise pass by testing nothing."
    )

    granted = [str(LAYER_ROOTS[flag]) for flag, on in flags.items() if on and flag in LAYER_ROOTS]
    assert granted, f"{function}'s row grants no layer at all"

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([*granted, str(LAMBDAS / function)])
    # LOGS_QUEUE_URL IS FORCED, not inherited, and that is a correctness fix rather than
    # tidiness. `observability.init` runs at module scope and takes the SQSSink branch only
    # when this is set — so leaving it to the ambient environment made the probe exercise a
    # DIFFERENT cold-start path depending on what else had run: green locally (unset, stdout
    # sink) and red in CI (set, SQS sink). Every deployed function has it, so pinning it here
    # tests the fuller path, identically everywhere.
    env["LOGS_QUEUE_URL"] = "https://sqs.us-east-1.amazonaws.com/1/dat-prod-logs.fifo"

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE, module],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"{function} cannot import at cold start from the layers its matrix row grants "
        f"({sorted(f for f, on in flags.items() if on)}). This is the SPEC-137 failure "
        f"mode, on the one function whose whole job is to report it:\n{result.stderr}"
    )
    assert "IMPORT_OK" in result.stderr


def test_the_probe_covers_every_notify_failure_verb_that_exists():
    """Guards the parametrisation against a fourth verb shipping uncovered.

    Discovers them from the FILESYSTEM rather than trusting the table above, so a new
    plane's notify-failure lands in this probe by existing rather than by being remembered.
    """
    found = {p.name for p in LAMBDAS.iterdir() if p.is_dir() and p.name.endswith("-notify-failure")}
    # data-quality's predates SPEC-152 and is covered by its own suite; it is named here so
    # the set comparison stays exact rather than being weakened to a subset check.
    expected = set(NOTIFY_FAILURE_VERBS) | {"data-quality-notify-failure"}
    assert found == expected, f"uncovered: {sorted(found - expected)}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
