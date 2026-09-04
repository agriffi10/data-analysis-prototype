"""Two workflow guards whose failure would be SILENT rather than red.

Both hold a condition that was structural until it became textual, which is the point at
which a guard starts needing one of its own.

``ci.yml``'s ``ci`` job skips its lint, build and test steps when a pull request touches none
of the app's inputs. That set is not "the app's source": the suite reads 93 files from OUTSIDE
``apps/portal/`` through ``?raw`` and ``import.meta.glob`` — all 88 IAM policy templates among
them, reached by one glob — in order to assert that the browser agrees with the infrastructure
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
is a weak control here, because 88 of the reads arrive through a single glob and would mask the
disappearance of any individual one. The five that do not come from that glob are named.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

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
)

#: Paths the list must NOT select, or the saving is gone. Each is a near miss of a real pattern
#: rather than an obvious non-match, so an over-broad or unanchored pattern is caught.
REFUSED_BY_SCOPE = (
    "docs/process.md",
    "CLAUDE.md",
    "lambdas/api/routes/objects.py",
    "lambdas/archive-common/arcommon/registry.py",
    "infra/modules/data/main.tf",
    "infra/variables.tf",
)

#: The floor for the glob-derived half. 88 templates exist; a lower bound lets one be added or
#: removed without editing this file, while still failing if the glob stops being swept at all.
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
        f"the sweep found only {len(templates)} IAM policy templates; there are 88 and the glob "
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


def _run_ci_scope(changed: tuple[str, ...]) -> dict[str, str]:
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

    Returns:
        dict[str, str]: The step's ``$GITHUB_OUTPUT`` — ``app`` — plus its ``stdout``, which
            carries the annotations that say WHY it answered as it did.

    Raises:
        AssertionError: If the step exits non-zero, with its output attached.
    """
    step = _ci_scope_step()
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        repo = root / "repo"
        repo.mkdir()

        git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)  # noqa: S603
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], check=True)  # noqa: S603
        subprocess.run([*git, "commit", "-qm", "base"], check=True)  # noqa: S603
        base = subprocess.run(  # noqa: S603
            [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()

        for name in changed:
            written = repo / name
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_text("under test\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], check=True)  # noqa: S603
        subprocess.run([*git, "commit", "-qm", "under test"], check=True)  # noqa: S603

        output = root / "output.txt"
        output.touch()
        script = root / "scope.sh"
        script.write_text(step["run"], encoding="utf-8")
        bash = shutil.which("bash")
        assert bash, (
            "no bash on PATH; the scope step is a bash script and cannot be exercised without one"
        )
        finished = subprocess.run(  # noqa: S603
            [bash, str(script)],
            cwd=repo,
            env={
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "BASE": base,
                "SCOPE_PATTERNS": step["env"]["SCOPE_PATTERNS"],
            },
            capture_output=True,
            text=True,
        )
        assert finished.returncode == 0, (
            f"the scope step failed:\n{finished.stdout}\n{finished.stderr}"
        )

        answers = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        answers["stdout"] = finished.stdout
        return answers


def test_the_pull_request_scope_step_answers_both_ways_over_a_real_repository():
    """The positive control, without which every assertion below can pass vacuously.

    A harness that answered ``app=true`` unconditionally — an unreachable base is one way, and
    the step takes that branch by design — would satisfy every quoted-path case here while
    proving nothing. So the pair is asserted together: a documentation-only commit skips, an
    ordinary portal source builds, and neither reaches the unreachable-base escape, which is
    what the annotation discriminates.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If either verdict is wrong, or if a verdict came from the fallback.
    """
    skipped = _run_ci_scope(("docs/process.md",))
    assert skipped["app"] == "false", (
        "a documentation-only pull request ran the install, the build and the bundle check"
    )
    assert "no app input changed" in skipped["stdout"], (
        "the skip path did not say why it skipped"
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
    document = yaml.safe_load(DEPLOY_SPA_WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["deploy"]["steps"]
    scope = [step for step in steps if step.get("id") == "scope"]
    assert scope, "`deploy-spa-image.yml` has no step with id `scope`"
    return scope[0]


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
    the failure this comparison exists to catch.

    Args:
        globs: The workflow's ``paths:`` entries.

    Returns:
        set[str]: Every corpus path the list selects.

    Raises:
        AssertionError: If an entry uses a glob shape this matcher does not implement.
    """
    selected = set()
    for glob in globs:
        if glob.endswith("/**"):
            prefix = glob[: -len("**")]
            selected |= {path for path in SCOPE_CORPUS if path.startswith(prefix)}
        else:
            assert "*" not in glob and "?" not in glob, (
                f"`{glob}` is a glob shape this test does not implement; teach the matcher "
                "rather than letting it approximate"
            )
            selected |= {path for path in SCOPE_CORPUS if path == glob}
    return selected


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

    It exists for one race: Terraform registering a revision this workflow has not seen yet.
    Widening it to `infra/` would deploy on every infrastructure merge — 19 of the 40 measured —
    and buy nothing the revision comparison does not already catch once the apply has landed.

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


#: The stub `aws`. Every answer the scope step reads comes from the environment, so a fixture
#: describes a deployment rather than a sequence of calls. The two `describe-task-definition`
#: calls are told apart by their `--query`, which is the only thing that differs between asking
#: what the service RUNS and asking what the family's newest revision IS.
FAKE_AWS = """#!/usr/bin/env python3
import os, sys

argv = sys.argv[1:]
if argv[:2] == ["ecs", "describe-services"]:
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
    else:
        print(os.environ["FAKE_NEWEST_ARN"])
elif argv[:2] == ["ecr", "describe-images"]:
    # A FAILED CALL IS NOT AN ABSENT IMAGE, and modelling only exit 0 and exit 254 is how that
    # difference stays invisible: a throttle and a missing tag look identical to a bare `else`.
    if os.environ["FAKE_ECR_CALL"] == "fails":
        sys.exit(255)
    tag = [a for a in argv if a.startswith("imageTag=")][0].split("=", 1)[1]
    sys.exit(0 if tag in os.environ["FAKE_EXISTING_TAGS"].split(",") else 254)
else:
    sys.exit(2)
"""


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
) -> dict[str, str]:
    """Run the workflow's real scope script over a throwaway repository and stubbed AWS.

    Args:
        changed: Repository-relative paths the commit under test touches.
        intermediate: Paths touched by a commit BETWEEN the deployed one and the one under test —
            a merge that was already deployed, or one whose run only re-pointed.
        deployed: What the service is running — ``baseline`` for the previous commit, ``absent``
            for no service at all, ``placeholder`` for the pre-first-deploy image, or
            ``unreachable`` for a sha this clone does not hold.
        newest_is_running: False when Terraform has registered a revision nobody has pointed at.
        existing_tags: Tags the registry already holds, which is how a re-run is described. The
            literal ``HEAD`` stands for this commit's sha, which the caller cannot know in advance.
        dispatched: True to exercise the manual recovery lever.
        tag_input: The dispatch's ``image_tag`` input.
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
        dict[str, str]: The step's ``$GITHUB_OUTPUT`` — ``tag``, ``build`` and ``deploy``.

    Raises:
        AssertionError: If the script exits non-zero, with its output attached.
    """
    step = _scope_step()
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        repo, binaries = root / "repo", root / "bin"
        repo.mkdir()
        binaries.mkdir()

        stub = binaries / "aws"
        stub.write_text(FAKE_AWS, encoding="utf-8")
        stub.chmod(0o755)

        git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)  # noqa: S603
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], check=True)  # noqa: S603
        subprocess.run([*git, "commit", "-qm", "baseline"], check=True)  # noqa: S603
        baseline = subprocess.run(  # noqa: S603
            [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()

        def commit(paths: tuple[str, ...], message: str) -> None:
            for name in paths:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"{message}\n", encoding="utf-8")
            subprocess.run([*git, "add", "-A"], check=True)  # noqa: S603
            subprocess.run([*git, "commit", "-qm", message], check=True)  # noqa: S603

        if intermediate:
            commit(intermediate, "already deployed")
        commit(changed, "under test")
        head = subprocess.run(  # noqa: S603
            [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
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

        output = root / "output.txt"
        output.touch()
        environment = {
            **os.environ,
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_SHA": head,
            "NAME": "dat-prod-spa",
            "CLUSTER": "dat-prod-spa",
            "SERVICE": "dat-prod-spa",
            "TAG_INPUT": tag_input,
            "DISPATCHED": "true" if dispatched else "false",
            "IMAGE_PATTERNS": step["env"]["IMAGE_PATTERNS"]
            if image_patterns is None
            else image_patterns,
            "TASK_PATTERNS": step["env"]["TASK_PATTERNS"],
            "FAKE_SERVICE_JSON": service,
            "FAKE_SERVICE_CALL": service_call,
            "FAKE_NEWEST_CALL": newest_call,
            "FAKE_ECR_CALL": ecr_call,
            "FAKE_RUNNING_IMAGE": image,
            "FAKE_NEWEST_ARN": running_arn
            if newest_is_running
            else "arn:aws:ecs:::task-definition/dat-prod-spa:8",
            # THE BASELINE'S OWN TAG IS ALWAYS PRESENT when the service is running it, because a
            # service cannot run an image the registry does not hold. Leaving it out models a
            # registry that contradicts the deployment, and every re-point fixture would then
            # assert a rebuild that production would never do.
            "FAKE_EXISTING_TAGS": ",".join(
                [head if tag == "HEAD" else tag for tag in existing_tags]
                + ([baseline] if deployed == "baseline" else [])
            ),
        }

        script = root / "scope.sh"
        script.write_text(step["run"], encoding="utf-8")
        bash = shutil.which("bash")
        assert bash, (
            "no bash on PATH; the scope step is a bash script and cannot be exercised without one"
        )
        finished = subprocess.run(  # noqa: S603
            [bash, str(script)],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
        )
        if expect_failure:
            assert finished.returncode != 0, (
                f"the scope step was expected to refuse and did not:\n{finished.stdout}"
            )
            return {"stdout": finished.stdout, "baseline": baseline, "head": head}
        assert finished.returncode == 0, (
            f"the scope step failed:\n{finished.stdout}\n{finished.stderr}"
        )

        answers = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        answers["baseline"] = baseline
        answers["head"] = head
        answers["stdout"] = finished.stdout
        return answers


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


def test_a_runtime_configuration_change_points_the_service_without_rebuilding():
    """Terraform's own revisions are the case a `paths:` filter on the image cannot see.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the service is left pointing at a revision Terraform superseded.
    """
    answers = _run_scope(("infra/main.tf",))
    assert (answers["build"], answers["deploy"]) == ("skip", "run")
    assert answers["tag"] == answers["baseline"], (
        "re-pointing must reuse the running image, not build a new one"
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


def test_a_dispatch_never_skips_the_deploy():
    """The recovery lever is reached for when this step's own reasoning is what is wrong.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a manual run can decide it has nothing to do.
    """
    answers = _run_scope(("docs/architecture.md",), dispatched=True)
    assert answers["deploy"] == "run"
    assert answers["tag"] == answers["head"]


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
        "a non-ASCII path was quoted out of the change set; the diff needs core.quotePath=false"
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


def test_a_configuration_change_already_deployed_does_not_re_point_forever():
    """The task list is about THIS push; the image change set does not advance when a run re-points.

    Tested against the image change set, one merge touching `infra/main.tf` goes on matching for
    every merge after it — registering a revision and rolling the production tasks, having changed
    nothing, until the next commit that builds. Measured before the fix: 11 of 15 re-points.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a configuration change from an earlier, already-deployed merge keeps
            triggering deploys.
    """
    stale = _run_scope(("docs/architecture.md",), intermediate=("infra/main.tf",))
    assert (stale["build"], stale["deploy"]) == ("skip", "skip"), (
        "a configuration change from an earlier merge is still being re-deployed; the task list "
        "is being tested against the image baseline rather than against this push"
    )

    # The control: the same change, in THIS commit, still re-points. Without it the assertion
    # above passes just as well on a task list that matches nothing at all.
    fresh = _run_scope(("infra/main.tf",), intermediate=("docs/architecture.md",))
    assert (fresh["build"], fresh["deploy"]) == ("skip", "run")


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
        ("a configuration change in this push", {"changed": ("infra/main.tf",)}),
    ):
        changed = fixture.pop("changed", ("docs/architecture.md",))
        answers = _run_scope(changed, ecr_call="fails", **fixture)
        assert (answers["build"], answers["deploy"]) == ("skip", "run"), (
            f"{label} with an unreadable registry scheduled a build"
        )
        assert answers["tag"] == answers["baseline"]
