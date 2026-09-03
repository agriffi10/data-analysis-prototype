"""Prove the borrowed-dependency-tree guard still fires, and still stays quiet.

``scripts/check-local-install.mjs`` refuses a JS gate run in a checkout that owns no
``node_modules``. It exists because a git worktree created inside another checkout silently
resolves UP into that checkout's dependencies, so eslint, prettier and ``tsc -b`` pass honestly
against a tree that is not the branch's.

Running the guard against this repository proves the repository is installed, not that the guard
works. So every case below builds its own fixture root, and half of them assert the guard is
SILENT -- a guard that refuses everything is as broken as one that refuses nothing, and the
false-positive half is where a gate like this actually gets deleted.

Attributes:
    GUARD: Absolute path to the checked script.
    REPO_ROOT: The workspace root, used only for the one positive control that the default root
        resolves without a ``--root`` argument.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "check-local-install.mjs"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(root: Path | None) -> subprocess.CompletedProcess[str]:
    """Invoke the guard, optionally against a fixture root.

    Args:
        root: Directory to inspect, or ``None`` to let the guard derive its own default.

    Returns:
        The completed process, with stdout and stderr captured as text.

    Raises:
        None.
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


def test_it_refuses_a_partial_install(tmp_path: Path) -> None:
    """A ``node_modules`` with no ``.bin`` is refused as partial rather than accepted.

    An interrupted install leaves the directory present and the binaries absent, which the
    cheaper "does the directory exist" check would wave through.

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
    assert "partial" in result.stderr


def test_it_is_silent_on_an_installed_checkout(tmp_path: Path) -> None:
    """An installed tree passes and prints NOTHING.

    The silence is the assertion. A guard wired into four ``pre`` scripts that chattered on every
    green run would be removed for noise long before it ever caught anything.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    (tmp_path / "node_modules" / ".bin").mkdir(parents=True)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_its_default_root_is_this_workspace() -> None:
    """With no ``--root``, the guard inspects the workspace and passes.

    This is the one case that reads the real repository, and it is here so that a guard whose
    path derivation broke cannot pass the fixture cases while refusing every real gate run.

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


@pytest.mark.parametrize("gate", ["lint", "format:check", "test", "test:coverage"])
def test_every_local_js_gate_is_guarded(gate: str) -> None:
    """Each local JS gate has a ``pre`` script invoking the guard.

    The gate names are written out rather than read back from the manifest: deriving them from
    the same file being checked would make the assertion agree with a deletion.

    Args:
        gate: The npm script name expected to carry a guard.

    Returns:
        None.

    Raises:
        None.
    """
    scripts = json.loads((REPO_ROOT / "apps" / "portal" / "package.json").read_text())["scripts"]

    assert scripts.get(f"pre{gate}") == "node ../../scripts/check-local-install.mjs"


def test_the_build_gate_is_deliberately_unguarded() -> None:
    """``build`` carries no guard, and that is a decision rather than an omission.

    It is the one gate CI still runs, and the SPA image runs the same command after its own
    ``npm ci``, so guarding it would add a failure mode to the delivery path for a state that
    cannot arise there. Pinned so that adding one is a deliberate act with this reasoning in
    front of whoever does it.

    Returns:
        None.

    Raises:
        None.
    """
    scripts = json.loads((REPO_ROOT / "apps" / "portal" / "package.json").read_text())["scripts"]

    assert "prebuild" not in scripts
