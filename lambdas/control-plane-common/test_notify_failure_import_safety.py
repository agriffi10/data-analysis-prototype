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
``test_the_shared_space_layer_publishes_every_module_it_has`` below closes it.

THE ENVIRONMENT IS INHERITED, DELIBERATELY, and that is the difference from
``test_layer_import_safety.py``. That test scrubs the environment because its three
singletons must import ``cpcommon.observability`` with NO variables set. These verbs are
the opposite case: they reach ``cpcommon.config`` through their domain notifier, so the
layer's import-time ``_require`` is *supposed* to run and Terraform's common env is
*supposed* to satisfy it. Scrubbing here would assert the opposite of the contract. What is
under test is PACKAGING, and ``sys.path`` is the only thing scrubbed.
"""

import os
import pathlib
import re
import subprocess
import sys

import pytest

LAYER_ROOT = pathlib.Path(__file__).resolve().parent
LAMBDAS = LAYER_ROOT.parent
WORKFLOW = LAMBDAS.parent / ".github" / "workflows" / "deploy-lambdas.yml"

#: The three functions SPEC-152 added, and the module Lambda loads for each.
NOTIFY_FAILURE_VERBS = {
    "table-builder-notify-failure": "tb_notify_failure",
    "table-share-notify-failure": "ts_notify_failure",
    "shared-space-notify-failure": "ss_notify_failure",
}

#: matrix flag -> the directory the layer publishes its contents FROM. ``layer`` is
#: shared-space-common, which publishes FLAT modules at the layer root rather than a
#: package — which is why the root itself is the path, exactly as /opt/python would be.
LAYER_ROOTS = {
    "cpcommon": LAMBDAS / "control-plane-common",
    "tbcommon": LAMBDAS / "table-builder-common",
    "tscommon": LAMBDAS / "table-share-common",
    "dqcommon": LAMBDAS / "data-quality-common",
    "layer": LAMBDAS / "shared-space-common",
}

_ROW_RE = re.compile(r"^\s*-\s*\{\s*name:\s*([a-z0-9-]+)\s*,(.*)\}\s*$")
_FLAG_RE = re.compile(r"(\w+)\s*:\s*(true|false)")


def _matrix_row(function: str) -> dict:
    """The deploy matrix's flags for one function, read from the workflow as data.

    A regex over the raw file rather than a YAML parse, matching ``test_deploy_matrix.py``:
    PyYAML is not a test dependency and the rows are a fixed one-line shape. A row that
    stops matching yields no flags, which the caller turns into a failure rather than a
    vacuous pass.
    """
    for line in WORKFLOW.read_text().splitlines():
        match = _ROW_RE.match(line)
        if match and match.group(1) == function:
            return {k: v == "true" for k, v in _FLAG_RE.findall(match.group(2))}
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
        f"{function} has no row in {WORKFLOW.name} (or the row was reformatted onto "
        "several lines and no longer matches). It cannot deploy, and this probe would "
        "otherwise pass by testing nothing."
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


#: Files in shared-space-common that are NOT layer content: tests, and the fake AWS clients
#: they use. Everything else is production code the layer must publish.
_NOT_LAYER_CONTENT = ("fakes.py",)


def test_the_shared_space_layer_publishes_every_module_it_has():
    """THE ONE GAP THE PROBE ABOVE CANNOT SEE, and it is specific to this layer.

    Every other layer is copied as a PACKAGE — ``cp -r cpcommon``, ``tbcommon`` — so a new
    module inside one ships by existing. ``shared-space-common`` publishes FLAT modules via
    an explicit ``for m in config casio auth …`` list in the workflow, so a new module ships
    only if someone remembers to name it there.

    The probe above cannot catch a miss, and the docstring must not pretend otherwise: it
    puts the SOURCE TREE on ``sys.path``, where every module is present whether or not the
    layer build copies it. SPEC-152 added ``messages.py`` to this layer; deleting it from
    the workflow list leaves the entire suite green while the deployed layer loses it, and
    ``ss_notify_failure`` — the function whose whole job is reporting import failures —
    raises ``ModuleNotFoundError`` at cold start.

    So this reads the workflow's list as data and joins it against the directory.
    """
    source = LAMBDAS / "shared-space-common"
    on_disk = {
        p.stem
        for p in source.glob("*.py")
        if not p.name.startswith("test_") and p.name not in _NOT_LAYER_CONTENT
    }

    match = re.search(r"for m in ([a-z_ ]+); do", WORKFLOW.read_text())
    assert match, (
        "the shared-space layer's module list is no longer a `for m in …; do` loop in "
        f"{WORKFLOW.name} — this guard cannot read it and would pass vacuously"
    )
    copied = set(match.group(1).split())

    assert on_disk == copied, (
        f"shared-space-common: the layer build copies {sorted(copied)} but the directory "
        f"holds {sorted(on_disk)}. Missing from the workflow: {sorted(on_disk - copied)}; "
        f"named but absent: {sorted(copied - on_disk)}"
    )


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
