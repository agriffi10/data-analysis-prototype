"""The singleton Lambdas must import with NO environment set (SPEC-137 FR-001, SPEC-156 FR-004).

This is the premise ``pre-signup``, ``post-confirmation`` and ``notifications-writer`` rest on.
They attach the ``cpcommon`` layer without setting the four variables its ``config.py`` governs —
the shape of PR #196, where one missing variable crashed a whole control plane at cold start.

**SPEC-156 added a second mechanism; it did not replace the first, and the reason is that
neither covers the other.**

The original guard is an AST scan: no singleton may name anything but ``observability`` from
``cpcommon``. It reads the WHOLE FILE, so it sees a ``from cpcommon import config`` inside a
function body — a read that runs on some later branch, long after the import succeeded.

The second is a subprocess that imports each singleton whole with ``cpcommon``'s four variables
withheld. It sees what the module actually TOUCHES, including a chain that reaches a required
variable through a module it never names — which a name check cannot do.

Each catches what the other misses, and the miss is not hypothetical: a runtime
``config.ADMIN_BUCKET`` added inside a ``pre-signup`` helper imports fine and fails on the branch
that runs it, which on a Cognito trigger is every user's sign-up. So both are here. The AST scan
keeps a per-function allowlist rather than one global list, because SPEC-156 FR-004 made
``notifications-writer`` legitimately import ``auth``, ``clients`` and ``errors`` — its own copy
of the JWKS path existed BECAUSE the shared one was unimportable, and an allowlist that still
forbade it would be preserving the duplication it caused.

**In a subprocess, and it has to be.** ``lambdas/conftest.py`` stamps all four variables before
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

#: boto3 IS STUBBED, and stays stubbed now that the test job installs a real one. The Lambda
#: runtime always provides boto3 and no layer declares it, so what is under test here is the
#: ENVIRONMENT a matrix row grants, not the dependency. A real client inside the probe would
#: also make the result depend on the runner's credentials and region, which is a property of
#: the machine rather than of the layering.
_MODULE_PROBE = """
import importlib, sys, types

boto3 = types.ModuleType("boto3")
boto3.client = lambda *a, **k: types.SimpleNamespace()
boto3.resource = lambda *a, **k: types.SimpleNamespace()
sys.modules["boto3"] = boto3

importlib.import_module(sys.argv[1])
print("IMPORT_OK", file=sys.stderr)
"""


#: What each singleton may name from ``cpcommon``, ANYWHERE in the file — module scope or a
#: function body. ``observability`` for all three; ``notifications-writer`` also reads the
#: trusted actor out of the message, which is a widening that had to be decided rather than
#: arrived at, so it is written here per function rather than globally.
#:
#: ``actor`` replaced ``auth`` when the planes stopped verifying tokens. It is a SAFER member of
#: this list than the one it replaced, and for the reason this list exists: it touches
#: ``cpcommon.config`` only for ``CATALOG_IDENTIFIER_RE``, a module-level constant, and never
#: for one of the four variables these functions do not set — so there is no branch on which it
#: can raise the way a verifier reading ``USER_POOL_ID`` could.
SINGLETON_CPCOMMON_ALLOWLIST = {
    "pre-signup": {"observability"},
    "post-confirmation": {"observability"},
    "notifications-writer": {"observability", "actor", "clients", "errors"},
}


def _cpcommon_imports(path):
    """Every ``cpcommon`` submodule name imported by one module, found by AST.

    By AST over the whole file rather than by importing it: a deferred import inside a function
    body is invisible to the subprocess probe below, and that is precisely the shape that fails
    on a later branch instead of at cold start.

    Args:
      path: The module file to scan.

    Returns:
      The set of ``cpcommon`` submodule names it imports.

    Raises:
      None.
    """
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module == "cpcommon":
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cpcommon."):
            names.add(node.module.split(".", 1)[1])
        elif isinstance(node, ast.Import):
            names.update(
                alias.name.split(".", 1)[1]
                for alias in node.names
                if alias.name.startswith("cpcommon.")
            )
    return names


def _singleton_modules():
    for name in SINGLETONS:
        for path in sorted((LAMBDAS / name).glob("*.py")):
            if not path.name.startswith(("test_", "conftest.")):
                yield path


@pytest.mark.parametrize(
    "path", list(_singleton_modules()), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_a_singleton_names_only_what_its_allowlist_grants(path):
    """The half the subprocess probe cannot see: a cpcommon import in a function body.

    Such an import succeeds at cold start and fails when its branch runs — on ``pre-signup``
    that is every user's sign-up, with a green deploy and a green suite. Widening a function's
    entry here is a decision with a cost; make it deliberately, and check what the variables it
    reaches are set to in that function's Terraform before you do.
    """
    function = path.parent.name
    extra = _cpcommon_imports(path) - SINGLETON_CPCOMMON_ALLOWLIST[function]
    assert not extra, (
        f"{function}/{path.name} imports {sorted(extra)} from cpcommon, which its allowlist does "
        f"not grant. These functions set none of cpcommon.config's four variables, so a module "
        f"that reads one — at import OR on any later branch — fails there."
    )


@pytest.mark.parametrize(
    "path", list(_singleton_modules()), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_a_singleton_imports_with_none_of_cpcommon_s_required_variables_set(path):
    """The property SPEC-137 protects, asserted against the real import.

    The other half of the pair above. A name check cannot see an import chain that reaches a
    required variable through a module it never names; running the import can. It cannot see a
    deferred import, which is why the name check stays.
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
        f"{function}/{path.name} cannot import without cpcommon's four variables, none of which "
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
    assert set(SINGLETON_CPCOMMON_ALLOWLIST) == set(SINGLETONS)


def test_the_ast_scan_sees_a_deferred_import():
    """Guards the guard the OTHER way: the name check exists for the function-body case.

    Asserted on a synthetic module rather than on a real one, because the property under test is
    the scanner's reach, and the real files must not carry the thing being detected.
    """
    source = "def later():\n    from cpcommon import config\n\n    return config.ADMIN_BUCKET\n"
    module = LAYER_ROOT / "_deferred_import_probe.py"
    module.write_text(source)
    try:
        assert _cpcommon_imports(module) == {"config"}
    finally:
        module.unlink()


def test_the_package_init_stays_import_free():
    """``cpcommon/__init__.py`` is what makes the import chain shallow enough to be safe.

    Asserted structurally rather than trusted to the docstring: an ``import`` added here reaches
    every function attaching the layer, including the three that set almost none of its
    environment.
    """
    tree = ast.parse((LAYER_ROOT / "cpcommon" / "__init__.py").read_text())
    imports = [
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not imports, (
        f"cpcommon/__init__.py imports {imports} — every function attaching the layer now pays "
        "for it at cold start, whether or not it uses the module"
    )
