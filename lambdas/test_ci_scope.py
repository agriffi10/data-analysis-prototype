"""Two workflow guards whose failure would be SILENT rather than red.

Both hold a condition that was structural until it became textual, which is the point at
which a guard starts needing one of its own.

``ci.yml``'s ``ci`` job skips its lint, build and test steps when a pull request touches
none of the app's inputs. That set is not "the app's source": the suite reads 94 files from
OUTSIDE ``apps/portal/`` through ``?raw`` and ``import.meta.glob`` — every IAM policy
template among them — in order to assert that the browser agrees with the infrastructure and
the planes. A read that is missing from the workflow's pattern list does not make the saving
smaller, it makes it dishonest: the coupled file changes, the guard that would have caught it
never runs, and the job is green. The first test sweeps for those reads rather than restating
them, so a new import cannot be added without the workflow learning about it.

``security.yml``'s scanners were ordered after gate validation by ``needs: gates`` while it
was a separate job. It is now a step, and the ordering is a string repeated on every scanner
step. YAML enforced the old form; nothing enforces the new one, so a scanner added without
the condition would run under a failed gate and report as if the gate had held.

The shape is ``test_security_gates.py``'s: assert the coupling, then assert the parse did not
go trivial. A sweep that finds nothing must fail rather than pass vacuously.
"""

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
PORTAL_SRC = ROOT / "apps" / "portal" / "src"

#: A quoted specifier that is path-shaped — it starts with ``.`` or ``/`` and contains a
#: separator. Deliberately NOT filtered by extension: the reads this sweep exists to find are
#: whatever the suite happens to reach for, and an extension allowlist is a second place to
#: forget one. A trailing Vite query (``?raw``) is stripped, and ``*`` is expanded, because
#: both forms are in use and a literal-path-only regex silently found half the set.
PATH_SPECIFIER = re.compile(r"""['"]([./][A-Za-z0-9_.*/-]*/[A-Za-z0-9_.*/-]+?)(\?[a-z]+)?['"]""")

#: The condition every scanner step in ``scan`` must carry now that gate validation is a step.
GATE_CONDITION = "always() && steps.gates.outcome == 'success'"

#: Steps in ``scan`` that are deliberately NOT gated: the checkout that fetches the script,
#: the validation itself, and the toolchain setup. None is a scanner, and each runs under the
#: default ``success()`` — which a failed validation already skips.
UNGATED_SCAN_STEPS = frozenset(
    {
        "Checkout",
        "Validate every gate value",
        "Record the gate configuration in the summary",
        "Set up Python",
        "Set up Node.js",
    }
)

#: The floor the sweep below must clear. 94 out-of-tree reads exist today — 89 of them IAM
#: templates reached by one glob. A lower bound lets one be added without editing this file, while
#: still failing if the specifier regex stops matching after a reformat.
MINIMUM_OUT_OF_TREE_READS = 90


def _scope_patterns() -> list[str]:
    """Read the ``ci`` job's scope pattern list out of the workflow.

    Taken from the step's ``env`` rather than from its shell body, so the test reads the same
    string the step passes to ``grep -f`` instead of a copy that can drift from it.

    Args:
        None.

    Returns:
        One compiled-shape pattern per line, in workflow order.

    Raises:
        AssertionError: If the workflow holds no step with ``id: scope``.
    """
    document = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = [step for step in document["jobs"]["ci"]["steps"] if step.get("id") == "scope"]
    assert steps, "ci.yml no longer has a step with `id: scope` — the scoping guard reads that step"
    return steps[0]["env"]["SCOPE_PATTERNS"].split()


def _out_of_tree_reads() -> set[str]:
    """Sweep the portal suite for files it reads from outside ``apps/portal/``.

    Each specifier is reduced to a repository-relative tail by dropping the leading ``/`` and
    every ``../`` — the bundler's own resolution differs between a relative import and a
    root-anchored ``import.meta.glob``, and what this sweep needs is only which repository
    paths are NAMED. A tail that does not exist at the repository root is an in-tree import
    and is dropped; one containing ``*`` is expanded against the root.

    Args:
        None.

    Returns:
        Repository-relative paths the suite reads from outside ``apps/portal/``.

    Raises:
        None.
    """
    portal = PORTAL_SRC.parent
    found: set[str] = set()
    for test in [*PORTAL_SRC.rglob("*.test.ts"), *PORTAL_SRC.rglob("*.test.tsx")]:
        for specifier, _query in PATH_SPECIFIER.findall(test.read_text(encoding="utf-8")):
            tail = re.sub(r"^(?:/|\.\./|\./)+", "", specifier)
            if not tail:
                continue
            targets = sorted(ROOT.glob(tail)) if "*" in tail else [ROOT / tail]
            for target in targets:
                if not target.is_file() or portal in target.parents:
                    continue
                found.add(target.relative_to(ROOT).as_posix())
    return found


def test_every_file_the_suite_reads_from_outside_the_portal_is_in_ci_scope():
    """A coupled file outside ``apps/portal/`` must re-run the suite that asserts the coupling.

    The failure this holds off is silent: the file changes, the set-equality assertion that
    would have caught it is skipped, and the job reports green. Two were reproduced by
    planting — ``arcommon/config.py`` and ``infra/main.tf`` — before the list covered them.

    Args:
        None.

    Returns:
        None.

    Raises:
        AssertionError: If the sweep goes trivial, or a swept path matches no scope pattern.
    """
    reads = _out_of_tree_reads()

    assert len(reads) >= MINIMUM_OUT_OF_TREE_READS, (
        f"the sweep found only {len(reads)} out-of-tree reads ({sorted(reads)}); it found "
        f"{MINIMUM_OUT_OF_TREE_READS} when written, so the specifier regex has stopped matching "
        "and this test is now asserting nothing"
    )

    patterns = [re.compile(pattern) for pattern in _scope_patterns()]
    uncovered = sorted(path for path in reads if not any(pattern.search(path) for pattern in patterns))

    assert not uncovered, (
        "the portal suite reads these files from outside apps/portal, and ci.yml's SCOPE_PATTERNS "
        f"does not cover them, so a pull request changing one skips the suite and reports green: {uncovered}"
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
        AssertionError: If ``scan`` holds no scanner steps, if the validation step is not first
            among the gated ones, or if a scanner step is missing the condition.
    """
    document = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["scan"]["steps"]
    names = [step.get("name", "") for step in steps]

    assert "Validate every gate value" in names, "scan no longer validates the gate values"
    assert names.index("Validate every gate value") < min(
        index for index, step in enumerate(steps) if step.get("name") not in UNGATED_SCAN_STEPS
    ), "the gate validation must come before every step that depends on it"

    scanner_steps = [step for step in steps if step.get("name") not in UNGATED_SCAN_STEPS]

    assert len(scanner_steps) >= 20, (
        f"only {len(scanner_steps)} scanner steps found in `scan`; there were 27 when this was "
        "written, so the step list has stopped parsing and this test is asserting nothing"
    )

    missing = sorted(step.get("name", "") for step in scanner_steps if step.get("if") != GATE_CONDITION)

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
