"""Prove the borrowed-dependency-tree guard still fires, and still stays quiet.

``scripts/check-local-install.mjs`` refuses a JS gate run in a checkout that owns no usable
``node_modules``. It exists because a git worktree created inside another checkout silently
resolves UP into that checkout's dependencies, so eslint, prettier and ``tsc -b`` pass honestly
against a tree that is not the branch's.

Running the guard against this repository proves the repository is installed, not that the guard
works. So every case below builds its own fixture root, and several assert the guard is SILENT --
a guard that refuses everything is as broken as one that refuses nothing, and the false-positive
half is where a gate like this gets deleted.

An earlier version of this corpus defined "installed" as an EMPTY ``.bin`` directory, which is
exactly the state that defeated the guard: npm builds a lifecycle script's PATH from every
ancestor's ``node_modules/.bin``, so an empty local one still runs eslint from the parent
checkout and exits 0. The fixture and the guard were wrong in the same direction, which is why
neither caught it. ``_install`` below now populates what the gates actually execute.

Attributes:
    GUARD: Absolute path to the checked script.
    REPO_ROOT: The workspace root, used by the controls that read the real repository.
    REQUIRED: The binaries the guard demands, mirroring its own list.
    GUARDED_GATES: The npm scripts that must carry a guard hook.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "check-local-install.mjs"
REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("eslint", "prettier", "vitest", "tsc")
GUARDED_GATES = ("lint", "format:check", "test", "test:coverage", "build")


def _run(root: Path | None) -> subprocess.CompletedProcess[str]:
    """Invoke the guard, optionally against a fixture root.

    Args:
        root: Directory to inspect, or ``None`` to let the guard derive its own default.

    Returns:
        The completed process, with stdout and stderr captured as text.

    Raises:
        AssertionError: If node is absent, which would make every case below vacuous.
    """
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is not on PATH. This guard protects the JS gates, which cannot run without "
            "node either, so a skip here would hide the same gap it is asserting."
        )
    argv = [node, str(GUARD)]
    if root is not None:
        argv += ["--root", str(root)]
    return subprocess.run(  # noqa: S603
        argv, capture_output=True, text=True, check=False
    )


def _install(root: Path, binaries: tuple[str, ...] = REQUIRED) -> None:
    """Give ``root`` a dependency tree carrying ``binaries``.

    Args:
        root: Directory to populate.
        binaries: Names to create under ``node_modules/.bin``.

    Returns:
        None.

    Raises:
        None.
    """
    binroot = root / "node_modules" / ".bin"
    binroot.mkdir(parents=True, exist_ok=True)
    for name in binaries:
        (binroot / name).touch()


def test_it_refuses_a_checkout_with_no_node_modules(tmp_path: Path) -> None:
    """A worktree that was never installed is refused, and the reason names the cause.

    Args:
        tmp_path: pytest's per-test directory, standing in for a fresh worktree.

    Returns:
        None.

    Raises:
        None.
    """
    result = _run(tmp_path)

    assert result.returncode == 1
    assert "no node_modules" in result.stderr
    assert "npm ci" in result.stderr


def test_it_refuses_a_node_modules_with_no_bin(tmp_path: Path) -> None:
    """``node_modules`` present but with no ``.bin`` is refused as partial.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    (tmp_path / "node_modules").mkdir()

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "has no .bin" in result.stderr


def test_it_refuses_an_empty_bin(tmp_path: Path) -> None:
    """An existing but EMPTY ``.bin`` is refused, naming every binary it cannot supply.

    This is the case a directory-existence check waves through, and the one that actually
    defeated the first version of this guard: npm's PATH walk reaches the parent checkout's
    ``.bin``, so the gate runs and passes against the wrong tree.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path, binaries=())

    result = _run(tmp_path)

    assert result.returncode == 1
    for name in REQUIRED:
        assert name in result.stderr


def test_it_refuses_a_bin_missing_one_binary_and_names_only_that_one(tmp_path: Path) -> None:
    """A tree missing a single binary is refused, and the reason discriminates.

    Asserting merely that "something was refused" would pass on the empty-``.bin`` fixture above,
    so this pins the detail rather than the outcome. The assertion reads the REASON LINE only:
    the remedy printed underneath it names ``eslint`` in a diagnostic command, so a check over
    the whole of stderr cannot tell a one-binary refusal from an everything refusal.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path, binaries=tuple(n for n in REQUIRED if n != "tsc"))

    result = _run(tmp_path)

    reason = result.stderr.splitlines()[0]
    assert result.returncode == 1
    assert "missing tsc" in reason
    assert "eslint" not in reason


def test_it_is_silent_on_an_installed_checkout(tmp_path: Path) -> None:
    """A tree carrying every required binary passes and prints NOTHING.

    The silence is the assertion. A guard wired into five ``pre`` scripts that chattered on every
    green run would be removed for noise long before it caught anything.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_its_default_root_is_this_workspace() -> None:
    """With no ``--root``, the guard inspects the workspace and passes.

    Here so that a guard whose path derivation broke cannot pass the fixture cases while refusing
    every real gate run.

    Returns:
        None.

    Raises:
        None.
    """
    assert (REPO_ROOT / "node_modules").is_dir(), (
        "this checkout is not installed, so the control cannot distinguish a broken default root "
        "from a correct refusal -- run `npm ci` and re-run"
    )

    result = _run(None)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("gate", GUARDED_GATES)
def test_every_js_gate_is_guarded(gate: str) -> None:
    """Each JS gate has a ``pre`` script invoking the guard.

    The gate names are written out rather than read back from the manifest: deriving them from
    the same file being checked would make the assertion agree with a deletion. The invocation is
    matched by SCRIPT NAME rather than by its exact command string, so that changing the path or
    adding a flag is not a failure while removing or repointing the hook still is.

    Args:
        gate: The npm script name expected to carry a guard.

    Returns:
        None.

    Raises:
        None.
    """
    scripts = json.loads((REPO_ROOT / "apps" / "portal" / "package.json").read_text())["scripts"]

    assert "check-local-install" in scripts.get(f"pre{gate}", "")


def test_the_image_build_still_installs_dev_dependencies() -> None:
    """The SPA image's ``npm ci`` must keep installing devDependencies.

    ``build`` carries the guard, and the guard demands eslint, prettier, vitest and tsc -- all
    four of which are devDependencies. The image build runs the same `npm run build`, so adding
    ``--omit=dev`` or ``NODE_ENV=production`` to the Dockerfile would turn a green delivery path
    red at the guard rather than at anything it is trying to protect. Pinned so that change is a
    deliberate act with this consequence in front of whoever makes it.

    Returns:
        None.

    Raises:
        None.
    """
    dockerfile = (REPO_ROOT / "apps" / "portal" / "Dockerfile").read_text()

    assert "npm ci" in dockerfile
    assert "--omit=dev" not in dockerfile
    assert "--production" not in dockerfile
    assert "NODE_ENV=production" not in dockerfile
