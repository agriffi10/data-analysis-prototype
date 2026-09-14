"""Two workflow guards whose failure would be SILENT rather than red.

Both hold a condition that was structural until it became textual, which is the point at
which a guard starts needing one of its own.

``ci.yml``'s ``ci`` job skips its lint, build and test steps when a pull request touches none
of the app's inputs. That set is not "the app's source": the suite reads scores of files from
OUTSIDE ``apps/portal/`` through ``?raw`` and ``import.meta.glob`` — every IAM policy template
among them, reached by one glob — in order to assert that the browser agrees with the infrastructure
and the planes. A read missing from the workflow's pattern list does not make the saving
smaller, it makes it dishonest: the coupled file changes, the guard that would have caught it
never runs, and the job is green. The first test sweeps for those reads rather than restating
them, so a new import cannot be added without the workflow learning about it.

``security.yml``'s scanners were ordered after gate validation by ``needs: gates`` while it was
a separate job. It is now a step, and the ordering is a string repeated on every scanner step.
YAML enforced the old form; nothing enforces the new one, so a scanner added without the
condition would run under a failed gate and report as if the gate had held.

The sweep covers every ``.ts``/``.tsx``/``.mts``/``.cts`` under ``apps/portal``, not only
``src/**/*.test.ts``. A coupled read moved one file sideways into a ``src/test/`` helper is the
shape this repository already uses — ``cssTokens.ts`` reads from disk — and a test-file-only
sweep is blind to it while looking exactly as green.

One shape it still cannot see: a BRACE glob, ``…/*.{tf,tftpl}``. Half the suite's
``import.meta.glob`` calls use braces, all of them in-tree today, and covering them needs
brace expansion before the glob rather than a wider character class. A coupled read written
that way would be missed, so write it as two globs or add the expansion.

Specifiers are RESOLVED against the file holding them, never string-stripped. Dropping the
``../`` prefixes and testing the remainder at the repository root reads ``../../package.json``
from ``src/lib/`` as the ROOT manifest when it is the portal's own, and turns a ``./*`` inside
a comment into a glob of the whole repository — which then demands scope patterns for
``README.md`` and for untracked files CI does not even have.

The shape is ``test_security_gates.py``'s: assert the coupling, then assert the parse did not
go trivial. A sweep that finds nothing must fail rather than pass vacuously — and a floor alone
is a weak control here, because all but four of the reads arrive through a single glob and mask the
disappearance of any individual one. The five that do not come from that glob are named.
"""

import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import test_config_workflows as _path_filter_guard
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
PORTAL = ROOT / "apps" / "portal"
PORTAL_SRC = PORTAL / "src"

#: A quoted specifier that is path-shaped — it starts with ``.`` or ``/`` and holds a separator.
#: Deliberately NOT filtered by extension: the reads this exists to find are whatever the suite
#: reaches for, and an allowlist is a second place to forget one. A trailing Vite query
#: (``?raw``) is stripped; ``*`` is expanded after resolution, never before.
PATH_SPECIFIER = re.compile(
    r"""['"]([./][A-Za-z0-9_.*/-]*/[A-Za-z0-9_.*/-]+?)(\?[a-z]+)?['"]"""
)

#: The condition every scanner step in ``scan`` must carry now that gate validation is a step.
GATE_CONDITION = "always() && steps.gates.outcome == 'success'"

#: Steps in ``scan`` deliberately NOT gated: the checkout that fetches the script, the
#: validation itself, its summary, and the toolchain setup. None is a scanner, and each runs
#: under the default ``success()`` — which a failed validation already skips.
UNGATED_SCAN_STEPS = frozenset(
    {
        "Checkout",
        "Validate every gate value",
        "Record the gate configuration in the summary",
        "Set up Python",
        "Set up Node.js",
    }
)

#: Every out-of-tree read that does NOT arrive through the IAM-template glob, named rather than
#: counted. A floor cannot protect these: the overwhelming majority of reads come from that one
#: glob, so any of the entries below could stop being swept while the total still cleared any
#: plausible threshold.
NAMED_OUT_OF_TREE_READS = frozenset(
    {
        "config/feature-flags.json",
        "infra/main.tf",
        "lambdas/api/routes/feature_flags.py",
        "lambdas/archive-common/arcommon/config.py",
        "lambdas/control-plane-common/cpcommon/app_managed.py",
    }
)

#: One repository path per ``SCOPE_PATTERNS`` entry that the list MUST select. The sweep above
#: derives only the out-of-tree half; nothing derived the build half, so deleting ``^apps/portal/``
#: passed green while every pull request touching app source skipped lint, build and the suite.
SELECTED_BY_SCOPE = (
    "apps/portal/src/App.tsx",
    "packages/shared/index.ts",
    "package.json",
    "package-lock.json",
    ".nvmrc",
    ".github/workflows/ci.yml",
    "config/feature-flags.json",
    "infra/main.tf",
    "infra/modules/data/policies/portal-role-permissions.json.tftpl",
    "lambdas/api/routes/feature_flags.py",
    "lambdas/archive-common/arcommon/config.py",
    "lambdas/control-plane-common/cpcommon/app_managed.py",
)

#: Paths the list must NOT select, or the saving is gone. Each is a near miss of a real pattern
#: rather than an obvious non-match, so an over-broad or unanchored pattern is caught.
REFUSED_BY_SCOPE = (
    "docs/process/INDEX.md",
    "CLAUDE.md",
    "lambdas/api/routes/objects.py",
    "lambdas/archive-common/arcommon/registry.py",
    "infra/modules/data/main.tf",
    "infra/variables.tf",
)

#: Git settings the harnesses below must not inherit from whoever is running the suite.
#: ``GIT_DIR`` and its neighbours point git at a DIFFERENT repository, and the fixture commits
#: then land there — measured: a decoy repo came back with its HEAD moved onto a fixture commit
#: and its original orphaned, while the suite passed. ``GIT_CONFIG_GLOBAL`` matters for a second
#: reason: ``core.quotePath=false`` in a developer's own config un-quotes the high-byte fixture,
#: which would let the quoting guard below pass against a workflow that has no ``-z``. Pointing
#: the two config FILES at ``os.devnull`` is not enough on its own: ``GIT_CONFIG_COUNT`` with its
#: ``GIT_CONFIG_KEY_n``/``VALUE_n`` pairs, and ``GIT_CONFIG_PARAMETERS``, inject the same setting
#: without a file. The numbered pairs are dropped alongside the count that activates them.
HERMETIC_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_COUNT": None,
    "GIT_CONFIG_PARAMETERS": None,
    "GIT_DIR": None,
    "GIT_WORK_TREE": None,
    "GIT_INDEX_FILE": None,
    "GIT_OBJECT_DIRECTORY": None,
    "GIT_ALTERNATE_OBJECT_DIRECTORIES": None,
    "GIT_COMMON_DIR": None,
    "GIT_CEILING_DIRECTORIES": None,
}


def _hermetic_env(**overrides: str) -> dict[str, str]:
    """Return an environment that cannot reach the caller's repository or git configuration.

    Args:
        **overrides: Variables to set on top of the scrubbed environment.

    Returns:
        dict[str, str]: The caller's environment with every entry of ``HERMETIC_GIT_ENV`` either
            replaced or removed, plus the overrides.

    Raises:
        None.
    """
    environment = dict(os.environ)
    for name, value in HERMETIC_GIT_ENV.items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    for name in [key for key in environment if key.startswith("GIT_CONFIG_")]:
        if name not in HERMETIC_GIT_ENV:
            environment.pop(name, None)
    environment.update(overrides)
    return environment


#: The floor for the glob-derived half. A LOWER BOUND deliberately, not the count: templates are
#: added and removed by ordinary infrastructure work, and a guard pinned to today's number would
#: redden on a correct change. An exact count written into prose goes stale with nothing to catch
#: it — this repository carried "88" against a real 87 for long enough to be copied four times —
#: so the number lives here, where a test reads it, and nowhere else.
MINIMUM_IAM_TEMPLATE_READS = 80


def _scope_patterns() -> list[str]:
    """Read the ``ci`` job's scope pattern list out of the workflow.

    Taken from the step's ``env`` rather than from its shell body, so this reads the same string
    the step hands to ``grep -f`` instead of a copy that can drift from it. Split on lines, not
    on whitespace: ``grep -f`` reads one pattern per LINE, and splitting on whitespace would
    hide both a blank line and a pattern containing a space.

    Args:
        None.

    Returns:
        One pattern per line of the block scalar, in workflow order, with blanks preserved.

    Raises:
        AssertionError: If the workflow holds no step with ``id: scope``.
    """
    document = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step for step in document["jobs"]["ci"]["steps"] if step.get("id") == "scope"
    ]
    assert steps, (
        "ci.yml no longer has a step with `id: scope` — the scoping guard reads that step"
    )
    return steps[0]["env"]["SCOPE_PATTERNS"].splitlines()


def _portal_sources() -> list[pathlib.Path]:
    """Every portal source a coupled read can hide in.

    Walks the whole of ``apps/portal`` rather than ``src/`` alone, and the four suffixes
    vitest's default include accepts, because a read moved into a helper or a config file is
    still a read — and a sweep scoped to ``src/**/*.test.ts`` was blind to exactly that.

    Args:
        None.

    Returns:
        Every ``.ts``/``.tsx``/``.mts``/``.cts`` file under the portal, build output excluded.

    Raises:
        None.
    """
    skip = {"node_modules", "dist", "coverage", "htmlcov"}
    return [
        path
        for suffix in ("*.ts", "*.tsx", "*.mts", "*.cts")
        for path in PORTAL.rglob(suffix)
        if not skip & set(path.relative_to(PORTAL).parts)
    ]


def _out_of_tree_reads() -> set[str]:
    """Sweep the portal's sources for files they read from outside ``apps/portal/``.

    A specifier beginning with ``/`` is root-anchored and resolves against ``apps/portal``; one
    beginning with ``.`` resolves against the directory of the file holding it. Both are then
    normalised, and anything landing inside the portal or outside the repository is dropped —
    which is what keeps in-tree imports and comment fragments out of the result.

    Args:
        None.

    Returns:
        Repository-relative POSIX paths read from outside ``apps/portal/``.

    Raises:
        None.
    """
    found: set[str] = set()
    for source in _portal_sources():
        for specifier, _query in PATH_SPECIFIER.findall(
            source.read_text(encoding="utf-8")
        ):
            base = PORTAL if specifier.startswith("/") else source.parent
            resolved = pathlib.Path(os.path.normpath(base / specifier.lstrip("/")))
            try:
                relative = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                continue
            matches = sorted(ROOT.glob(relative)) if "*" in relative else [resolved]
            for match in matches:
                if match.is_file() and PORTAL not in match.parents:
                    found.add(match.relative_to(ROOT).as_posix())
    return found


