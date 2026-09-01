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

The sweep covers every ``.ts``/``.tsx`` under ``src/``, not only ``*.test.ts``. A coupled read
moved one file sideways into a ``src/test/`` helper is the shape this repository already uses
— ``cssTokens.ts`` reads from disk — and a test-file-only sweep is blind to it while looking
exactly as green.

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

import os
import pathlib
import re

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
PATH_SPECIFIER = re.compile(r"""['"]([./][A-Za-z0-9_.*/-]*/[A-Za-z0-9_.*/-]+?)(\?[a-z]+)?['"]""")

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
#: counted. A floor cannot protect these: 88 of the 93 reads come from that one glob, so any of
#: these five could stop being swept while the total still cleared any plausible threshold.
NAMED_OUT_OF_TREE_READS = frozenset(
    {
        ".github/workflows/deploy-app.yml",
        "config/feature-flags.json",
        "infra/main.tf",
        "lambdas/api/routes/feature_flags.py",
        "lambdas/archive-common/arcommon/config.py",
    }
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
    steps = [step for step in document["jobs"]["ci"]["steps"] if step.get("id") == "scope"]
    assert steps, "ci.yml no longer has a step with `id: scope` — the scoping guard reads that step"
    return steps[0]["env"]["SCOPE_PATTERNS"].splitlines()


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
    for source in [*PORTAL_SRC.rglob("*.ts"), *PORTAL_SRC.rglob("*.tsx")]:
        for specifier, _query in PATH_SPECIFIER.findall(source.read_text(encoding="utf-8")):
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
    uncovered = sorted(path for path in reads if not any(pattern.search(path) for pattern in patterns))

    assert not uncovered, (
        "the portal suite reads these files from outside apps/portal, and ci.yml's SCOPE_PATTERNS "
        f"does not cover them, so a pull request changing one skips the suite and reports green: {uncovered}"
    )


def test_no_scope_pattern_matches_every_path():
    """``grep -f`` reads a blank line as a pattern matching everything.

    One stray empty line in the block scalar makes the scope step answer ``app=true`` for every
    pull request — the whole saving gone, silently and in the expensive direction, with the
    coverage test above still green because a blank pattern covers all of its paths.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If a pattern is blank, holds whitespace, or matches an unrelated path.
    """
    patterns = _scope_patterns()

    assert patterns, "SCOPE_PATTERNS is empty; the scope step would skip every pull request"

    blank = [index for index, pattern in enumerate(patterns) if not pattern.strip()]
    assert not blank, (
        f"SCOPE_PATTERNS has a blank line at index {blank}; `grep -f` reads it as a "
        "match-everything pattern and the scoping stops scoping"
    )

    spaced = [pattern for pattern in patterns if " " in pattern.strip()]
    assert not spaced, f"these patterns contain whitespace and would not mean what they look like: {spaced}"

    unrelated = "docs/process.md"
    matching = [pattern for pattern in patterns if re.search(pattern, unrelated)]
    assert not matching, (
        f"these patterns match {unrelated}, so a documentation-only pull request would still run "
        f"the full suite: {matching}"
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

    assert "Validate every gate value" in names, "scan no longer validates the gate values"

    gated = [index for index, step in enumerate(steps) if step.get("name") not in UNGATED_SCAN_STEPS]
    assert gated, (
        "no gated steps found in `scan`; the step list has stopped parsing, or every step is now "
        "named in UNGATED_SCAN_STEPS, and this test is asserting nothing"
    )
    assert names.index("Validate every gate value") < min(
        gated
    ), "the gate validation must come before every step that depends on it"

    missing = sorted(names[index] for index in gated if steps[index].get("if") != GATE_CONDITION)
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
        validation = [s for s in document["jobs"][job]["steps"] if s.get("name") == "Validate every gate value"]
        assert validation, f"`{job}` no longer validates the gate values"
        assert "continue-on-error" not in validation[0], (
            f"`{job}`'s gate validation tolerates its own failure; every scanner would skip on "
            "`outcome` while the job concluded green"
        )
