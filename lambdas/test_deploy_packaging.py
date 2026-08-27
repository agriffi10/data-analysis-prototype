"""What actually reaches the deployment package, run rather than read.

The build step is four lines of shell and it decides which of a function's modules exist at
runtime. Getting it wrong is invisible everywhere it could be caught: ``conftest.py`` puts the
function directory on ``sys.path`` so every import resolves under pytest, and
``update-function-code`` reports success against a package that cannot import what it needs.
The failure surfaces only as a cold start in production — which is exactly how a Cognito
trigger once broke real signups.

So this extracts the real copy block from ``deploy-lambda.sh`` and RUNS it against a synthetic
function laid out the way a function with subpackages is laid out. Reading the glob and
reasoning about it is what left the previous shape unnoticed: ``cp lambdas/$NAME/*.py`` is
obviously flat once you ask the question, and nothing was asking.

Attributes:
  SCRIPT: The deploy script whose build block is under test.
  FUNCTION_TREE: A function laid out with a subpackage, a nested suite and a nested conftest.
  MUST_SHIP: Paths a correct package contains, relative to the package root.
  MUST_NOT_SHIP: Paths a correct package does not contain, at any depth.
"""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / ".github" / "scripts" / "deploy-lambda.sh"

#: Resolved rather than named, so the shell under test is the one on PATH and ruff can see
#: that the executable is not caller-supplied.
BASH = shutil.which("bash") or "/bin/bash"

FUNCTION_TREE = (
    "handler.py",
    "router.py",
    "conftest.py",
    "test_router.py",
    "apicommon/__init__.py",
    "apicommon/config.py",
    "apicommon/principal.py",
    "routes/__init__.py",
    "routes/whoami.py",
    "routes/test_whoami.py",
)

MUST_SHIP = (
    "handler.py",
    "router.py",
    "apicommon/__init__.py",
    "apicommon/config.py",
    "apicommon/principal.py",
    "routes/__init__.py",
    "routes/whoami.py",
)

MUST_NOT_SHIP = ("conftest.py", "test_router.py", "routes/test_whoami.py")


def _build_block() -> str:
    """Extracts the copy-and-prune block from the deploy script.

    Read out of the script rather than restated, so the test cannot pass against a block the
    script no longer runs — which is the way a copy of shell in a test goes stale.

    Args:
      None.

    Returns:
      The shell between the dependency install and the build stamp.

    Raises:
      AssertionError: If the block's boundaries are no longer recognisable.
    """
    source = SCRIPT.read_text()
    match = re.search(
        r"\n(# Copy the function's modules.*?)\n# SPEC-186 FR-005", source, re.DOTALL
    )
    assert match, "the build block's boundaries moved — this test is reading the wrong shell"
    return match.group(1)