def _grep_selection(paths: tuple[str, ...]) -> set[str]:
    """Run the workflow's pattern list against ``paths`` using the engine CI uses.

    GNU ``grep -E`` rather than Python ``re``: they are not the same language, and validating
    with the wrong one let a plant claim coverage of a named read while grep silently disagreed.
    A warning on stderr is treated as failure — grep reports an unsupported construct that way
    and still exits 0, having matched nothing.

    Args:
        paths: Repository-relative paths to offer the pattern list, one per line.

    Returns:
        The subset of ``paths`` the list selects.

    Raises:
        AssertionError: If grep is absent, errors, or writes any diagnostic about the list.
    """
    grep = shutil.which("grep")
    assert grep, (
        "no grep on PATH; this test validates the pattern list with the engine CI uses"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".grep", delete=False) as handle:
        handle.write("\n".join(_scope_patterns()) + "\n")
        pattern_file = handle.name
    try:
        result = subprocess.run(  # noqa: S603
            [grep, "-E", "-f", pattern_file],
            input="\n".join(paths) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        os.unlink(pattern_file)

    assert result.returncode in (0, 1), (
        f"grep rejected ci.yml's pattern list: {result.stderr.strip()}"
    )
    assert not result.stderr.strip(), (
        "grep reported a problem with ci.yml's pattern list, which means it matched less than it "
        f"appears to — a Python-only construct such as `(?:` reaches CI as a broken pattern: {result.stderr.strip()}"
    )
    return set(result.stdout.split())


def test_every_file_the_suite_reads_from_outside_the_portal_is_in_ci_scope():
    """A coupled file outside ``apps/portal/`` must re-run the suite that asserts the coupling.

    The failure this holds off is silent: the file changes, the set-equality assertion that
    would have caught it is skipped, and the job reports green. Two were reproduced by planting
    — ``arcommon/config.py`` and ``infra/main.tf`` — before the pattern list covered them.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the sweep loses a named read or the IAM glob, or if a swept path
            matches no scope pattern.
    """
    reads = _out_of_tree_reads()

    lost = sorted(NAMED_OUT_OF_TREE_READS - reads)
    assert not lost, (
        f"the sweep no longer finds these known out-of-tree reads: {lost}. Either the read moved "
        "to a file shape the sweep does not cover, or the specifier regex stopped matching — "
        "both leave this test passing while covering nothing"
    )

    templates = {path for path in reads if path.startswith("infra/modules/")}
    assert len(templates) >= MINIMUM_IAM_TEMPLATE_READS, (
        f"the sweep found only {len(templates)} IAM policy templates against a floor of "
        f"{MINIMUM_IAM_TEMPLATE_READS}; the glob "
        "in policyTemplates.guard.test.ts reaches all of them, so the glob has stopped resolving"
    )

    patterns = [re.compile(pattern) for pattern in _scope_patterns() if pattern.strip()]
    uncovered = sorted(
        path for path in reads if not any(pattern.search(path) for pattern in patterns)
    )

    assert not uncovered, (
        "the portal suite reads these files from outside apps/portal, and ci.yml's SCOPE_PATTERNS "
        f"does not cover them, so a pull request changing one skips the suite and reports green: {uncovered}"
    )


def test_the_pattern_list_selects_every_build_input_and_refuses_the_rest():
    """The half of ``SCOPE_PATTERNS`` no sweep derives, checked with the engine CI runs.

    Deleting ``^apps/portal/`` is the worst single edit possible here — every pull request
    touching app source would skip lint, format, build and the whole suite and report green —
    and nothing caught it, because the coverage test above only asserts the paths its own sweep
    found. This names one path per pattern instead.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a build input is not selected, or a near miss is.
    """
    selected = _grep_selection(SELECTED_BY_SCOPE + REFUSED_BY_SCOPE)

    missed = [path for path in SELECTED_BY_SCOPE if path not in selected]
    assert not missed, (
        "ci.yml's SCOPE_PATTERNS no longer selects these inputs, so a pull request changing one "
        f"would skip the build and the suite and report green: {missed}"
    )

    over = [path for path in REFUSED_BY_SCOPE if path in selected]
    assert not over, (
        f"these patterns select paths the app does not read, so the saving is gone: {over}"
    )


def _assert_pattern_list_is_sane(patterns: list[str], label: str) -> None:
    """Assert a `grep -f` pattern list means what it looks like.

    Args:
        patterns: One extended regular expression per entry.
        label: The list's name, for the failure message.

    Returns:
        None.

    Raises:
        AssertionError: If the list is empty, or a pattern is blank, carries whitespace, or uses
            a construct POSIX ERE does not have.
    """
    assert patterns, (
        f"{label} is empty; the step it feeds would answer the same for every commit"
    )

    blank = [index for index, pattern in enumerate(patterns) if not pattern.strip()]
    assert not blank, (
        f"{label} has a blank line at index {blank}; `grep -f` reads it as a "
        "match-everything pattern and the scoping stops scoping"
    )

    whitespaced = [
        pattern
        for pattern in patterns
        if any(char.isspace() for char in pattern.strip())
    ]
    assert not whitespaced, (
        "these patterns carry whitespace and do not mean what they look like — a trailing tab "
        f"survives YAML and makes the pattern match nothing: {whitespaced!r}"
    )

    # Asserted textually rather than by running grep, because the two greps disagree: BSD accepts
    # `(?:` and matches, GNU warns and matches nothing, so a check that shells out passes on a
    # developer's Mac and fails on the runner — or worse, the reverse.
    pcre = [pattern for pattern in patterns if "(?" in pattern]
    assert not pcre, (
        "POSIX ERE has no non-capturing or lookaround group, and `grep -E` on the runner matches "
        f"NOTHING for a pattern using one — silently, in the cheap direction: {pcre}"
    )


def test_no_scope_pattern_matches_every_path():
    """``grep -f`` reads a blank line as a pattern matching everything.

    One stray empty line in the block scalar makes the scope step answer ``app=true`` for every
    pull request — the whole saving gone, silently and in the expensive direction, with the
    coverage tests still green because a blank pattern covers all of their paths.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a pattern is blank, carries whitespace, or uses a construct POSIX
            ERE does not have.
    """
    _assert_pattern_list_is_sane(_scope_patterns(), "SCOPE_PATTERNS")


def _seed_repo(repo: pathlib.Path) -> tuple[list[str], str]:
    """Initialise a throwaway repository holding one commit, and return the way back into it.

    Both scope steps below diff against a commit they are handed, so both need a repository
    with a baseline. Shared rather than written twice because the two copies drifted apart in
    exactly one place — the message that says which step could not find a shell — and a message
    naming the wrong step is worse than no message.

    Every git invocation takes the scrubbed environment. Inheriting ``GIT_DIR`` from whoever ran
    the suite does not merely break hermeticity: the fixture commits land in THAT repository.

    Args:
        repo: An existing empty directory to initialise.

    Returns:
        tuple[list[str], str]: The ``git`` argv prefix that operates on it, and the seed
            commit's sha.

    Raises:
        subprocess.CalledProcessError: If any of the git commands fails.
    """
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
    environment = _hermetic_env()
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, env=environment)  # noqa: S603
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, env=environment)  # noqa: S603
    subprocess.run([*git, "commit", "-qm", "baseline"], check=True, env=environment)  # noqa: S603
    head = subprocess.run(  # noqa: S603
        [*git, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()
    return git, head


def _locate_bash(label: str) -> str:
    """Find the shell a scope step is written in, naming the step that needs it.

    Args:
        label: The workflow whose step is about to be run, for the refusal message.

    Returns:
        str: An absolute path to ``bash``.

    Raises:
        AssertionError: If there is no ``bash`` on PATH.
    """
    bash = shutil.which("bash")
    assert bash, (
        f"no bash on PATH; {label}'s scope step is a bash script and cannot be exercised "
        "without one"
    )
    return bash


def _read_github_output(path: pathlib.Path) -> dict[str, str]:
    """Parse a step's ``$GITHUB_OUTPUT`` file into the answers it wrote.

    Args:
        path: The file the step was handed as ``GITHUB_OUTPUT``.

    Returns:
        dict[str, str]: One entry per ``key=value`` line, later lines winning.

    Raises:
        None.
    """
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def _ci_scope_step() -> dict:
    """Return the ``ci`` job's scope step, by id rather than by position.

    Args:
        None.

    Returns:
        dict: The step mapping, including its ``run`` script and its ``env`` block.

    Raises:
        AssertionError: If no step carries the id, which means the tests below are asserting
            about a step that no longer exists.
    """
    document = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step for step in document["jobs"]["ci"]["steps"] if step.get("id") == "scope"
    ]
    assert steps, (
        "ci.yml no longer has a step with `id: scope` — the execution guards read that step"
    )
    return steps[0]


def _assert_the_hazard_is_present(
    git: list[str],
    environment: dict[str, str],
    changed: tuple[str, ...],
    base: str | None = None,
) -> None:
    """Prove the fixture still provokes the quoting the step is guarded against.

    The verdict tests below police what the step ANSWERS; nothing polices whether the hazard
    arose at all. A fixture that stopped being quoted — a git that changed its default, an
    environment that un-quotes it — would let the quoting guard pass against a workflow with no
    ``-z`` at all, and read exactly like a fix that works. So the control is over the INPUT:
    for any fixture path that is not plain ASCII, the un-``-z``'d diff must still C-quote it.

    Args:
        git: The ``git`` argv prefix for the fixture repository.
        environment: The scrubbed environment those commands run under.
        changed: The paths the head commit touched.
        base: The commit to diff from. Defaults to the environment's ``BASE``, which is what the
            pull-request step is handed; the deploy step is handed a tag instead.

    Returns:
        None.

    Raises:
        AssertionError: If a non-ASCII fixture path is not quoted by a plain ``--name-only``,
            which makes the guard over it vacuous.
    """
    hazardous = [name for name in changed if not name.isascii()]
    if not hazardous:
        return
    plain = subprocess.run(  # noqa: S603
        [*git, "diff", "--name-only", "--no-renames", base or environment["BASE"], "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout
    for name in hazardous:
        assert name not in plain, (
            f"[{name}] came back from a plain `--name-only` unquoted, so this fixture no longer "
            "provokes the quoting the step is guarded against and the guard over it is vacuous"
        )


def _run_ci_scope(
    changed: tuple[str, ...],
    *,
    renamed: tuple[tuple[str, str], ...] = (),
    patterns: str | None = None,
    break_diff: bool = False,
    expect_failure: bool = False,
) -> dict[str, str]:
    """Run the pull-request scope step's real script over a throwaway repository.

    The static tests above ask what the pattern list means; this asks what the STEP answers,
    which is a different question. Everything between the two — how ``git diff`` spells a path,
    how the here-string reaches ``grep`` — lives only in the shell body, and the failures it
    hides are silent: a green ``ci`` check that installed nothing, built nothing and ran no
    suite looks exactly like one that did.

    The script is taken from the workflow rather than restated, so a fix reverted in ``ci.yml``
    reddens here instead of leaving a test that passes against a copy of itself.

    Args:
        changed: Repository-relative paths the pull request's head commit touches, written and
            committed on top of a seed commit that stands in for the base.
        renamed: ``(from, to)`` pairs created in the base commit and moved with ``git mv`` in
            the head commit, which is the only way to exercise ``--no-renames``.
        patterns: Replaces the workflow's own pattern list, for exercising a list ``grep``
            cannot compile.
        break_diff: Put a ``git`` on PATH that fails ``diff`` and passes everything else, which
            is the only way past the reachability guard to the pipeline behind it.
        expect_failure: Assert the step exits non-zero instead of emitting an answer.

    Returns:
        dict[str, str]: The step's ``$GITHUB_OUTPUT`` — ``app`` — plus its ``stdout``, which
            carries the annotations that say WHY it answered as it did. On a refusal, its
            ``stdout``, its ``stderr``, and whatever it managed to ``record``.

    Raises:
        AssertionError: If the step's exit status disagrees with ``expect_failure``.
    """
    step = _ci_scope_step()
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        repo = root / "repo"
        repo.mkdir()

        git, base = _seed_repo(repo)
        environment = _hermetic_env(
            GITHUB_OUTPUT=str(root / "output.txt"),
            # `mktemp` honours TMPDIR: the script's scratch files land in this invocation's
            # own directory, not in the one every other run of the suite can also write.
            TMPDIR=str(root),
            BASE=base,
            SCOPE_PATTERNS=step["env"]["SCOPE_PATTERNS"]
            if patterns is None
            else patterns,
        )
        for source, _destination in renamed:
            written = repo / source
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_text("to be moved\n", encoding="utf-8")
        if renamed:
            subprocess.run([*git, "add", "-A"], check=True, env=environment)  # noqa: S603
            subprocess.run(  # noqa: S603
                [*git, "commit", "-qm", "before the move"], check=True, env=environment
            )
            environment["BASE"] = subprocess.run(  # noqa: S603
                [*git, "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout.strip()
        for source, destination in renamed:
            (repo / destination).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(  # noqa: S603
                [*git, "mv", source, destination], check=True, env=environment
            )

        for name in changed:
            written = repo / name
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_text("under test\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], check=True, env=environment)  # noqa: S603
        subprocess.run(  # noqa: S603
            [*git, "commit", "-qm", "under test"], check=True, env=environment
        )

        output = pathlib.Path(environment["GITHUB_OUTPUT"])
        output.touch()
        _assert_the_hazard_is_present(git, environment, changed)

        if break_diff:
            real_git = shutil.which("git")
            assert real_git, "no git on PATH"
            shim = root / "bin"
            shim.mkdir()
            (shim / "git").write_text(
                f'#!/bin/sh\nif [ "$1" = diff ]; then exit 128; fi\nexec {real_git} "$@"\n',
                encoding="utf-8",
            )
            (shim / "git").chmod(0o755)
            environment["PATH"] = f"{shim}{os.pathsep}{environment['PATH']}"

        script = root / "scope.sh"
        script.write_text(step["run"], encoding="utf-8")
        finished = subprocess.run(  # noqa: S603
            [_locate_bash("ci.yml"), str(script)],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
        )
        if expect_failure:
            assert finished.returncode != 0, (
                "the scope step was expected to refuse and did not:\n"
                f"{finished.stdout}\n{finished.stderr}"
            )
            return {
                "stdout": finished.stdout,
                "stderr": finished.stderr,
                "record": output.read_text(encoding="utf-8"),
            }
        assert finished.returncode == 0, (
            f"the scope step failed:\n{finished.stdout}\n{finished.stderr}"
        )

        answers = _read_github_output(output)
        answers["stdout"] = finished.stdout
        return answers


def test_the_pull_request_scope_step_answers_both_ways_over_a_real_repository():
    """The positive control, without which every assertion below can pass vacuously.

    A harness that answered ``app=true`` unconditionally — an unreachable base is one way, and
    the step takes that branch by design — would satisfy every quoted-path case here while
    proving nothing. So the pair is asserted together: a documentation-only commit skips, an
    ordinary portal source builds, and neither reaches the unreachable-base escape, which is
    what the annotation discriminates. The skip also has to show the change set it decided over,
    or a wrong `app=false` leaves nothing in the log to diagnose it from.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If either verdict is wrong, or if a verdict came from the fallback.
    """
    skipped = _run_ci_scope(("docs/process/INDEX.md",))
    assert skipped["app"] == "false", (
        "a documentation-only pull request ran the install, the build and the bundle check"
    )
    assert "no app input changed" in skipped["stdout"], (
        "the skip path did not say why it skipped"
    )
    assert "docs/process/INDEX.md" in skipped["stdout"], (
        "the skip path printed a verdict with no evidence under it; a wrong `app=false` is then "
        "undiagnosable from the log, which is the failure this step keeps having"
    )

    built = _run_ci_scope(("apps/portal/src/App.tsx",))
    assert built["app"] == "true", "a portal source change skipped the build"
    for answers in (skipped, built):
        assert "is unreachable" not in answers["stdout"], (
            "the step reached its unreachable-base escape; the fixture's base is not being read, "
            "so every `app=true` below would be that fallback rather than a match"
        )


def test_no_shape_of_quoted_path_can_fall_out_of_the_pull_request_change_set():
    """``--name-only`` C-quotes a path, and a quoted path matches no anchored pattern.

    ``"apps/portal/src/caf\\303\\251.tsx"`` — leading double quote, escaped bytes — fails
    ``^apps/portal/``, so a pull request that genuinely changes the app answers ``app=false``
    and its install, build and bundle check are skipped behind a green check.

    ``core.quotePath=false`` covers bytes >= 0x80 alone and leaves ``"``, ``\\`` and control
    characters still wrapped, which is the same outcome for a different character. ``-z`` emits
    every path raw, closing the class rather than one member of it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If any quoted shape falls out of the change set.
    """
    for name in (
        "apps/portal/src/café.tsx",
        'apps/portal/src/a"b.tsx',
        "apps/portal/src/back\\slash.tsx",
    ):
        answers = _run_ci_scope((name,))
        assert answers["app"] == "true", (
            f"[{name}] was quoted out of the change set; the diff needs -z"
        )


def test_a_file_moved_out_of_the_portal_still_runs_the_build():
    """``--name-only`` reports only a rename's DESTINATION, and the destination is the miss.

    Moving `apps/portal/src/App.tsx` to `packages/` shows up under a pattern that selects, so
    the flag looks harmless. Moving one OUT of both shows up as the destination alone, answers
    ``app=false``, and breaks ``tsc -b`` on main behind a green pull request. The destination is
    deliberately not doc-shaped: a `docs/*.md` fixture path is read as a real documentation
    reference by the doc gate, which then refuses it as a missing file.
    The step's comment has claimed this since it was written and nothing measured it; a refactor
    that moves a file is far likelier than a filename nobody would type.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a file moved out of the portal skips the build.
    """
    answers = _run_ci_scope(
        (), renamed=(("apps/portal/src/Moved.tsx", "tools/moved.txt"),)
    )
    assert answers["app"] == "true", (
        "a file moved out of apps/portal was reported by its destination alone; "
        "the diff needs --no-renames"
    )


def test_the_scope_step_still_dies_on_a_diff_it_cannot_compute():
    """Making the assignment a PIPELINE moved that guarantee onto one shell flag.

    The step's header advertises that a `git diff` which cannot be computed fails the job
    outright rather than reporting an empty change set. As a simple assignment that held under
    `set -e` alone; as `git diff -z … | tr`, it holds only while `pipefail` is also set, because
    a pipeline's status is its LAST command's and `tr` succeeds over nothing. Dropping the flag
    would answer `app=false` for every pull request, silently, with the reassuring notice.

    Both halves are asserted: the flag is present, and a diff that fails really does kill the
    step rather than emitting a verdict. The second is what makes the first more than a spelling
    check — the fixture points BASE at a commit whose object has been removed after the
    reachability guard would have accepted it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the flag is gone, or if an uncomputable diff produces an answer.
    """
    assert "set -euo pipefail" in _ci_scope_step()["run"], (
        "the scope step no longer sets `pipefail`, so a failing `git diff` in its pipeline "
        "reports the exit status of `tr` and answers `app=false` for every pull request"
    )

    answers = _run_ci_scope(
        ("apps/portal/src/App.tsx",), break_diff=True, expect_failure=True
    )
    assert "app=" not in answers["record"], (
        f"the step emitted a verdict over a change set it could not compute: {answers['record']!r}"
    )


def test_no_way_of_breaking_the_pattern_list_reads_as_nothing_changed():
    """The class, not one member of it: every broken list must stop the job.

    Every way this list can stop working answers ``app=false``, which skips the install, the
    build and the bundle check behind the same notice an honest skip prints. Enumerating the
    ways does not work — checking for a grep exit above 1 catches an unbalanced bracket alone,
    because GNU grep answers a lookaround and a stray ``\\d`` with an ordinary "no match" and
    diagnoses neither. So the step runs a path the list must always select through the same
    invocation and refuses anything but a match, which is what these fixtures exercise.

    DROPPED, deliberately, rather than left unsaid: a non-capturing group. GNU grep 3.11 — the
    runner's engine — answers it with exit 1 and the canary catches it, but BSD grep 2.6 happens
    to MATCH it, and this suite runs on a session's own machine. Asserting it would redden on
    macOS and pass in CI. The textual check in ``_assert_pattern_list_is_sane`` is what covers
    that shape on both.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a broken pattern list produces a verdict rather than a refusal.
    """
    for label, broken in (
        ("empty", ""),
        ("an unbalanced bracket", "^apps/portal/[\n"),
        ("a lookahead", "^apps/portal(?=/)\n"),
        ("a stray backslash-d", "^apps/\\dportal/\n"),
    ):
        answers = _run_ci_scope(
            ("apps/portal/src/App.tsx",), patterns=broken, expect_failure=True
        )
        assert "no longer selects" in answers["stdout"], (
            f"a pattern list carrying {label} produced a verdict rather than a refusal:\n"
            f"{answers['stdout']}\n{answers['stderr']}"
        )
        assert "app=" not in answers["record"], (
            f"a pattern list carrying {label} emitted a verdict it could not stand behind"
        )


def test_a_change_set_grep_cannot_read_stops_the_job_rather_than_skipping():
    """The narrower diagnostic behind the canary, for when the LIST is fine.

    A list that matches the canary and then makes grep fail over the change set is grep failing
    on the input rather than on the patterns, and the two want different messages — an operator
    who is told the pattern list is broken will go and read a pattern list that is fine. There
    is no fixture that provokes it, so what is asserted is that the branch exists and says which
    of the two the run got.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the step no longer distinguishes the two, or stopped refusing.
    """
    body = _ci_scope_step()["run"]
    assert '[ "$matched" -gt 1 ]' in body, (
        "the step no longer reads grep's third exit status over the change set, so `could not "
        "perform the test` collapses back into `nothing changed`"
    )
    assert "not the pattern list" in body, (
        "the change-set refusal no longer distinguishes itself from the canary's, which sends "
        "an operator to read a pattern list that is fine"
    )


def test_every_scanner_step_is_ordered_after_the_gate_validation():
    """``needs: gates`` was structural; the condition that replaced it is a repeated string.

    A scanner step added without it runs under a failed gate — the state SPEC-138's rule that
    "did not run is never clean" exists to refuse — and the run is green having enforced nothing.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If ``scan`` holds no scanner steps, if the validation does not precede
            them, or if a scanner step is missing the condition.
    """
    document = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["scan"]["steps"]
    names = [step.get("name", "") for step in steps]

    assert "Validate every gate value" in names, (
        "scan no longer validates the gate values"
    )

    gated = [
        index
        for index, step in enumerate(steps)
        if step.get("name") not in UNGATED_SCAN_STEPS
    ]
    assert gated, (
        "no gated steps found in `scan`; the step list has stopped parsing, or every step is now "
        "named in UNGATED_SCAN_STEPS, and this test is asserting nothing"
    )
    assert names.index("Validate every gate value") < min(gated), (
        "the gate validation must come before every step that depends on it"
    )

    missing = sorted(
        names[index] for index in gated if steps[index].get("if") != GATE_CONDITION
    )
    assert not missing, (
        "these steps in `scan` do not carry the gate condition, so they would run even after the "
        f"gate validation failed: {missing}"
    )


def test_the_gate_validation_cannot_be_marked_continue_on_error():
    """``outcome`` ignores ``continue-on-error``; the step must therefore not carry it.

    With ``continue-on-error: true`` the step's ``outcome`` is still ``failure``, so every
    scanner skips, while its ``conclusion`` is ``success`` and the JOB goes green — a run that
    scanned nothing and said so nowhere. Cheaper to forbid the attribute than to explain it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the validation step is absent or tolerates its own failure.
    """
    document = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
    for job in ("scan", "dast"):
        validation = [
            s
            for s in document["jobs"][job]["steps"]
            if s.get("name") == "Validate every gate value"
        ]
        assert validation, f"`{job}` no longer validates the gate values"
        assert "continue-on-error" not in validation[0], (
            f"`{job}`'s gate validation tolerates its own failure; every scanner would skip on "
            "`outcome` while the job concluded green"
        )


# ---------------------------------------------------------------------------
# `deploy-spa-image.yml`'s scope step
#
# The step decides, on every push to main, whether to build the SPA image and whether to point
# the service at anything. Both answers are SKIPPABLE, which is what makes them worth a fixture
# corpus rather than a reading: a wrong "skip" is a deploy that never happened reported as a
# green deploy, and nothing downstream of it looks any different. The tests below run the step's
# real script — extracted from the workflow, with the workflow's own pattern lists — against a
# throwaway git repository and a stubbed `aws`, and assert the answer for each branch.
#
# THE GREP ENGINE DIVERGES and it is worth naming. These tests run under the local `grep`; the
# step runs under GNU grep on an Actions runner. Every pattern in the two lists is plain ERE —
# an anchor, an escaped dot, an alternation — which the two agree on. Anything cleverer than
# that needs validating against GNU grep before it goes in the list.
DEPLOY_SPA_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-spa-image.yml"
SPA_IMAGE_WORKFLOW = ROOT / ".github" / "workflows" / "spa-image.yml"

#: Paths spanning both lists, the boundaries either could get wrong, and the near misses that
#: must NOT select — `packages.json` for `^package\.json$`, a nested `package.json` for the root
#: one, `infra/modules/spa-something/` for `^infra/modules/spa/`.
SCOPE_CORPUS = (
    "apps/portal/src/App.tsx",
    "apps/portal/Dockerfile",
    "apps/portal/docker/nginx.conf",
    "apps/portal/info/component-inventory/foundations.md",
    "packages/shared/index.ts",
    "package.json",
    "package-lock.json",
    "packages.json",
    "apps/portal/package.json",
    ".nvmrc",
    ".dockerignore",
    ".github/scripts/spa-image-matrix.sh",
    ".github/scripts/point-lambda.sh",
    ".github/workflows/spa-image.yml",
    ".github/workflows/deploy-spa-image.yml",
    ".github/workflows/deploy-lambdas.yml",
    "infra/main.tf",
    "infra/variables.tf",
    "infra/modules/spa/ecs.tf",
    "infra/modules/spa-extras/ecs.tf",
    "infra/modules/lambda-image/ecr.tf",
    "docs/architecture.md",
    "lambdas/api/router.py",
    "CLAUDE.md",
)


def _deploy_spa_step(step_id: str) -> dict:
    """Return one of the deploy workflow's steps, by id rather than by position.

    Args:
        step_id: The step's ``id``.

    Returns:
        dict: The step mapping, including its ``run`` script and ``env`` block.

    Raises:
        AssertionError: If no step carries the id, which means the guards below are asserting
            about a step that no longer exists.
    """
    document = yaml.safe_load(DEPLOY_SPA_WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["deploy"]["steps"]
    found = [step for step in steps if step.get("id") == step_id]
    assert found, f"`deploy-spa-image.yml` has no step with id `{step_id}`"
    return found[0]


def _scope_step() -> dict:
    """Return the deploy workflow's scope step, by id rather than by position.

    Args:
        None.

    Returns:
        dict: The step mapping, including its ``run`` script and ``env`` block.

    Raises:
        AssertionError: If no step carries the id, which means the guards below are asserting
            about a step that no longer exists.
    """
    return _deploy_spa_step("scope")


def _selected_by_regexes(patterns: str) -> set[str]:
    """Return the corpus paths a newline-separated ERE list selects.

    Args:
        patterns: The step's pattern block, one extended regular expression per line.

    Returns:
        set[str]: Every corpus path matching at least one pattern.

    Raises:
        None.
    """
    compiled = [re.compile(line) for line in patterns.split("\n") if line.strip()]
    return {
        path for path in SCOPE_CORPUS if any(rule.search(path) for rule in compiled)
    }


def _selected_by_globs(globs: list[str]) -> set[str]:
    """Return the corpus paths a GitHub ``paths:`` list selects.

    Only the two glob shapes the SPA lists actually use are understood — a literal path, and a
    ``dir/**`` prefix. Anything else RAISES rather than being approximated, because a matcher
    that quietly mishandles a shape agrees with the regex list for the wrong reason, which is
    the failure this comparison exists to catch. The matcher is the path-filter guard's, so
    the two tests cannot disagree about what a ``paths:`` entry selects.

    Args:
        globs: The workflow's ``paths:`` entries.

    Returns:
        set[str]: Every corpus path the list selects.

    Raises:
        AssertionError: If an entry uses a glob shape this matcher does not implement.
    """
    return {path for path in SCOPE_CORPUS if _path_filter_guard._filter_selects(globs, path)}


def test_the_image_scope_list_and_the_pull_request_gate_select_the_same_paths():
    """The deploy's build decision and the PR gate's trigger must be one set, written twice.

    `spa-image.yml` decides whether the image is PROVEN; the scope step decides whether it is
    BUILT AND DEPLOYED. A path in one list and not the other is not a smaller saving, it is a
    silent one in whichever direction it leans: an unproven image, or production left running
    the previous bundle behind a green deploy.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the two lists disagree, or if the comparison went vacuous.
    """
    patterns = _scope_step()["env"]["IMAGE_PATTERNS"]
    gate = yaml.safe_load(SPA_IMAGE_WORKFLOW.read_text(encoding="utf-8"))
    globs = gate[True]["pull_request"]["paths"]

    by_regex = _selected_by_regexes(patterns)
    by_glob = _selected_by_globs(globs)

    # A POSITIVE CONTROL FIRST. Two empty sets are equal, and an equality over nothing is the
    # shape this repository has shipped green before.
    assert "apps/portal/src/App.tsx" in by_regex, (
        "the regex list selects nothing; the comparison below would be vacuous"
    )
    assert "apps/portal/src/App.tsx" in by_glob, (
        "the glob list selects nothing; the comparison below would be vacuous"
    )
    assert "docs/architecture.md" not in by_regex, (
        "the regex list selects everything; it would agree with any glob list"
    )

    assert by_regex == by_glob, (
        "`deploy-spa-image.yml`'s IMAGE_PATTERNS and `spa-image.yml`'s `paths:` disagree.\n"
        f"  only the deploy's list selects: {sorted(by_regex - by_glob)}\n"
        f"  only the gate's list selects:   {sorted(by_glob - by_regex)}"
    )


def test_the_task_scope_list_selects_what_shapes_the_task_definition():
    """The narrower list must cover the runtime-configuration map and the SPA module, and no more.

    It decides which pushes hold the run until their own apply has finished, because Terraform
    registers a revision this workflow would otherwise read the family too early to see. Widening
    it to `infra/` would hold the SPA deploy on every infrastructure merge — 19 of the 40 measured
    — for applies that, outside these two paths, can move a configuration value only through a
    module output or a variable default.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the list stops selecting an input to the task definition, or starts
            selecting infrastructure that cannot change one.
    """
    selected = _selected_by_regexes(_scope_step()["env"]["TASK_PATTERNS"])
    assert selected == {"infra/main.tf", "infra/modules/spa/ecs.tf"}, (
        f"the task-definition scope list selects {sorted(selected)}; it must select the runtime "
        "configuration map and the SPA module, and neither the rest of infra nor a module whose "
        "name merely starts with `spa`"
    )


#: The stub `aws`. Every answer the `names` and scope steps read comes from the environment, so a
#: fixture describes a deployment rather than a sequence of calls. The two
#: `describe-task-definition` calls are told apart by their `--query`, which is the only thing that
#: differs between asking what the service RUNS and asking what the family's newest revision IS.
#: The newest revision MOVES once this commit's apply has finished, which is the race the scope
#: step waits out: read before then, the family answers with what it held before the apply.
FAKE_AWS = """#!/usr/bin/env python3
import json, os, pathlib, sys

argv = sys.argv[1:]
if argv[:2] == ["ecr", "describe-repositories"]:
    uri = os.environ["FAKE_REPOSITORY_URI"]
    if argv[argv.index("--repository-names") + 1] != uri.rsplit("/", 1)[1]:
        sys.exit(254)
    print(uri)
elif argv[:2] == ["ecs", "describe-services"]:
    # `services[0]` over an empty list is `null`, printed on a SUCCESSFUL call. Modelling a
    # missing service as a non-zero exit would leave the step's `null` branch unexercised
    # while this fixture claimed to cover it.
    if os.environ["FAKE_SERVICE_CALL"] == "fails":
        sys.exit(255)
    print(os.environ["FAKE_SERVICE_JSON"])
elif argv[:2] == ["ecs", "describe-task-definition"]:
    query = argv[argv.index("--query") + 1]
    if "containerDefinitions" in query:
        print(os.environ["FAKE_RUNNING_IMAGE"])
    elif os.environ["FAKE_NEWEST_CALL"] == "fails":
        sys.exit(255)
    elif (pathlib.Path(os.environ["FAKE_STATE"]) / "applied").exists():
        print(os.environ["FAKE_APPLIED_ARN"])
    else:
        print(os.environ["FAKE_NEWEST_ARN"])
elif argv[:2] == ["ecr", "describe-images"]:
    # A FAILED CALL IS NOT AN ABSENT IMAGE, and modelling only exit 0 and exit 254 is how that
    # difference stays invisible: a throttle and a missing tag look identical to a bare `else`.
    if os.environ["FAKE_ECR_CALL"] == "fails":
        sys.exit(255)
    tag = [a for a in argv if a.startswith("imageTag=")][0].split("=", 1)[1].strip()
    if len(tag) > 1 and tag[0] == tag[-1] and tag[0] in "'\\"":
        tag = tag[1:-1]
    if os.environ.get("FAKE_AWS_LOG"):
        with open(os.environ["FAKE_AWS_LOG"], "a", encoding="utf-8") as log:
            log.write(json.dumps(tag) + "\\n")
    sys.exit(0 if tag in os.environ["FAKE_EXISTING_TAGS"].split(",") else 254)
else:
    sys.exit(2)
"""

#: The stub `gh`, answering the one question the scope step asks it: the runs of the apply
#: workflow for this commit. Each call takes the next answer from ``FAKE_RUNS`` and the last one
#: repeats, and the answer is put through the step's own ``--jq`` expression by the real ``jq``,
#: so the expression is exercised rather than assumed. The first COMPLETED answer is what moves
#: the family's newest revision. A question about any other commit or workflow is answered the way
#: GitHub would answer it about a past push — finished and green — without moving anything, so a
#: step that asked the wrong question is told it can go on, and reads the family too early.
FAKE_GH = """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, urllib.parse

state = pathlib.Path(os.environ["FAKE_STATE"])
with (state / "gh-calls").open("a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
polls = len((state / "gh-calls").read_text(encoding="utf-8").splitlines())
argv = sys.argv[1:]
if argv[:1] != ["api"] or os.environ["FAKE_RUNS_CALL"] == "fails":
    sys.exit(1)
endpoint = urllib.parse.urlsplit(argv[1])
wanted = "repos/{}/actions/workflows/{}/runs".format(
    os.environ["GITHUB_REPOSITORY"], os.environ["APPLY_WORKFLOW"]
)
query = urllib.parse.parse_qs(endpoint.query)
if endpoint.path == wanted and query.get("head_sha") == [os.environ["GITHUB_SHA"]]:
    answers = json.loads(os.environ["FAKE_RUNS"])
    runs = answers[min(polls, len(answers)) - 1]
    if runs and runs[0]["status"] == "completed":
        (state / "applied").touch()
else:
    runs = [{"status": "completed", "conclusion": "success"}]
body = json.dumps({"total_count": len(runs), "workflow_runs": runs})
expression = argv[argv.index("--jq") + 1]
sys.exit(subprocess.run(["jq", "-r", expression], input=body, text=True).returncode)
"""

#: The stub `sleep`: records how long the step asked to wait and returns at once, so the wait's
#: window is measured without being spent.
FAKE_SLEEP = """#!/bin/sh
echo "$1" >> "$FAKE_STATE/slept"
"""

#: What the apply workflow's run lookup can answer, one poll at a time.
APPLY_RUNNING = ({"status": "in_progress", "conclusion": None},)
APPLY_SUCCEEDED = ({"status": "completed", "conclusion": "success"},)
APPLY_FAILED = ({"status": "completed", "conclusion": "failure"},)
APPLY_CANCELLED = ({"status": "completed", "conclusion": "cancelled"},)

#: The shortest wait for an apply the scope step may give up after. It must outlast the slowest
#: apply a push actually gets, QUEUE INCLUDED, because giving up early reddens main on a push whose
#: apply was only behind another. The number lives here, where a test reads it: re-measure the
#: apply workflow's push runs (``gh api 'repos/{owner}/{repo}/actions/workflows/deploy-infra.yml/
#: runs?event=push&per_page=100'``, created to updated) before lowering it.
MINIMUM_APPLY_WAIT_SECONDS = 660


def _run_scope(
    changed: tuple[str, ...],
    *,
    intermediate: tuple[str, ...] = (),
    deployed: str = "baseline",
    newest_is_running: bool = True,
    existing_tags: tuple[str, ...] = (),
    dispatched: bool = False,
    tag_input: str = "",
    image_patterns: str | None = None,
    expect_failure: bool = False,
    rollout: str = "COMPLETED",
    desired: int = 2,
    running: int = 2,
    service_call: str = "ok",
    newest_call: str = "ok",
    ecr_call: str = "ok",
    apply_runs: tuple[tuple[dict, ...], ...] = (APPLY_RUNNING, APPLY_SUCCEEDED),
    apply_registers: bool = False,
    runs_call: str = "ok",
) -> dict[str, str | int]:
    """Run the workflow's real scope script over a throwaway repository and stubbed AWS.

    Args:
        changed: Repository-relative paths the commit under test touches.
        intermediate: Paths touched by a commit BETWEEN the deployed one and the one under test —
            a merge that was already deployed, or one whose run only re-pointed.
        deployed: What the service is running — ``baseline`` for the previous commit, ``absent``
            for no service at all, ``placeholder`` for the pre-first-deploy image, or
            ``unreachable`` for a sha this clone does not hold.
        newest_is_running: False when Terraform has registered a revision nobody has pointed at
            before this run began.
        apply_runs: What each successive lookup of this commit's apply run answers, the last
            repeating. The default is still running on the first poll and finished on the second.
        apply_registers: True when this commit's apply registers a revision as it finishes, so
            the family's newest revision moves only once the apply is over.
        runs_call: ``fails`` to make every lookup of the apply run error.
        existing_tags: Tags the registry already holds, which is how a re-run is described. The
            literal ``HEAD`` stands for this commit's sha, which the caller cannot know in advance.
        dispatched: True to exercise the manual recovery lever.
        tag_input: The dispatch's ``image_tag`` input. The literal ``HEAD`` stands for this
            commit's sha, as it does in ``existing_tags``.
        rollout: The PRIMARY deployment's ``rolloutState``. Anything but ``COMPLETED`` describes a
            revision the service was pointed at and which never landed — the circuit breaker runs
            with rollback disabled, so PRIMARY stays on it.
        desired: The service's desired task count.
        running: The service's running task count.
        service_call: ``fails`` to make ``describe-services`` itself error.
        newest_call: ``fails`` to make the newest-revision read error.
        ecr_call: ``fails`` to make the registry read error rather than answer absent.
        image_patterns: Replaces the workflow's own image list, for exercising a list `grep`
            cannot compile.
        expect_failure: Assert the step exits non-zero instead of emitting an answer.

    Returns:
        dict[str, str | int]: The step's ``$GITHUB_OUTPUT`` — ``tag``, ``build`` and ``deploy``
            — with ``polls``, how many times it asked after the apply, and ``slept``, the seconds
            it asked to wait in all.

    Raises:
        AssertionError: If the script exits non-zero, with its output attached.
    """
    step = _scope_step()
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        repo, binaries, state = root / "repo", root / "bin", root / "state"
        repo.mkdir()
        binaries.mkdir()
        state.mkdir()

        for name, body in (("aws", FAKE_AWS), ("gh", FAKE_GH), ("sleep", FAKE_SLEEP)):
            stub = binaries / name
            stub.write_text(body, encoding="utf-8")
            stub.chmod(0o755)

        git, baseline = _seed_repo(repo)
        clean = _hermetic_env()

        def commit(paths: tuple[str, ...], message: str) -> None:
            for name in paths:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"{message}\n", encoding="utf-8")
            subprocess.run([*git, "add", "-A"], check=True, env=clean)  # noqa: S603
            subprocess.run(  # noqa: S603
                [*git, "commit", "-qm", message], check=True, env=clean
            )

        if intermediate:
            commit(intermediate, "already deployed")
        commit(changed, "under test")
        head = subprocess.run(  # noqa: S603
            [*git, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            env=clean,
        ).stdout.strip()

        image = {
            "baseline": f"registry/dat-prod-spa:{baseline}",
            "placeholder": "registry/dat-prod-spa:placeholder",
            "unreachable": "registry/dat-prod-spa:" + "f" * 40,
            "absent": "",
        }[deployed]
        running_arn = (
            ""
            if deployed == "absent"
            else "arn:aws:ecs:::task-definition/dat-prod-spa:7"
        )
        service = (
            "null"
            if deployed == "absent"
            else json.dumps(
                {
                    "taskDefinition": running_arn,
                    "desiredCount": desired,
                    "runningCount": running,
                    "deployments": [{"status": "PRIMARY", "rolloutState": rollout}],
                }
            )
        )
        newest_arn = (
            running_arn
            if newest_is_running
            else "arn:aws:ecs:::task-definition/dat-prod-spa:8"
        )

        output = root / "output.txt"
        output.touch()
        environment = {
            **_hermetic_env(),
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            # `mktemp` honours TMPDIR: the script's scratch files land in this invocation's
            # own directory, not in the one every other run of the suite can also write.
            "TMPDIR": str(root),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_SHA": head,
            "NAME": "dat-prod-spa",
            "CLUSTER": "dat-prod-spa",
            "SERVICE": "dat-prod-spa",
            "TAG_INPUT": head if tag_input == "HEAD" else tag_input,
            "DISPATCHED": "true" if dispatched else "false",
            "IMAGE_PATTERNS": step["env"]["IMAGE_PATTERNS"]
            if image_patterns is None
            else image_patterns,
            "TASK_PATTERNS": step["env"]["TASK_PATTERNS"],
            "APPLY_WORKFLOW": step["env"]["APPLY_WORKFLOW"],
            "GITHUB_REPOSITORY": "owner/repo",
            "FAKE_STATE": str(state),
            "FAKE_RUNS": json.dumps(apply_runs),
            "FAKE_RUNS_CALL": runs_call,
            "FAKE_SERVICE_JSON": service,
            "FAKE_SERVICE_CALL": service_call,
            "FAKE_NEWEST_CALL": newest_call,
            "FAKE_ECR_CALL": ecr_call,
            "FAKE_RUNNING_IMAGE": image,
            "FAKE_NEWEST_ARN": newest_arn,
            "FAKE_APPLIED_ARN": "arn:aws:ecs:::task-definition/dat-prod-spa:9"
            if apply_registers
            else newest_arn,
            # THE BASELINE'S OWN TAG IS ALWAYS PRESENT when the service is running it, because a
            # service cannot run an image the registry does not hold. Leaving it out models a
            # registry that contradicts the deployment, and every re-point fixture would then
            # assert a rebuild that production would never do.
            "FAKE_EXISTING_TAGS": ",".join(
                [head if tag == "HEAD" else tag for tag in existing_tags]
                + ([baseline] if deployed == "baseline" else [])
            ),
        }

        _assert_the_hazard_is_present(git, environment, changed, base=baseline)

        script = root / "scope.sh"
        script.write_text(step["run"], encoding="utf-8")
        finished = subprocess.run(  # noqa: S603
            [_locate_bash("deploy-spa-image.yml"), str(script)],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
        )
        calls, slept = state / "gh-calls", state / "slept"
        waited = {
            "polls": len(calls.read_text(encoding="utf-8").splitlines())
            if calls.exists()
            else 0,
            "slept": sum(
                int(line) for line in slept.read_text(encoding="utf-8").split()
            )
            if slept.exists()
            else 0,
        }
        if expect_failure:
            assert finished.returncode != 0, (
                f"the scope step was expected to refuse and did not:\n{finished.stdout}"
            )
            return {
                "stdout": finished.stdout,
                "baseline": baseline,
                "head": head,
                **waited,
            }
        assert finished.returncode == 0, (
            f"the scope step failed:\n{finished.stdout}\n{finished.stderr}"
        )

        answers = _read_github_output(output)
        answers["baseline"] = baseline
        answers["head"] = head
        answers["stdout"] = finished.stdout
        return {**answers, **waited}


def test_a_commit_touching_nothing_the_image_or_the_task_definition_reads_does_neither():
    """The saving itself: a documentation merge builds nothing and leaves production alone.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If either half of the run is still scheduled.
    """
    answers = _run_scope(
        ("docs/architecture.md", "lambdas/api/router.py", "infra/variables.tf")
    )
    assert (answers["build"], answers["deploy"]) == ("skip", "skip")
    assert answers["tag"] == answers["baseline"], (
        "a skipped run must keep naming the running commit"
    )


def test_a_portal_change_builds_and_deploys_this_commit():
    """The negative control for the test above, and the ordinary path.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a real change to the bundle is skipped.
    """
    answers = _run_scope(("apps/portal/src/App.tsx", "docs/architecture.md"))
    assert (answers["build"], answers["deploy"]) == ("run", "run")
    assert answers["tag"] == answers["head"]


def test_a_change_under_packages_builds():
    """`packages/` is empty today, which is exactly why its absence from a list goes unnoticed.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a workspace package the bundle could import fails to trigger a build.
    """
    assert _run_scope(("packages/shared/index.ts",))["build"] == "run"


def test_a_configuration_change_waits_for_its_apply_then_points_at_what_it_registered():
    """The family is read only after this push's apply, or the deploy clones what it superseded.

    The apply runs in another workflow on the same push, and this one reaches the family first.
    A read before the apply finishes finds the revision from before it — same keys, old values —
    and the register step, which counts keys, deploys it green. So the step asks after this
    commit's apply until it has finished, and only then compares the family with the service.
    The same holds when the push also changes the image, and when the service has no baseline:
    either way the register step clones the family, and must clone the new revision.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the family is read before the apply finished, which leaves the
            service on the revision the apply superseded.
    """
    only = _run_scope(("infra/main.tf",), apply_registers=True)
    assert (only["build"], only["deploy"]) == ("skip", "run"), (
        "a configuration change was decided before its apply finished, so the revision the apply "
        "registered was never seen"
    )
    assert only["tag"] == only["baseline"], (
        "re-pointing must reuse the running image, not build a new one"
    )
    assert only["polls"] == 2, "the step stopped asking before the apply had finished"

    with_image = _run_scope(
        ("apps/portal/src/App.tsx", "infra/modules/spa/ecs.tf"), apply_registers=True
    )
    assert (with_image["build"], with_image["deploy"]) == ("run", "run")
    assert with_image["polls"] == 2, (
        "a push changing the image and the task definition was built without waiting for its "
        "apply, so the register step clones the revision from before it"
    )

    # A service with no baseline builds and deploys straight away, and the register step still
    # clones the family, so the wait has to come before those exits too.
    unanchored = _run_scope(
        ("infra/main.tf",), deployed="placeholder", apply_registers=True
    )
    assert (unanchored["build"], unanchored["deploy"]) == ("run", "run")
    assert unanchored["polls"] == 2, (
        "a configuration push to a service with no baseline was deployed without waiting for "
        "its apply"
    )


def test_a_configuration_push_whose_apply_registered_nothing_leaves_the_service_alone():
    """Most pushes touching `infra/main.tf` change nothing the task definition renders.

    Their apply registers no revision, so after the wait the family still holds the one the
    service runs, and there is nothing to point at. Re-pointing anyway rolls the production tasks
    onto a copy of what they already run — which is all the list used to buy, every time.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a push whose apply changed nothing still rolls the service, or reaches
            that verdict without having waited for the apply.
    """
    answers = _run_scope(("infra/main.tf",), apply_registers=False)
    assert (answers["build"], answers["deploy"]) == ("skip", "skip"), (
        "a push whose apply registered no revision still re-pointed the service"
    )
    assert answers["polls"] == 2, (
        "the verdict was reached without waiting for the apply"
    )


def test_an_apply_that_never_finishes_stops_the_run_rather_than_reading_past_it():
    """Reading the family while the apply may still register is the defect, arriving late.

    So the wait ends in a refusal, not a guess — after a window long enough that a routine apply
    queued behind another cannot trip it. An answer GitHub will not give is waited out the same
    way rather than read as finished.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the step goes on without the apply, gives up inside the window, or
            refuses without saying why.
    """
    for label, fixture in (
        ("an apply still running", {"apply_runs": (APPLY_RUNNING,)}),
        ("a lookup that errors", {"runs_call": "fails"}),
    ):
        answers = _run_scope(("infra/main.tf",), expect_failure=True, **fixture)
        assert "::error title=Apply not finished::" in answers["stdout"], (
            f"{label}: the step refused, but not with the message that names the apply"
        )
        assert answers["slept"] >= MINIMUM_APPLY_WAIT_SECONDS, (
            f"{label}: the step gave up after {answers['slept']} seconds, which a routine apply "
            "queued behind another can outlast"
        )


def test_a_failed_apply_is_reported_and_the_run_decides_from_what_it_can_read():
    """An apply that finished without succeeding is said, and the run goes on from live state.

    A failed apply is a red main already, and adding a second red for it holds back an image
    that may not depend on it. A cancelled one is what GitHub leaves when a newer push's run
    replaces a pending one: it will never finish any further, so waiting on it runs out the
    window and reddens main for a push that did nothing wrong.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a finished-but-unsuccessful apply reddens this run or passes
            unreported.
    """
    for label, runs in (
        ("a failed apply", APPLY_FAILED),
        ("a cancelled apply", APPLY_CANCELLED),
    ):
        answers = _run_scope(("infra/main.tf",), apply_runs=(runs,))
        assert (answers["build"], answers["deploy"]) == ("skip", "skip"), (
            f"{label} did not let the run decide from what the family holds"
        )
        assert "::warning title=Apply did not succeed::" in answers["stdout"], (
            f"{label} was waited out silently, so nothing says the family may not carry this "
            "commit's configuration"
        )


def test_nothing_but_a_push_touching_the_task_definition_waits():
    """The wait is paid by the pushes it protects, and the recovery lever never pays it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If an ordinary push or a dispatch asks after the apply.
    """
    assert _run_scope(("apps/portal/src/App.tsx",))["polls"] == 0, (
        "a push touching nothing the task definition reads waited for an apply"
    )
    assert _run_scope(("infra/main.tf",), dispatched=True)["polls"] == 0, (
        "a dispatch waited for an apply; the recovery lever does what it is told"
    )


def test_every_path_the_task_list_waits_on_fires_the_apply_it_waits_for():
    """A push the task list selects waits for a run of the apply workflow, so there must be one.

    A path in the task list that the apply workflow's `paths:` does not cover waits the full
    window for a run that is never created, and reddens main on every push touching it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the named workflow is missing or does not fire on a path the task
            list selects.
    """
    step = _scope_step()
    workflow = ROOT / ".github" / "workflows" / step["env"]["APPLY_WORKFLOW"]
    assert workflow.is_file(), (
        f"the scope step waits for {workflow.name}, which does not exist"
    )

    waited_on = _selected_by_regexes(step["env"]["TASK_PATTERNS"])
    assert waited_on, (
        "the task list selects nothing; the comparison below would be vacuous"
    )
    fired = _selected_by_globs(
        yaml.safe_load(workflow.read_text(encoding="utf-8"))[True]["push"]["paths"]
    )
    assert waited_on <= fired, (
        f"{workflow.name} does not fire on {sorted(waited_on - fired)}, so a push touching it "
        "waits for an apply run that is never created"
    )


def test_the_scope_step_holds_a_token_that_may_read_the_apply_runs():
    """The harness builds its own environment, so it cannot see what the runner hands the step.

    `gh` refuses to run with no token at all, and the runs endpoint refuses a token without the
    Actions permission in a private repository. Either way every lookup reads as unreadable,
    and every push touching the task definition waits out the window and reddens main.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the job's token cannot read workflow runs, or the step is not given
            it.
    """
    document = yaml.safe_load(DEPLOY_SPA_WORKFLOW.read_text(encoding="utf-8"))
    permissions = document["jobs"]["deploy"]["permissions"]
    assert permissions.get("actions") in ("read", "write"), (
        f"the deploy job's token is granted {permissions}, which cannot list workflow runs"
    )
    assert _scope_step()["env"].get("GH_TOKEN") == "${{ github.token }}", (
        "the scope step is not handed the job's token as GH_TOKEN, so `gh` has nothing to ask with"
    )


def test_a_revision_nobody_pointed_at_is_deployed_without_rebuilding():
    """The apply landed before this run: the newest revision exists and the service is not on it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a registered revision is left unpointed.
    """
    answers = _run_scope(("docs/architecture.md",), newest_is_running=False)
    assert (answers["build"], answers["deploy"]) == ("skip", "run")


def test_every_unreadable_baseline_builds_and_deploys():
    """Absent service, placeholder image, unreachable commit — each fails in the expensive direction.

    A cheap green that deployed nothing looks exactly like a real one, so none of these may
    resolve to a skip.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If any unreadable baseline is treated as "nothing changed".
    """
    for deployed in ("absent", "placeholder", "unreachable"):
        answers = _run_scope(("docs/architecture.md",), deployed=deployed)
        assert (answers["build"], answers["deploy"]) == ("run", "run"), (
            f"a {deployed} baseline skipped work"
        )
        assert answers["tag"] == answers["head"]

        # And it still asks the registry first. A run that got as far as pushing and then failed
        # leaves the tag behind, and the repository is IMMUTABLE — rebuilding it fails at the
        # push, which is the one recovery the dispatch lever should not be needed for.
        again = _run_scope(
            ("docs/architecture.md",), deployed=deployed, existing_tags=("HEAD",)
        )
        assert (again["build"], again["deploy"]) == ("skip", "run"), (
            f"a {deployed} baseline rebuilt a tag the registry already holds"
        )


def test_a_dispatch_with_an_empty_input_deploys_this_commit_building_it_only_if_absent():
    """The recovery lever never skips: it is reached for when this step's own reasoning is wrong.

    So a commit that changed nothing still deploys, and builds when the registry lacks it.
    Naming this commit's own sha is the same request and is decided the same way: `names` checks
    only that a tag OTHER than this commit exists, so this one arrives unchecked and has to be
    asked about, never answered `skip` by construction. And asking is what lets a dispatch after
    the push run already built this commit — the ordinary way to pick up a revision Terraform
    registered — reuse the image, because the registry is IMMUTABLE and a rebuild fails at the
    push.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If either spelling of "this commit" plans anything but a deploy of it,
            or builds it when the registry already holds it, or skips building it when not.
    """
    for tag_input, existing_tags, build in (
        ("", (), "run"),
        ("HEAD", (), "run"),
        ("", ("HEAD",), "skip"),
    ):
        answers = _run_scope(
            ("docs/architecture.md",),
            dispatched=True,
            tag_input=tag_input,
            existing_tags=existing_tags,
        )
        plan = (answers["tag"], answers["build"], answers["deploy"])
        assert plan == (answers["head"], build, "run"), (
            f"a dispatch naming [{tag_input}] with the registry holding {existing_tags} "
            f"planned {plan}"
        )


def test_a_dispatch_naming_an_existing_older_tag_re_points_without_building():
    """The lever's other half points the service at an image that is already built.

    `names` refuses a tag the registry does not hold, so one that reaches the scope step exists
    and answers `skip` by construction, as every other re-point does. It is never asked about,
    because a failed read is not an absent image: answering "absent" for an older sha builds the
    CURRENT tree and pushes it under that older commit's tag. The registry read fails in the
    second run, so the answer is pinned to the construction rather than to what the read says.
    This commit changes the bundle, so falling through to the push path would build it instead.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the named tag is refused, rebuilt, or replaced by another.
    """
    older = "a" * 40
    for ecr_call in ("ok", "fails"):
        answers = _run_scope(
            ("apps/portal/src/App.tsx",),
            dispatched=True,
            tag_input=older,
            existing_tags=(older,),
            ecr_call=ecr_call,
        )
        plan = (answers["tag"], answers["build"], answers["deploy"])
        assert plan == (older, "skip", "run"), (
            f"a dispatch naming an existing tag, registry read {ecr_call}, planned {plan}"
        )


def _run_names(
    tag_input: str,
    *,
    existing_tags: tuple[str, ...] = (),
    expect_failure: bool = False,
) -> tuple[dict[str, str], str, list[str]]:
    """Run the deploy workflow's real ``names`` script against a stubbed registry.

    `names` is the one step that asks the registry whether a dispatched tag exists, and the
    scope step answers ``skip`` for that tag by construction because of it — so the refusal here
    is the only check that the image a dispatch re-points at is real. The stub answers
    ``describe-images`` the way the CLI does rather than the way the script spells the call:
    measured against the CLI's own request body, it trims the ``imageTag=`` value, newlines
    included, and strips the quotes from around it. A stub comparing the raw argument would refuse
    a padded tag as unknown where the real CLI finds it; modelling the respelling is what makes an
    input that slips past the grammar behave here as it would in production — resolved, and handed
    on under a spelling the registry does not hold.

    Args:
        tag_input: The dispatch's ``image_tag`` input. The literal ``HEAD`` stands for this
            commit's sha.
        existing_tags: Tags the registry holds.
        expect_failure: Assert the step exits non-zero instead of resolving the names.

    Returns:
        tuple[dict[str, str], str, list[str]]: The step's ``$GITHUB_OUTPUT``, what it printed,
            and every tag it asked ``describe-images`` about, spelled as the CLI sends it.

    Raises:
        AssertionError: If the step's exit status is not the one expected, with its output
            attached.
    """
    step = _deploy_spa_step("names")
    head = "c" * 40
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        binaries = root / "bin"
        binaries.mkdir()
        stub = binaries / "aws"
        stub.write_text(FAKE_AWS, encoding="utf-8")
        stub.chmod(0o755)
        output, log = root / "output.txt", root / "aws.log"
        output.touch()
        log.touch()
        script = root / "names.sh"
        script.write_text(step["run"], encoding="utf-8")
        finished = subprocess.run(  # noqa: S603
            [_locate_bash("deploy-spa-image.yml"), str(script)],
            cwd=root,
            env=_hermetic_env(
                PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
                TMPDIR=str(root),
                GITHUB_OUTPUT=str(output),
                GITHUB_SHA=head,
                PROJECT="dat",
                ENVIRONMENT="prod",
                TAG_INPUT=head if tag_input == "HEAD" else tag_input,
                FAKE_REPOSITORY_URI="registry.example/dat-prod-spa",
                FAKE_ECR_CALL="ok",
                FAKE_EXISTING_TAGS=",".join(existing_tags),
                FAKE_AWS_LOG=str(log),
            ),
            capture_output=True,
            text=True,
        )
        refused = finished.returncode != 0
        assert refused == expect_failure, (
            f"the names step was expected to {'refuse' if expect_failure else 'pass'} and "
            f"exited {finished.returncode}:\n{finished.stdout}\n{finished.stderr}"
        )
        looked_up = [
            json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
        ]
        return _read_github_output(output), finished.stdout, looked_up


def test_the_names_step_refuses_a_dispatch_naming_a_tag_the_registry_does_not_hold():
    """A dispatched tag is deployed without the scope step asking about it, so `names` must.

    Past this refusal the tag is answered ``skip`` by construction and the register step points
    the service at it, so letting a missing tag through points production at an image the
    registry does not hold. The registry holds a different tag, so a lookup that ignored its
    argument would be found out, and nothing may be written for the later steps to read.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the step resolves the names for a missing tag, or refuses it for any
            reason other than its absence.
    """
    missing, held = "b" * 40, "a" * 40
    outputs, stdout, looked_up = _run_names(
        missing, existing_tags=(held,), expect_failure=True
    )
    assert f"::error title=Unknown tag::{missing} is not in the registry." in stdout, (
        f"a dispatch naming a missing tag was refused for another reason:\n{stdout}"
    )
    assert looked_up == [missing], f"the step asked the registry about {looked_up}"
    assert outputs == {}, f"a refused dispatch still wrote {outputs}"


def test_the_names_step_resolves_an_existing_tag_and_never_looks_up_this_commit():
    """A tag the registry holds resolves the names; this commit's sha is not asked about at all.

    This commit's image is what the run is about to build, so the registry lacks it on every
    first attempt, and asking about it would refuse the ordinary dispatch that builds it. The
    scope step asks about it instead. An empty input means this commit too, and neither spelling
    may reach the registry here.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If any of the three inputs is refused, writes other names, or asks the
            registry about a tag it should not.
    """
    held = "a" * 40
    for tag_input, lookups in ((held, [held]), ("HEAD", []), ("", [])):
        outputs, _, looked_up = _run_names(tag_input, existing_tags=(held,))
        assert outputs == {
            "repo": "registry.example/dat-prod-spa",
            "family": "dat-prod-spa",
            "cluster": "dat-prod-spa",
            "service": "dat-prod-spa",
        }, f"a dispatch naming [{tag_input}] resolved {outputs}"
        assert looked_up == lookups, (
            f"a dispatch naming [{tag_input}] asked the registry about {looked_up}"
        )


def test_the_names_step_refuses_a_malformed_tag_before_the_registry_sees_it():
    """An input outside the tag grammar is refused before the lookup, and never printed.

    Every respelled row is an input the CLI reduces to a tag the registry holds, so without the
    grammar it is found, and the scope step writes it out as typed — naming an image that does
    not exist and, for the newline rows, writing a second line into ``$GITHUB_OUTPUT``. The space
    and newline rows come one per side, which is what a widened character class or a dropped
    anchor would let through. The last row is an unknown tag followed by a workflow command: the
    unknown-tag refusal prints the input, so reaching it would print a spoofed plan as a notice of
    its own.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a malformed input is looked up, refused for another reason, or printed
            as a workflow command of its own.
    """
    held = "a" * 40
    spoof = f"::notice title=Plan::tag={held} build=skip deploy=run"
    for tag_input in (
        f" {held}",
        f"{held} ",
        f"'{held}'",
        f"{held}\n",
        f"\n{held}",
        f"{'b' * 40}\n{spoof}",
    ):
        outputs, stdout, looked_up = _run_names(
            tag_input, existing_tags=(held,), expect_failure=True
        )
        assert "::error title=Malformed tag::" in stdout, (
            f"a dispatch naming {tag_input!r} was refused for another reason:\n{stdout}"
        )
        assert looked_up == [], f"{tag_input!r} reached the registry as {looked_up}"
        commands = [
            line for line in stdout.splitlines() if line.lstrip().startswith("::")
        ]
        assert len(commands) == 1, (
            f"a dispatch naming {tag_input!r} printed {len(commands)} workflow commands:\n"
            f"{stdout}"
        )
        assert outputs == {}, f"a refused dispatch still wrote {outputs}"


def test_the_scope_step_runs_only_after_names_has_passed():
    """The scope step writes a dispatched tag out unchecked, because `names` has checked it.

    Both the tag's existence and its form are refused in `names`, and the scope step answers
    ``skip`` for the tag and writes it into ``$GITHUB_OUTPUT`` on that strength. So the ordering
    carries both checks: `names` must come first, must not tolerate its own failure, and the scope
    step must carry no condition under which it could run after `names` failed.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the scope step could run without `names` having passed.
    """
    names, scope = _deploy_spa_step("names"), _deploy_spa_step("scope")
    steps = yaml.safe_load(DEPLOY_SPA_WORKFLOW.read_text(encoding="utf-8"))["jobs"][
        "deploy"
    ]["steps"]
    order = [step.get("id") for step in steps]
    assert order.index("names") < order.index("scope"), (
        "the scope step runs before `names`, so a dispatched tag reaches it unchecked"
    )
    assert names.get("continue-on-error", False) is False, (
        "`names` tolerates its own failure, so the scope step runs after a refused tag and "
        "writes it out"
    )
    assert "if" not in scope, (
        f"the scope step carries `if: {scope.get('if')}`, which could run it after `names` failed"
    )


def test_a_re_run_reuses_the_image_its_first_attempt_pushed():
    """The registry is IMMUTABLE, so rebuilding a pushed tag fails at the push and nowhere sooner.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a re-run schedules a build of a tag that already exists.
    """
    answers = _run_scope(("apps/portal/src/App.tsx",), existing_tags=("HEAD",))
    assert answers["build"] == "skip", (
        "a tag already in the registry must not be rebuilt"
    )
    assert answers["deploy"] == "run", "but the service still has to be pointed at it"


def test_both_spa_pattern_lists_mean_what_they_look_like():
    """The SPA lists are fed to the same ``grep -f``, so they own the same failure modes.

    The guard existed for `ci.yml`'s list alone. One PCRE construct in either list here matches
    NOTHING under the runner's GNU grep while Python's `re` and the local grep both accept it, so
    every portal commit would answer "nothing changed" with the fixture corpus still green.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If either list is empty, blank-lined, whitespaced or non-POSIX.
    """
    environment = _scope_step()["env"]
    for name in ("IMAGE_PATTERNS", "TASK_PATTERNS"):
        _assert_pattern_list_is_sane(
            [line for line in environment[name].split("\n") if line.strip()], name
        )


def test_every_scope_pattern_and_glob_selects_something_in_the_corpus():
    """A per-entry positive control, because a set comparison cannot see an entry outside it.

    Both list-agreement tests compare *selections over the corpus*, so an entry matching nothing
    in it is invisible to them — and adding a path to one list and not the other is exactly the
    operation both workflow comments instruct. This is what forces a new corpus row when a list
    grows: the addition selects nothing, and this fails.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If any pattern or glob selects no corpus path.
    """
    environment = _scope_step()["env"]
    for name in ("IMAGE_PATTERNS", "TASK_PATTERNS"):
        for pattern in (line for line in environment[name].split("\n") if line.strip()):
            assert _selected_by_regexes(pattern), (
                f"`{pattern}` in {name} selects nothing in SCOPE_CORPUS, so neither list-agreement "
                "test can see it. Add a path it selects to the corpus."
            )

    gate = yaml.safe_load(SPA_IMAGE_WORKFLOW.read_text(encoding="utf-8"))
    for glob in gate[True]["pull_request"]["paths"]:
        assert _selected_by_globs([glob]), (
            f"`{glob}` in spa-image.yml's `paths:` selects nothing in SCOPE_CORPUS. Add a path it "
            "selects to the corpus, or the deploy's list can silently stop covering it."
        )


def test_a_revision_the_service_never_settled_on_is_re_pointed_rather_than_skipped():
    """What the service was POINTED at is not what landed, and the difference is a silent hole.

    The circuit breaker runs with rollback disabled — deliberately, so a bad image fails the
    workflow — which means a failed rollout leaves PRIMARY on the revision that failed and
    `describe-services` reports it as the service's task definition. Diffing against it would
    make the failed deploy permanent: the re-run finds no change and reports green over the
    bundle from before it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If an unsettled service is treated as a settled baseline.
    """
    for label, fixture in (
        ("a failed rollout", {"rollout": "FAILED"}),
        ("a rollout still in flight", {"rollout": "IN_PROGRESS"}),
        ("tasks that never started", {"running": 0}),
        ("a service scaled to nothing", {"desired": 0, "running": 0}),
    ):
        answers = _run_scope(("docs/architecture.md",), **fixture)
        assert answers["deploy"] == "run", (
            f"{label} was treated as a settled deployment"
        )
        assert answers["tag"] == answers["baseline"], (
            f"{label} must be re-pointed at the running image, not rebuilt from this commit"
        )


def test_a_failing_describe_services_builds_and_deploys():
    """The read itself erroring leaves no baseline, which must not read as "nothing changed".

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If an AWS failure resolves to a skip.
    """
    answers = _run_scope(("docs/architecture.md",), service_call="fails")
    assert (answers["build"], answers["deploy"]) == ("run", "run")


def test_a_non_ascii_path_is_not_quoted_out_of_the_change_set():
    """`git diff --name-only` quotes a non-ASCII path, and a quoted path matches no anchor.

    Left alone, `"apps/portal/src/caf\\303\\251.tsx"` — leading double quote, escaped bytes —
    fails `^apps/portal/`, so a file that genuinely changes the bundle answers "nothing changed".

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a non-ASCII portal path fails to trigger a build.
    """
    answers = _run_scope(("apps/portal/src/café.tsx",))
    assert (answers["build"], answers["deploy"]) == ("run", "run"), (
        "a non-ASCII path was quoted out of the change set; the diff needs -z"
    )


def test_a_pattern_list_grep_cannot_compile_stops_the_run_rather_than_skipping():
    """`grep` answers three ways and an `if` collapses two of them.

    0 matched, 1 did not, anything above that is grep failing to perform the test at all. Written
    as a bare `if`, the third reads as "nothing changed" — so a list the runner's grep refuses
    would skip every deploy, silently and in the cheap direction. The fixture uses an unbalanced
    bracket rather than a PCRE construct because every grep refuses that one; the PCRE case is
    caught textually instead, since the local engine accepts what the runner's rejects.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If an uncompilable list resolves to an answer rather than a refusal.
    """
    answers = _run_scope(
        ("apps/portal/src/App.tsx",),
        image_patterns="^apps/portal[/",
        expect_failure=True,
    )
    assert "::error title=Scope::" in answers["stdout"], (
        "the step refused, but not with the message that names the pattern list as the cause"
    )


def test_a_configuration_change_already_deployed_does_not_wait_forever():
    """The task list is about THIS push; the image change set does not advance when a run re-points.

    Tested against the image change set, one merge touching `infra/main.tf` goes on matching for
    every merge after it until the next commit that builds — each run waiting on an apply that
    cannot concern it. Measured when the list still re-pointed: 11 of 15 re-points were that.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a configuration change from an earlier, already-deployed merge keeps
            holding later runs.
    """
    stale = _run_scope(("docs/architecture.md",), intermediate=("infra/main.tf",))
    assert stale["polls"] == 0, (
        "a configuration change from an earlier merge still holds this run for an apply; the task "
        "list is being tested against the image baseline rather than against this push"
    )
    assert (stale["build"], stale["deploy"]) == ("skip", "skip")

    # The control: the same change, in THIS commit, still waits. Without it the assertion above
    # passes just as well on a task list that matches nothing at all.
    fresh = _run_scope(("infra/main.tf",), intermediate=("docs/architecture.md",))
    assert fresh["polls"] == 2


def test_no_shape_of_quoted_path_can_fall_out_of_the_change_set():
    """`--name-only` C-quotes more than high bytes, and every quoted path fails an anchor.

    `core.quotePath=false` covers bytes >= 0x80 alone and leaves `"`, `\\` and control characters
    still wrapped in quotes — the same silent-stale-bundle outcome for a different character.
    `-z` emits every path raw, which closes the class rather than one member of it.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If any quoted shape falls out of the change set.
    """
    for name in (
        "apps/portal/src/café.tsx",
        'apps/portal/src/a"b.tsx',
        "apps/portal/src/back\\slash.tsx",
    ):
        answers = _run_scope((name,))
        assert (answers["build"], answers["deploy"]) == ("run", "run"), (
            f"[{name}] was quoted out of the change set; the diff needs -z"
        )


def test_an_unreadable_newest_revision_says_so_rather_than_killing_the_step():
    """The one read that used to kill the step, with no annotation, only on the cheap path.

    The verdict is not what this branch buys — an empty `newest_arn` reaches `deploy=run` through
    the comparison below it either way. What it buys is the operator's message: without it the run
    either dies from a step whose name explains nothing, or announces that "the newest revision is
    " and blames a revision mismatch for an API failure. So the message is what is asserted.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a failed revision read reds the run, or is reported as something else.
    """
    answers = _run_scope(("docs/architecture.md",), newest_call="fails")
    assert (answers["build"], answers["deploy"]) == ("skip", "run")
    assert answers["tag"] == answers["baseline"]
    assert "::warning title=Unreadable::" in answers["stdout"], (
        "a failed revision read is reported as a revision mismatch, which sends an operator "
        "looking for a Terraform apply that never happened"
    )


def test_the_skip_path_prints_the_change_set_it_decided_over():
    """A verdict with no evidence makes an incomplete pattern list undiagnosable from the log.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the skipped run does not name the paths it dismissed.
    """
    answers = _run_scope(("docs/architecture.md", "lambdas/api/router.py"))
    assert answers["build"] == "skip"
    assert "docs/architecture.md" in answers["stdout"], (
        "the skip path does not print the change set, so a real bundle change dismissed by an "
        "incomplete pattern list leaves nothing in the log to diagnose it with"
    )


def test_a_truncated_change_set_says_how_much_it_dropped():
    """A silent cap reads as "these were all of them", which is the diagnosis going wrong quietly.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the printed change set is truncated without saying so.
    """
    # PAST THE PIPE BUFFER, deliberately. At 65 paths this fixture was three orders of magnitude
    # under 64 KiB and green on a size at which the failure it names cannot happen: printing the
    # change set through `printf | head` takes SIGPIPE once it is large enough, `pipefail` reports
    # 141, and the step dies before emitting an answer at all — a red main on a merge whose whole
    # point was to be a no-op. Measured on ubuntu at ~3000 paths, on macOS at ~4000.
    answers = _run_scope(tuple(f"docs/note-{index:04d}.md" for index in range(5000)))
    assert answers["build"] == "skip", (
        "the step lost its answer while printing the evidence for it"
    )
    assert "and 4940 more, not printed" in answers["stdout"], (
        "the change set was capped at 60 lines without saying what it dropped"
    )


def test_a_re_point_never_asks_the_registry_whether_to_build():
    """A failed registry read is not an absent image, and only HEAD may be built.

    The re-point paths answer `skip` by construction: they point at the image the service is
    already running, which therefore exists. Asking the registry instead would let a throttled
    read answer "absent" for a PREVIOUS commit's sha — and this run would then build the CURRENT
    tree, stamp it with that older sha and push it under that tag, which against an IMMUTABLE
    repository fails at the push blaming immutability rather than the throttle, and against one
    whose lifecycle had expired the image succeeds and leaves the tag naming a different tree.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a re-point schedules a build when the registry cannot be read.
    """
    for label, fixture in (
        ("an unreadable newest revision", {"newest_call": "fails"}),
        ("an unsettled deployment", {"rollout": "FAILED"}),
        (
            "a revision this push's apply registered",
            {"changed": ("infra/main.tf",), "apply_registers": True},
        ),
    ):
        changed = fixture.pop("changed", ("docs/architecture.md",))
        answers = _run_scope(changed, ecr_call="fails", **fixture)
        assert (answers["build"], answers["deploy"]) == ("skip", "run"), (
            f"{label} with an unreadable registry scheduled a build"
        )
        assert answers["tag"] == answers["baseline"]


# ── The scripts above are run on a machine, and the machine is shared ────────────────────────
#
# The guards below hold one defect class, found as a flake: a scratch file named in the script
# rather than created privately is ONE file for every run of the suite at once, and the wrong
# verdict it produces is silent. The reasoning is in the Key Decisions register, under gates and
# tests, in the entry on what the guards over a change-detection gate owe.


#: Directories every process on the machine may write, and therefore every other run of this
#: suite. A fixed path under one of them is not a defect in CI, where a runner is ephemeral and
#: holds a single job; it is a defect here, because these scripts are executed verbatim by the
#: harnesses above.
SHARED_TEMPORARY_ROOTS = ("/tmp/", "/private/tmp/", "/var/tmp/", "/dev/shm/")  # noqa: S108

#: The workflows whose ``run:`` scripts this module EXECUTES rather than merely reads — the
#: population the rule below is about. ``security.yml`` is parsed here and never run.
#: ``deploy-infra.yml`` is not run either, and its two temp files travel BETWEEN steps, where a
#: private file per step would be wrong and ``RUNNER_TEMP`` is the answer instead.
EXECUTED_WORKFLOWS = (CI_WORKFLOW, DEPLOY_SPA_WORKFLOW)

#: The standalone shell scripts the ``lambdas/`` suite EXECUTES, subject to the same rule for the
#: same reason — ``test_probe_cold_start.py``, ``test_point_lambda.py`` and
#: ``test_resolve_config.py`` run these three as scripts, and the first is where this defect was
#: found a second time. Named rather than globbed over ``.github/scripts/`` because the criterion
#: is execution BY THIS SUITE, which a directory cannot express: ``spa-image-matrix.sh`` holds a
#: dozen fixed ``/tmp/matrix-*`` names that are the same defect on the host, but no test runs it,
#: so it cannot flake this gate and fixing it is its own change. Every other ``.sh`` a suite module
#: names — the two image matrices, the container entrypoint — is read as TEXT, never run. Each path
#: is asserted to exist, so a rename empties the population loudly rather than quietly.
EXECUTED_SCRIPTS = (
    ROOT / ".github" / "scripts" / "probe-cold-start.sh",
    ROOT / ".github" / "scripts" / "point-lambda.sh",
    ROOT / ".github" / "scripts" / "resolve-config.sh",
)


def _shared_temporary_paths(script: str) -> list[str]:
    """Return the lines of a shell script that NAME a path under a shared temporary directory.

    Full-line comments are exempt for the only reason that matters: a comment cannot open a file,
    so flagging one would be a gate demanding a change that fixes nothing. Nothing else is exempt,
    including a trailing comment — over-strict there costs a reword and buys one less place to
    hide a write. No swept file relies on the exemption today; it is there so that explaining a
    fixed path stays possible.

    Args:
        script: A step's ``run:`` body.

    Returns:
        list[str]: The offending lines, stripped, in file order.

    Raises:
        None.
    """
    return [
        line.strip()
        for line in script.splitlines()
        if not line.lstrip().startswith("#")
        and any(root in line for root in SHARED_TEMPORARY_ROOTS)
    ]


def test_the_shared_temporary_path_sweep_reports_a_write_and_stays_quiet_otherwise():
    """The sweep below is a gate, so its own checks are exercised rather than trusted.

    Running a gate against the artifact it guards proves the artifact passes, not that the gate
    works — and half of a gate's regressions are false positives, so the silent cases are asserted
    as deliberately as the loud ones.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the sweep stops seeing a fixed shared path, or starts seeing something
            that is not one.
    """
    caught = (
        ("a redirect", "aws ecs describe-services > /tmp/scope-service.json"),
        ("a read", "jq -r .desiredCount /tmp/scope-service.json"),
        ("the resolved form of the same directory", "cat /private/tmp/service.json"),
        ("the other shared root", "printf x > /var/tmp/plan.json"),
        ("shared memory, which a runner has and this Mac does not", "cat /dev/shm/out.json"),
        ("a trailing comment on a live line", "cat x  # was /tmp/service.json"),
    )
    for label, script in caught:
        assert _shared_temporary_paths(script) == [script.strip()], (
            f"the sweep no longer reports {label}, which is the shape that flaked"
        )

    quiet = (
        (
            "a private file",
            'service_json=$(mktemp)\njq -r .desiredCount "$service_json"',
        ),
        ("the runner's own scratch directory", 'cat "$RUNNER_TEMP/plan.json"'),
        (
            "a full-line comment naming the path",
            "          # was /tmp/scope-service.json",
        ),
        ("a path that merely starts the same way", "cat /tmpfiles/service.json"),
    )
    for label, script in quiet:
        assert _shared_temporary_paths(script) == [], (
            f"the sweep reports {label}, which is not a shared fixed path — a gate that reddens "
            "on the correct form is how the correct form stops being written"
        )


def test_nothing_the_suite_executes_names_a_shared_temporary_path():
    """A script this suite runs must keep its scratch files to itself.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a step or script the suite executes names a fixed path under a
            directory the rest of the machine shares.
    """
    scripts: dict[str, str] = {}
    for script in EXECUTED_SCRIPTS:
        assert script.is_file(), (
            f"{script.relative_to(ROOT)} is gone or has moved, so the sweep below covers one "
            "script fewer than it says it does — re-point it rather than dropping it"
        )
        where = script.relative_to(ROOT).as_posix()
        scripts[where] = script.read_text(encoding="utf-8")
    for workflow in EXECUTED_WORKFLOWS:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_name, job in document["jobs"].items():
            for position, step in enumerate(job.get("steps", [])):
                if "run" in step:
                    name = step.get("name", step.get("id", f"step {position}"))
                    scripts[f"{workflow.name} / {job_name} / {name}"] = step["run"]

    # THE COLLECTOR IS PROVEN BEFORE AN ABSENCE IS ASSERTED OVER IT, once per workflow: a parse
    # that returned no scripts at all — a renamed job, a `run:` moved into a composite action —
    # would satisfy every assertion below while sweeping nothing.
    bodies = set(scripts.values())
    assert _ci_scope_step()["run"] in bodies, (
        "the sweep did not reach ci.yml's scope step, so its verdict is about some other set of "
        "scripts than the ones the harnesses run"
    )
    assert _scope_step()["run"] in bodies, (
        "the sweep did not reach deploy-spa-image.yml's scope step, so its verdict is about some "
        "other set of scripts than the ones the harnesses run"
    )

    offences = {
        where: lines
        for where, script in scripts.items()
        if (lines := _shared_temporary_paths(script))
    }
    assert not offences, (
        "something this suite executes names a fixed path under a directory every other process on "
        "the machine shares, which is one file for every run of the suite at once — two of them "
        "truncate and rewrite it, and the step reads the other one's fixture as its own answer. "
        "Create the file with `mktemp` instead:\n"
        + "\n".join(
            f"  {where}:\n" + "\n".join(f"    {line}" for line in lines)
            for where, lines in sorted(offences.items())
        )
    )


def test_concurrent_runs_of_the_scope_step_do_not_answer_each_other():
    """Two runs of the step at once must each get their own verdict.

    The sweep above is the deterministic half of this guard and catches the SPELLING; this is the
    behavioural half and catches the PROPERTY, which is the wider of the two. The sweep knows four
    directory names. Sharing does not need one: a fixed name under `$HOME`, a lock file, a port, a
    named pipe, a cache keyed on something two runs both compute the same way — each collides
    exactly as `/tmp/scope-service.json` did, and each is invisible to a matcher over paths.

    An unset `$RUNNER_TEMP` is NOT among them, though it reads like it should be. Every `run:`
    body in the workflow opens `set -euo pipefail`, and `-u` makes the first expansion of an unset
    variable abort the step — loudly, on the first run, rather than silently on an unlucky one.
    `${RUNNER_TEMP:-/tmp}` would be the dangerous spelling, and nothing here uses it.

    The two fixtures are chosen to CONTRADICT: one describes a service running the baseline, whose
    verdict is skip/skip against a commit that touches nothing the image reads, and one describes
    no service at all, whose verdict is build-and-deploy this commit. Sharing state between them
    turns each into the other, so a collision cannot be absorbed as a coincidence.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a run's verdict depends on what another run was doing.
    """
    touched = ("docs/architecture.md",)

    def settled() -> None:
        answers = _run_scope(touched)
        assert (answers["build"], answers["deploy"]) == ("skip", "skip"), (
            "a commit touching nothing the image reads was built while another run of the step "
            "was in flight; the two are sharing a file"
        )
        assert answers["tag"] == answers["baseline"]

    def absent() -> None:
        answers = _run_scope(touched, deployed="absent")
        assert (answers["build"], answers["deploy"]) == ("run", "run"), (
            "a service that does not exist was treated as a baseline while another run of the "
            "step was in flight; the two are sharing a file"
        )
        assert answers["tag"] == answers["head"]

    work = [settled, absent] * 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(work)) as pool:
        for future in concurrent.futures.as_completed(
            [pool.submit(one) for one in work]
        ):
            future.result()
