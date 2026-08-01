"""``from cpcommon import observability`` must work with NO environment set (SPEC-137 FR-001).

This is the premise the three singleton Lambdas rest on. ``pre-signup``, ``post-confirmation``
and ``notifications-writer`` attach the ``cpcommon`` layer for one import, and that layer's
``config.py`` calls ``_require`` on six variables **at import** — the shape of PR #196, where one
missing variable crashed a whole control plane at cold start. None of the six is set on those
three functions, deliberately, because ``observability`` never reaches ``config``:
``cpcommon/__init__.py`` imports no submodules, and ``clients`` lazy-imports boto3 inside each
accessor.

That makes the invariant **load-bearing rather than incidental**. A single
``from cpcommon import config`` added to ``__init__.py`` — or to ``observability`` — would break
sign-up for every user, at cold start, with nothing in the normal suite failing. So it is pinned
here.

**In a subprocess with a scrubbed environment, and it has to be.** ``lambdas/conftest.py`` stamps
all six variables before collection so the verb suites can import at all, which means an
in-process assertion would pass no matter what ``observability`` imported. The only honest test
is a fresh interpreter that was never given them.
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


def _cpcommon_imports(path):
    """Every ``cpcommon`` submodule name imported by one module, found by AST."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module == "cpcommon":
            names.update(alias.name for alias in node.names)
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
            if not path.name.startswith("test_"):
                yield path


@pytest.mark.parametrize(
    "path", list(_singleton_modules()), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_a_singleton_imports_only_observability_from_cpcommon(path):
    """Adopting ``cpcommon.auth`` or ``cpcommon.config`` here is a separate decision with a
    separate cost — six environment variables on three functions — not something to arrive at by
    autocomplete (SPEC-137's explicit non-goal).
    """
    extra = _cpcommon_imports(path) - {"observability"}
    assert not extra, (
        f"{path.parent.name}/{path.name} imports {sorted(extra)} from cpcommon. Only "
        "`observability` is import-safe without the layer's six required variables — see this "
        "module's docstring before adding the variables instead."
    )


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
