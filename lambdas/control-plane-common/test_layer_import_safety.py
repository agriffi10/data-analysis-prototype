"""The singleton Lambdas must import with NO environment set (SPEC-137 FR-001, SPEC-156 FR-004).

This is the premise ``pre-signup``, ``post-confirmation`` and ``notifications-writer`` rest on.
They attach the ``cpcommon`` layer without setting the six variables its ``config.py`` governs —
the shape of PR #196, where one missing variable crashed a whole control plane at cold start.

**SPEC-156 changed how the property is held, and this file changed with it.** It used to be held
by what the three functions were allowed to IMPORT: ``config`` called ``_require`` at import, so
``observability`` was the only safe name and a test asserted no singleton imported anything else.
That allowlist was the reason ``notifications-writer`` carried its own copy of the fleet's JWKS
verifier — the shared one was unimportable. ``config`` now resolves on first access, so the
property is held by what a module TOUCHES rather than by what it names, and the allowlist would
now forbid the very adoption that removed the duplication.

So the assertion is the honest one instead of the proxy: each singleton is imported whole, in a
fresh interpreter with a scrubbed environment. That covers strictly more than the allowlist did —
it would catch an import chain that reaches a required variable at module scope, which a name
check never could — and it is what the acceptance criterion asks for.

**In a subprocess, and it has to be.** ``lambdas/conftest.py`` stamps all six variables before
collection so the verb suites can import at all, which means an in-process assertion would pass
no matter what the module reached. The only honest test is a fresh interpreter that was never
given them.
"""

import ast
import os
import pathlib
import subprocess
import sys

import pytest

LAYER_ROOT = pathlib.Path(__file__).resolve().parent
LAMBDAS = LAYER_ROOT.parent

#: The three functions that attach the layer for `observability` alone (SPEC-137 FR-001).
SINGLETONS = ("pre-signup", "post-confirmation", "notifications-writer")

#: What a scrubbed environment keeps: enough to find the interpreter and its site-packages, and
#: nothing that `cpcommon.config` would accept. PYTHONPATH stands in for the layer's /opt/python.
_SCRUBBED_KEEP = ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH")

_PROBE = """
import json, sys
from cpcommon import observability

observability.init(service="auth")
observability.info("probe emitted")
observability.flush()
print("IMPORT_OK", file=sys.stderr)
"""


def _scrubbed_env():
    env = {k: v for k, v in os.environ.items() if k in _SCRUBBED_KEEP}
    env["PYTHONPATH"] = str(LAYER_ROOT)
    return env


def test_observability_imports_and_emits_with_no_environment_at_all():
    """The whole of SPEC-137 FR-001 in one assertion.

    If this fails with ``required environment variable … is unset``, something in the
    ``cpcommon`` import chain now reaches ``config`` — do not fix it by setting the variable on
    the three functions. Fix the import, or the three lose the property that lets them attach the
    layer at all.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE],
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        "`from cpcommon import observability` failed with an empty environment — the three "
        f"singleton Lambdas cannot attach the layer:\n{result.stderr}"
    )
    assert "IMPORT_OK" in result.stderr
    # Not merely importable: usable. With no LOGS_QUEUE_URL the StdoutSink fallback runs, which
    # is exactly the path a function deployed before its env lands would take.
    assert "probe emitted" in result.stdout + result.stderr, (
        "observability imported but emitted nothing with no environment set"
    )


#: The variables each singleton's OWN Terraform sets that it reads at import — and nothing else.
#: Deliberately minimal: what is under test is that none of ``cpcommon``'s six is needed to
#: import, so anything beyond a function's own eager reads would weaken the probe.
SINGLETON_OWN_ENV = {
    "pre-signup": {},
    "post-confirmation": {"PORTAL_ROLE_ARN": "arn:aws:iam::000000000000:role/probe"},
    "notifications-writer": {},
}

#: boto3 IS STUBBED. ``post_confirmation`` builds its Glue and Lake Formation clients at module
#: scope, and CI's `lambdas` job installs only ruff/pytest — so a real import would pass locally
#: and fail in CI, testing the machine rather than the property. The Lambda runtime always
#: provides boto3; what is under test here is the ENVIRONMENT, not the dependency.
_MODULE_PROBE = """
import importlib, sys, types

boto3 = types.ModuleType("boto3")
boto3.client = lambda *a, **k: types.SimpleNamespace()
boto3.resource = lambda *a, **k: types.SimpleNamespace()
sys.modules["boto3"] = boto3

importlib.import_module(sys.argv[1])
print("IMPORT_OK", file=sys.stderr)
"""


def _singleton_modules():
    for name in SINGLETONS:
        for path in sorted((LAMBDAS / name).glob("*.py")):
            if not path.name.startswith(("test_", "conftest.")):
                yield path


@pytest.mark.parametrize(
    "path", list(_singleton_modules()), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_a_singleton_imports_with_none_of_cpcommon_s_required_variables_set(path):
    """The property SPEC-137 protects, asserted against the real import.

    Not "which names does it import from cpcommon" — that proxy forbade the adoption that
    removed the JWKS duplication, and could never have seen an import chain that reached a
    required variable through a module it did not name. This runs the import.
    """
    function = path.parent.name
    env = {k: v for k, v in os.environ.items() if k in _SCRUBBED_KEEP}
    env["PYTHONPATH"] = os.pathsep.join([str(LAYER_ROOT), str(LAMBDAS / function)])
    env.update(SINGLETON_OWN_ENV[function])

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _MODULE_PROBE, path.stem],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"{function}/{path.name} cannot import without cpcommon's six variables, none of which "
        f"its Terraform sets. This is PR #196 / PR #317's failure mode, and on `pre-signup` it "
        f"is every user's sign-up:\n{result.stderr}"
    )
    assert "IMPORT_OK" in result.stderr


def test_the_probe_environment_really_withholds_the_six():
    """Guards the guard: a probe env that happened to carry them would assert nothing."""
    from cpcommon import config

    granted = set().union(*(set(env) for env in SINGLETON_OWN_ENV.values()))
    assert not granted & set(config._REQUIRED_VARS.values()), (
        f"the probe grants {sorted(granted & set(config._REQUIRED_VARS.values()))}, which is "
        "exactly what it exists to withhold"
    )
    assert set(SINGLETON_OWN_ENV) == set(SINGLETONS)


def test_the_package_init_stays_import_free():
    """``cpcommon/__init__.py`` is what makes the import chain shallow enough to be safe.

    Asserted structurally rather than trusted to the docstring: an ``import`` added here reaches
    every function attaching the layer, including the three with no environment.
    """
    tree = ast.parse((LAYER_ROOT / "cpcommon" / "__init__.py").read_text())
    imports = [
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not imports, (
        f"cpcommon/__init__.py imports {imports} — every function attaching the layer now pays "
        "for it at cold start, including the three that set none of config's six variables"
    )
