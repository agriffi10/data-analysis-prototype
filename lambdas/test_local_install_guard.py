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

The coverage gate alone (``--coverage``) also demands Vitest's coverage provider beside ``vitest``
in the root ``node_modules``. Vitest imports it from its own directory, so a lockfile that installs
it inside the workspace instead fails outside another checkout and borrows the parent's copy
inside one. Those cases pin which of the two fixes the refusal names, because the lockfile defect
is reproduced by the ``npm ci`` that repairs a stale install.

Attributes:
    GUARD: Absolute path to the checked script.
    REPO_ROOT: The workspace root, used by the controls that read the real repository.
    REQUIRED: The binaries the guard demands, mirroring its own list.
    GUARDED_GATES: The npm scripts that must carry a guard hook.
    PROVIDER: The coverage provider the coverage gate demands beside ``vitest``.
    ROOT_KEY: The lockfile key that installs PROVIDER beside ``vitest``.
    NESTED_KEY: The lockfile key that installs PROVIDER inside the portal workspace instead.
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
PROVIDER = "@vitest/coverage-v8"
ROOT_KEY = f"node_modules/{PROVIDER}"
NESTED_KEY = f"apps/portal/node_modules/{PROVIDER}"


def _run(root: Path | None, *flags: str) -> subprocess.CompletedProcess[str]:
    """Invoke the guard, optionally against a fixture root.

    Args:
        root: Directory to inspect, or ``None`` to let the guard derive its own default.
        *flags: Further arguments for the guard, such as ``--coverage``.

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
    argv += flags
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


def _lock(root: Path, *keys: str) -> None:
    """Give ``root`` a ``package-lock.json`` whose ``packages`` block holds ``keys``.

    Args:
        root: Directory to write the lockfile into.
        *keys: Lockfile keys to install PROVIDER under, such as ROOT_KEY or NESTED_KEY.

    Returns:
        None.

    Raises:
        None.
    """
    packages = {"": {"name": "fixture"}} | {key: {"version": "5.0.5"} for key in keys}
    (root / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": packages}))


def _provide(root: Path) -> None:
    """Install PROVIDER in ``root``'s own ``node_modules``, beside where ``vitest`` sits.

    Args:
        root: Directory whose ``node_modules`` receives the provider.

    Returns:
        None.

    Raises:
        None.
    """
    provider = root / "node_modules" / PROVIDER
    provider.mkdir(parents=True)
    (provider / "package.json").write_text(json.dumps({"name": PROVIDER, "version": "5.0.5"}))


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


def test_coverage_refuses_a_provider_the_lockfile_installs_inside_a_workspace(
    tmp_path: Path,
) -> None:
    """A provider nested in the portal workspace is refused, naming the lockfile fix.

    This is the layout ``npm ci`` reproduces, so the refusal must not send the reader to it: the
    reason names the nested key, and the remedy names the lockfile repair.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)
    _lock(tmp_path, NESTED_KEY)

    result = _run(tmp_path, "--coverage")

    reason = result.stderr.splitlines()[0]
    assert result.returncode == 1
    assert f"installs {PROVIDER} at {NESTED_KEY}" in reason
    assert "cannot import it" in reason
    assert "npm install --package-lock-only" in result.stderr


@pytest.mark.parametrize(
    ("keys", "empty_dir"),
    [((ROOT_KEY, NESTED_KEY), False), ((ROOT_KEY,), True)],
    ids=["root-key-wins", "empty-provider-dir"],
)
def test_coverage_sends_a_stale_install_to_npm_ci(
    tmp_path: Path, keys: tuple[str, ...], empty_dir: bool
) -> None:
    """A tree lacking a provider the lockfile installs at the root is refused as stale.

    The first lockfile also carries a nested copy, so it pins that a root key wins: a stale tree
    beside a correct lockfile needs ``npm ci``, never a lockfile edit. The second tree has the
    provider's directory with no ``package.json`` in it, which is what an interrupted extraction
    leaves, so a directory-existence check would wave it through.

    Args:
        tmp_path: pytest's per-test directory.
        keys: The lockfile keys installing the provider.
        empty_dir: Whether to leave an empty provider directory in the tree.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)
    _lock(tmp_path, *keys)
    if empty_dir:
        (tmp_path / "node_modules" / PROVIDER).mkdir(parents=True)

    result = _run(tmp_path, "--coverage")

    reason = result.stderr.splitlines()[0]
    assert result.returncode == 1
    assert f"node_modules/{PROVIDER} is missing" in reason
    assert "npm ci" in result.stderr
    assert "--package-lock-only" not in result.stderr


def test_coverage_names_the_manifest_when_the_lockfile_lacks_the_provider(
    tmp_path: Path,
) -> None:
    """A lockfile that does not install the provider at all is refused with the manifest fix.

    Neither ``npm ci`` nor a lockfile move can supply a package the lockfile never names, so the
    refusal must send the reader to the portal's devDependencies instead.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)
    _lock(tmp_path)

    result = _run(tmp_path, "--coverage")

    reason = result.stderr.splitlines()[0]
    assert result.returncode == 1
    assert f"does not install {PROVIDER} at all" in reason
    assert "devDependencies" in result.stderr
    assert "--package-lock-only" not in result.stderr


