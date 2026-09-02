"""Every notify-failure verb must survive its own cold start (SPEC-152 FR-003).

**This is the guard that matters most for these three functions specifically**, and the
reason is circular in a way worth stating plainly: they exist to report the failures no
verb can catch — and a Lambda that dies at IMPORT is the headline member of that class.
A notify-failure verb that cannot import restores the exact silence SPEC-152 was written
to end, on every failure at once, while every other gate stays green.

SPEC-137 is the precedent and every one of its blind spots still applies:

* **pytest cannot see it.** ``lambdas/conftest.py`` puts the shared roots on ``sys.path``
  for every test, so an import that would fail in Lambda succeeds under test, by design.
* **The deploy cannot see it.** ``update-function-code`` succeeds against a function that
  raises ``ModuleNotFoundError`` at cold start; the job goes green.
So this runs a fresh interpreter whose ``sys.path`` is what the deployed function actually
gets: the shared surface plus its own directory, and nothing else.

**WHAT CHANGED, and why the check is narrower than it was.** This used to grant exactly the
layers a function's deploy-table row flagged, and a wrong ROW failed here rather than in
production. There are no rows now, and no per-function layer grants either: one image puts
every shared package on ``/opt/python`` for every function in the fleet. So the failure this
half caught — a function importing a layer its row did not attach — cannot occur, and the
probe no longer claims to catch it. What survives is the half that still can fail and still
matters most: these verbs must import at all, in a minimal environment, with nothing on the
path that a test harness put there.

WHAT IT DOES NOT COVER, stated so nobody reads more into it: these are SOURCE TREES, so a
module present on disk but absent from the built artefact is invisible here. The image's own
behaviour matrix closes that, by importing every handler inside the built image under the
runtime's own bootstrap — which is a stronger answer than this probe ever gave.

THE ENVIRONMENT IS INHERITED, DELIBERATELY, and that is the difference from
``test_layer_import_safety.py``. That test withholds ``cpcommon.config``'s six variables
because its three singletons must import without them. These verbs are the opposite case:
they reach their DOMAIN config through their notifier, whose import-time ``_require`` is
*supposed* to run and which Terraform's common env is *supposed* to satisfy. (``cpcommon``'s
own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what an
import demands from anyone.) Scrubbing here would assert the opposite of the contract. What
is under test is PACKAGING, and ``sys.path`` is the only thing scrubbed.
"""

import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "docker"))
import assemble
import fleet
import pytest

LAYER_ROOT = pathlib.Path(__file__).resolve().parent
LAMBDAS = LAYER_ROOT.parent

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

#: The shared surface the image gives every function, read from the ASSEMBLER. The list this
#: replaces was an eleventh restatement of the layer table; deriving it from a `*-common` glob
#: instead would have been a twelfth, agreeing with the image by naming convention alone.
SHARED_ROOTS = tuple(str(p) for p in assemble.shared_roots(LAMBDAS.parent))

#: boto3 IS STUBBED, and the reason is the same one that makes this probe meaningful.
#:
#: The Lambda RUNTIME provides boto3; no layer does, and nothing in `lambdas/` declares it.
#: `observability.init` runs at module scope and — whenever `LOGS_QUEUE_URL` is set, which it
#: is on every deployed function — eagerly builds an SQSSink through `clients.sqs()`. So a
#: faithful cold start really does touch boto3, and in Lambda it is always there.
#:
#: The probe stubs it anyway, and still does now that the test job installs a real boto3.
#: Stubbing keeps the scope honest: what is under test is whether the LAYERS the matrix row
#: grants satisfy the module's imports — not whether the runner has credentials, a region, or
#: any particular SDK release.
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
def test_a_notify_failure_verb_imports_on_the_image_s_own_search_path(function, module):
    """A cold start, simulated honestly: the shared surface and the function, nothing else."""
    assert function in set(fleet.function_names(LAMBDAS.parent)), (
        f"{function} is not a function Terraform declares. It cannot deploy, and this probe "
        "would otherwise pass by testing nothing."
    )
    assert SHARED_ROOTS, "found no shared roots — this probe would run on the function alone"

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([*SHARED_ROOTS, str(LAMBDAS / function)])
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
        f"{function} cannot import at cold start on the search path the image gives it "
        f"({len(SHARED_ROOTS)} shared roots plus its own directory). This is the failure mode "
        f"where a broken import reaches production behind a green suite and a green deploy, on "
        f"the one function whose whole job is to report failures:\n{result.stderr}"
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