@pytest.fixture
def built(tmp_path: pathlib.Path) -> pathlib.Path:
    """Runs the real build block against a synthetic function and returns the package root."""
    root = tmp_path / "repo"
    (root / "lambdas" / "api").mkdir(parents=True)
    for relative in FUNCTION_TREE:
        module = root / "lambdas" / "api" / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("VALUE = 1\n")

    build_dir = root / "build" / "api"
    build_dir.mkdir(parents=True)

    script = f'set -euo pipefail\nNAME=api\nBUILD_DIR="build/api"\n{_build_block()}\n'
    result = subprocess.run(  # noqa: S603
        [BASH, "-c", script], cwd=root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"the build block failed: {result.stderr}"
    return build_dir


def test_a_functions_subpackages_reach_the_package(built: pathlib.Path) -> None:
    """The failure this file exists for: a package deployed without the modules it imports.

    Args:
      built: The package root the build block produced.

    Returns:
      None.

    Raises:
      AssertionError: If any module a function imports is absent from the package.
    """
    missing = [relative for relative in MUST_SHIP if not (built / relative).exists()]
    assert not missing, (
        f"the package is missing {missing} — these import fine under pytest and the deploy "
        "reports success, so the only symptom is a cold start that cannot import them"
    )


def test_no_test_file_reaches_the_package_at_any_depth(built: pathlib.Path) -> None:
    """A suite in the package makes its test doubles importable at runtime.

    ``conftest.py`` is included deliberately: the prune this replaces matched ``test_*.py``
    only, so every function shipped its conftest.

    Args:
      built: The package root the build block produced.

    Returns:
      None.

    Raises:
      AssertionError: If a test file or conftest survived the prune.
    """
    shipped = [
        str(path.relative_to(built))
        for path in built.rglob("*.py")
        if path.name.startswith("test_") or path.name == "conftest.py"
    ]
    assert not shipped, f"the package ships {shipped}"
    for relative in MUST_NOT_SHIP:
        assert not (built / relative).exists()


def test_the_flat_copy_this_replaces_would_have_failed(tmp_path: pathlib.Path) -> None:
    """Pins WHY the block changed, by running what it replaced.

    Without this the new block looks like an ordinary refactor, and a later reader with a
    tidier idea reverts to the one-line glob. This is what that costs.

    Args:
      tmp_path: Scratch directory.

    Returns:
      None.

    Raises:
      AssertionError: If the old shape would somehow have carried the subpackage.
    """
    root = tmp_path / "old"
    (root / "lambdas" / "api").mkdir(parents=True)
    for relative in FUNCTION_TREE:
        module = root / "lambdas" / "api" / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("VALUE = 1\n")
    build_dir = root / "build" / "api"
    build_dir.mkdir(parents=True)

    subprocess.run(  # noqa: S603
        [BASH, "-c", 'cp lambdas/"${NAME}"/*.py "$BUILD_DIR"/; rm -f "$BUILD_DIR"/test_*.py'],
        cwd=root,
        env={"NAME": "api", "BUILD_DIR": "build/api", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert not (build_dir / "apicommon").exists(), "the old glob would have carried a subpackage"
    assert not (build_dir / "routes").exists()
    assert (build_dir / "conftest.py").exists(), "the old prune matched test_*.py only"


def test_the_block_refuses_rather_than_shipping_a_suite(tmp_path: pathlib.Path) -> None:
    """The guard-the-guard: the prune is checked by the script, not only by this file.

    Args:
      tmp_path: Scratch directory.

    Returns:
      None.

    Raises:
      AssertionError: If a package containing a suite is allowed to deploy.
    """
    root = tmp_path / "sabotage"
    (root / "lambdas" / "api").mkdir(parents=True)
    (root / "lambdas" / "api" / "handler.py").write_text("VALUE = 1\n")
    build_dir = root / "build" / "api"
    build_dir.mkdir(parents=True)

    # A prune that misses is what the refusal exists to catch, so plant what it should catch.
    block = _build_block().replace("! -name 'test_*.py' ", "")
    (root / "lambdas" / "api" / "test_planted.py").write_text("VALUE = 1\n")

    result = subprocess.run(  # noqa: S603
        [BASH, "-c", f'set -uo pipefail\nNAME=api\nBUILD_DIR="build/api"\n{block}\n'],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "a package carrying a suite was allowed to deploy"
    assert "refusing to deploy" in result.stdout + result.stderr


def test_every_shipped_function_still_packages_identically() -> None:
    """The blast radius. This block builds all 82 functions, not just the one that needed it.

    Every function is flat today, so the new block must produce exactly what the old one
    produced for each — minus the conftest that should never have shipped. The subject is the
    deploy table, not every directory under ``lambdas/``: the layer directories are built by
    ``build-layer.sh`` and this block never touches them.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any deployed function's file set changed beyond the conftest.
    """
    lambdas = pathlib.Path(__file__).resolve().parent
    functions = json.loads((lambdas.parent / ".github" / "lambda-functions.json").read_text())
    assert len(functions) > 50, "the deploy table collapsed — this test would prove nothing"

    for entry in functions:
        directory = lambdas / entry["name"]
        old_shape = {
            module.name
            for module in directory.glob("*.py")
            if not module.name.startswith("test_")
        }
        new_shape = {
            str(module.relative_to(directory))
            for module in directory.rglob("*.py")
            if not module.name.startswith("test_")
            and module.name != "conftest.py"
            and not any(part.startswith(".") for part in module.relative_to(directory).parts)
        }
        assert new_shape == old_shape - {"conftest.py"}, (
            f"{entry['name']} packages differently under the new block: "
            f"gained {sorted(new_shape - old_shape)}, "
            f"lost {sorted(old_shape - new_shape - {'conftest.py'})}"
        )