def test_coverage_is_silent_when_the_provider_sits_beside_vitest(tmp_path: Path) -> None:
    """A tree with the provider at its root passes, even beside a lockfile that nests it.

    The verdict is the installed tree, which is what the gate runs, so a lockfile disagreeing
    with it is no refusal. Silence is the assertion.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)
    _provide(tmp_path)
    _lock(tmp_path, NESTED_KEY)

    result = _run(tmp_path, "--coverage")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_only_the_coverage_gate_checks_the_provider(tmp_path: Path) -> None:
    """Without ``--coverage``, a nested provider is no refusal.

    No other gate imports the provider, so refusing lint, format, test or build over it would
    block runs that work.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        None.

    Raises:
        None.
    """
    _install(tmp_path)
    _lock(tmp_path, NESTED_KEY)

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("flags", [(), ("--coverage",)], ids=["plain", "coverage"])
def test_its_default_root_is_this_workspace(flags: tuple[str, ...]) -> None:
    """With no ``--root``, the guard inspects the workspace and passes.

    Here so that a guard whose path derivation broke cannot pass the fixture cases while refusing
    every real gate run. Like the guard, it reads the installed tree, never the lockfile: a tree
    installed from an older lockfile that nested the provider fails the coverage case until
    ``npm ci``, while one that still has the provider at its root passes whatever the lockfile
    now says. The lockfile itself is held by the next test.

    Args:
        flags: Further arguments for the guard.

    Returns:
        None.

    Raises:
        None.
    """
    assert (REPO_ROOT / "node_modules").is_dir(), (
        "this checkout is not installed, so the control cannot distinguish a broken default root "
        "from a correct refusal -- run `npm ci` and re-run"
    )

    result = _run(None, *flags)

    assert result.returncode == 0, result.stderr


def test_this_lockfile_installs_the_provider_beside_vitest() -> None:
    """This repository's lockfile installs the provider at the root, and nowhere else.

    The guard judges the installed tree, and a checkout installed before a dependency bump keeps
    its old layout, which is how a lockfile nesting the provider went unnoticed in every checkout
    that was not freshly installed. This reads the lockfile itself, so it needs no install and
    fails in every checkout the moment a bump nests the provider again.

    Returns:
        None.

    Raises:
        None.
    """
    packages = json.loads((REPO_ROOT / "package-lock.json").read_text())["packages"]
    placements = [key for key in packages if key == ROOT_KEY or key.endswith(f"/{ROOT_KEY}")]

    assert placements == [ROOT_KEY]
    assert packages["node_modules/vitest"]["version"] == packages[ROOT_KEY]["version"]


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


@pytest.mark.parametrize("gate", GUARDED_GATES)
def test_only_the_coverage_gate_asks_for_the_provider(gate: str) -> None:
    """``--coverage`` is passed by the coverage gate's hook and by no other.

    Dropping it from that hook would switch the provider check off without a sound, and adding it
    elsewhere would refuse gates that never import the provider.

    Args:
        gate: The npm script name whose hook is read.

    Returns:
        None.

    Raises:
        None.
    """
    scripts = json.loads((REPO_ROOT / "apps" / "portal" / "package.json").read_text())["scripts"]

    assert ("--coverage" in scripts[f"pre{gate}"].split()) == (gate == "test:coverage")


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
