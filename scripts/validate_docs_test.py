"""The fixture corpus for ``validate_docs.py``.

Why this exists. ``validate_docs.py`` runs fifteen checks on every pull request, and until this
file it had no test of any kind. Running it against this repo's own documents proves those
documents pass; it proves nothing about whether any of the fifteen still fires. A gate whose
checks have gone quiet is indistinguishable from a healthy repo — the green run looks the same
either way — and this is the gate the whole doc discipline rests on.

How it works, and why not pytest. ``ROOT`` in ``validate_docs.py`` is derived from ``__file__``,
so a COPY of the script inside a fixture tree validates that tree. Nothing about the gate has to
change to be testable, and in particular no environment override is added: a budget a caller can
redirect is a budget CI can be told to ignore. ``pytest`` is not used because this repo's pytest
run is ``pytest lambdas/`` with a coverage floor scoped to the Lambda fleet; a scripts-level test
would either not run or fight that configuration. This runs as its own CI step beside the
validator it tests.

Each case asserts the specific FAILURE TEXT, not just the exit code. A check that fails for the
wrong reason gets "fixed" by changing the wrong thing, and several of the checks here return the
same exit code for very different problems. Cases whose name ends ``_ok`` assert SILENCE: a
corpus of only-failures cannot see a false positive, and a check that fires on everything passes
a failures-only corpus perfectly.

Usage: ``python3 scripts/validate_docs_test.py`` — takes no arguments, imports nothing outside
the standard library, and exits non-zero if any case does not behave as declared.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent


def build(root: pathlib.Path) -> None:
    """Write the smallest documentation tree that passes all fifteen checks.

    Every file here is load-bearing for at least one check, which is why the baseline is this
    large: the checks are cross-referential. The decisions register must be routed by its INDEX
    and its areas must match CLAUDE.md's digest headings; the workflows README must have a row
    per workflow; and ``check_doc_paths_everywhere`` reads the doc paths named in
    ``validate_docs.py``'s OWN docstrings, so those files have to exist here too.

    Args:
      root: An empty directory to build the fixture repository in.

    Returns:
      None.

    Raises:
      None.
    """
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "validate_docs.py", root / "scripts" / "validate_docs.py")
    for d in ("docs/testing", "docs/decisions", "docs/specs", "docs/spec-delivery",
              "apps/portal/info", "lambdas/info/planes", "infra/info", "infra/modules",
              ".github/workflows"):
        (root / d).mkdir(parents=True, exist_ok=True)

    (root / "README.md").write_text("# R\n")
    (root / "CLAUDE.md").write_text(
        "# P\n\n## Key Decisions (settled)\n\n### Area one\n\n- **Alpha** — fence.\n\n"
        "### Identity and access\n\n- **X** — fence.\n\n## Out of Scope\n\nx\n")
    (root / "docs" / "process.md").write_text("# Process\n")
    (root / "docs" / "reviewer-contract.md").write_text("# Reviewer contract\n")
    for name in ("e2e.md", "owed.md", "sessions.md"):
        (root / "docs" / "testing" / name).write_text("# t\n")
    (root / "docs" / "decisions" / "INDEX.md").write_text(
        "# Decisions\n\n- [Area one](area-one.md)\n- [Identity and access](identity-and-access.md)\n")
    (root / "docs" / "decisions" / "area-one.md").write_text(
        "# Area one\n\n## Contents\n\n- [Alpha](#alpha)\n\n## Alpha\n\nR.\n")
    (root / "docs" / "decisions" / "identity-and-access.md").write_text(
        "# Identity and access\n\n## Contents\n\n- [X](#x)\n\n## X\n\nR.\n")
    (root / "docs" / "specs" / "INDEX.md").write_text("# Index\n")
    (root / "docs" / "specs" / "ARCS.md").write_text("# Arcs\n")
    (root / "lambdas" / "info" / "planes" / "api.md").write_text("# API plane\n")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n")
    (root / ".github" / "workflows" / "README.md").write_text(
        "# Workflows\n\n| File | Trigger | Purpose |\n|---|---|---|\n| `ci.yml` | PR | the one workflow |\n")


def run(root: pathlib.Path) -> tuple[int, str]:
    """Run the copied validator against its own fixture tree.

    Args:
      root: The fixture repository built by :func:`build`.

    Returns:
      The exit code and the combined stdout/stderr.

    Raises:
      None.
    """
    # The S603 suppression below is justified rather than blanket: both operands are ours —
    # `sys.executable` is this interpreter, and the script path was written by `build()` moments
    # earlier from a copy of a file in this repo. No part of it comes from input.
    p = subprocess.run(  # noqa: S603
        [sys.executable, str(root / "scripts" / "validate_docs.py")],
        capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# Each case is (name, mutate, want_exit, want_text). `mutate` receives the built fixture root and
# breaks exactly one thing. A name ending `_ok` asserts the validator stays SILENT, and its
# want_text is ignored — those cases exist because half of what a gate gets wrong is firing on
# something legitimate, which a corpus of only-failures cannot see.
# Fixture paths are ASSEMBLED, never written as literals. `check_doc_paths_everywhere` scans every
# `.py` in the repo for documentation-path references and refuses any that do not resolve — and a
# fixture
# corpus is made of paths that deliberately do not exist here. Exempting this file from that check
# was the other option and the worse one: an exemption is a hole someone later widens. Assembling
# the path states no claim for the checker to refuse, and costs one helper.
def D(*parts: str) -> str:
    """Join a fixture-relative documentation path without writing it as a literal."""
    return "/".join(("docs", *parts))


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _spec(n, frs):
    body = "\n".join(f"### FR-{i:03d} A requirement\n\nText.\n" for i in range(1, frs + 1))
    return f"# SPEC-{n:03d}: Thing\n\nStatus: Draft\n\n## Functional Requirements\n\n{body}"


CASES = [
    # ---- check_testing_layout -------------------------------------------------------------
    ("testing_stray_file",
     lambda r: _write(r, D("testing", "notes-from-tuesday.md"), "# notes\n"),
     1, "docs/testing/"),
    ("testing_inflight_e2e_ok",
     lambda r: _write(r, D("testing", "arc-b-e2e.md"), "# in-flight arc script\n"),
     0, ""),

    # ---- check_fixture_scripts ------------------------------------------------------------
    ("fixture_scripts_second",
     lambda r: [_write(r, D("testing", "fixtures", "plane-a.sh"), "#!/bin/sh\n"),
                _write(r, D("testing", "fixtures", "plane-b.sh"), "#!/bin/sh\n")],
     1, "fixtures"),

    # ---- check_claude_budget --------------------------------------------------------------
    ("claude_over_budget",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text() + "\nfiller " * 9000),
     1, "CLAUDE.md is"),
    ("digest_line_too_long",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text().replace(
         "- **Alpha** — fence.", "- **Alpha** — " + ("the reasoning has moved into the digest. " * 45))),
     1, "Key Decisions"),

    # ---- check_process_budget -------------------------------------------------------------
    ("process_over_budget",
     lambda r: _write(r, D("process.md"), "# Process\n" + ("filler line of prose. " * 2400)),
     1, "against a 40,000 budget"),

    # ---- check_decisions_register ---------------------------------------------------------
    ("register_entry_unlisted",
     lambda r: _write(r, D("decisions", "area-one.md"),
                      "# Area one\n\n## Contents\n\n- [Alpha](#alpha)\n\n## Alpha\n\nR.\n\n## Beta\n\nR.\n"),
     1, "Contents"),
    ("register_area_unrouted",
     lambda r: _write(r, D("decisions", "INDEX.md"), "# Decisions\n\n- [Area one](area-one.md)\n"),
     1, "not routed"),

    # ---- check_arcs -----------------------------------------------------------------------
    # The heading is LISTED deliberately. Without the list entry the fixture also trips the
    # "missing from the arc list" exit, and an assertion of "ARCS.md" matches either message —
    # so the case passed with the status-word rule disabled. One exit per case, asserted by its
    # own text, which is the rule four lines below this in docs/reviewer-contract.md.
    ("arcs_status_in_heading",
     lambda r: _write(r, D("specs", "ARCS.md"),
                      "# Arcs\n\n- [Arc B — shipped](#arc-b--shipped)\n\n## Arc B — shipped\n\nNarrative.\n"),
     1, "carries status"),
    ("arcs_heading_not_in_list",
     lambda r: _write(r, D("specs", "ARCS.md"), "# Arcs\n\n## Arc B\n\nNarrative.\n"),
     1, "missing from the arc list"),

    # ---- check_spec_status ----------------------------------------------------------------
    # The spec carries FRs deliberately. Without them `check_spec_size` fires instead and the
    # case passes for the wrong reason — which is what mutation-testing this corpus caught.
    # The delivery doc exists deliberately: without it, `Status: Completed` also trips the
    # "Completed with no write-up" exit and the case passes with the disagreement rule disabled.
    ("spec_status_disagrees",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 3).replace("Status: Draft", "Status: Completed")),
                _write(r, D("spec-delivery", "SPEC-001-thing.md"), "# Completed Spec — SPEC-001\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "INDEX.md says"),
    ("spec_completed_without_delivery_doc",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 3).replace("Status: Draft", "Status: Completed")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Completed |\n")],
     1, "no docs/spec-delivery/ write-up"),

    # ---- check_spec_size -------------------------------------------------------------------
    ("spec_with_no_fr_headings",
     lambda r: [_write(r, D("specs", "SPEC-002-thing.md"), "# SPEC-002: Thing\n\nStatus: Draft\n\nProse only.\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 002 | Draft |\n")],
     1, "size ratchet cannot see"),

    # ---- check_delivery_size --------------------------------------------------------------
    ("delivery_doc_too_long",
     lambda r: _write(r, D("spec-delivery", "SPEC-001-thing.md"), "# Completed\n" + "line\n" * 300),
     1, "lines"),

    # ---- check_source_citations -----------------------------------------------------------
    ("source_cites_a_spec_number",
     lambda r: _write(r, "lambdas/handler.py", "# Guarded per SPEC-137, see that spec.\nX = 1\n"),
     1, "lambdas/handler.py"),

    # ---- check_workflow_table -------------------------------------------------------------
    ("workflow_without_a_row",
     lambda r: _write(r, ".github/workflows/deploy.yml", "name: D\non: [push]\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: true\n"),
     1, "deploy.yml"),

    # ---- check_links ----------------------------------------------------------------------
    ("broken_relative_link",
     lambda r: _write(r, D("process.md"), "# Process\n\nSee [the thing](nowhere.md).\n"),
     1, "nowhere.md"),

    # ---- check_section_pointers -----------------------------------------------------------
    ("owed_pointer_to_missing_section",
     lambda r: _write(r, D("testing", "owed.md"), "# Owed\n\n§9.9 is where the recipe lives.\n"),
     1, "§9.9"),

    # ---- check_doc_paths_everywhere --------------------------------------------------------
    # Scans SOURCE files (.py/.yml/.tf/...), never markdown — a markdown link is check_links'
    # subject. A docstring citing a doc that has been moved is the case this catches.
    ("doc_path_in_source_that_does_not_exist",
     lambda r: _write(r, "lambdas/thing.py", '"""See ' + D("nowhere", "missing.md") + ' for the rules."""\n'),
     1, "missing.md"),

    # ---- check_always_loaded_pointers ------------------------------------------------------
    ("claude_pointer_resolves_to_nothing",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text() + "\nSee `@" + D("nowhere.md") + "`.\n"),
     1, "nowhere.md"),

    # ---- silence cases ---------------------------------------------------------------------
    ("baseline_ok", lambda r: None, 0, ""),

    # Six checks had no `_ok` case, so an "always fires" mutant in each survived the whole
    # corpus. A failures-only corpus cannot see a check that fires on legitimate content — which
    # is half of what a gate gets wrong.
    ("one_fixture_script_ok",
     lambda r: _write(r, D("testing", "fixtures", "plane-a.sh"), "#!/bin/sh\n"),
     0, ""),
    ("arc_heading_listed_and_statusless_ok",
     lambda r: _write(r, D("specs", "ARCS.md"), "# Arcs\n\n- [Arc B](#arc-b)\n\n## Arc B\n\nNarrative.\n"),
     0, ""),
    ("delivery_doc_within_cap_ok",
     lambda r: _write(r, D("spec-delivery", "SPEC-001-thing.md"), "# Completed Spec — SPEC-001\n" + "line\n" * 40),
     0, ""),
    ("source_without_a_citation_ok",
     lambda r: _write(r, "lambdas/handler.py", "# The guard is total: a swallowed fault is named by type.\nX = 1\n"),
     0, ""),
    ("valid_owed_section_pointer_ok",
     lambda r: _write(r, D("testing", "owed.md"), "# Owed\n\n### 2.6 A section\n\n§2.6 is where the recipe lives.\n"),
     0, ""),
    ("valid_always_loaded_pointer_ok",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text() + "\nSee `@" + D("process.md") + "`.\n"),
     0, ""),

    # check_workflow_table checks BOTH directions; only the missing-row direction had a case.
    ("workflow_row_with_no_file",
     lambda r: _write(r, ".github/workflows/README.md",
                      "# Workflows\n\n| File | Trigger | Purpose |\n|---|---|---|\n"
                      "| `ci.yml` | PR | the one workflow |\n| `gone.yml` | PR | deleted long ago |\n"),
     1, "gone.yml"),
    ("spec_with_fr_headings_is_countable_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 6)),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
]


def _no_literal_doc_paths() -> list[str]:
    """Refuse a literal documentation path in this file's own source.

    The `D()` helper exists so `check_doc_paths_everywhere` has no claim to refuse. Nothing
    enforced that, and a review found one literal that had slipped through — silent only because
    the doc it named happens to exist, so it would have started failing the day that file moved.
    A convention nothing checks is a convention that drifts, which is the whole subject of the
    gate this corpus tests, so the corpus checks its own.

    Args:
      None.

    Returns:
      One message per literal found, empty when the invariant holds.

    Raises:
      None.
    """
    import re
    trees = ("docs", "apps/portal/info", "lambdas/info", "infra/info", "infra/modules")
    pattern = re.compile(r"[\"'`](?:" + "|".join(re.escape(x) for x in trees) + r")/[A-Za-z0-9_./-]+\.md")
    source = pathlib.Path(__file__).read_text()
    return [f"literal documentation path in this file: {m.group(0)} — build it with D() instead"
            for m in pattern.finditer(source)]


def main() -> int:
    """Run every case and report all failures at once.

    Mirrors ``validate_docs.py``'s own reporting: everything, not the first, so one run tells the
    whole story.

    Args:
      None.

    Returns:
      ``0`` when every case behaved as declared, ``1`` otherwise.

    Raises:
      None.
    """
    passed, failed = 0, []
    for message in _no_literal_doc_paths():
        failed.append(("no_literal_doc_paths", message, ""))
        print(f"FAIL  no_literal_doc_paths: {message}")
    for name, mutate, want_exit, want_text in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "repo"
            root.mkdir()
            build(root)
            mutate(root)
            rc, out = run(root)
        why = None
        if rc != want_exit:
            why = f"exit {rc}, wanted {want_exit}"
        elif name.endswith("_ok"):
            if "problem(s)" in out:
                why = "expected silence, got a problem"
        elif want_text and want_text not in out:
            why = f"output lacked {want_text!r}"
        if why:
            failed.append((name, why, out))
            print(f"FAIL  {name}: {why}")
        else:
            passed += 1
            print(f"ok    {name}")
    print("----")
    print(f"validate_docs_test: {passed} passed, {len(failed)} failed.")
    for name, _, out in failed:
        print(f"\n--- {name} output ---\n{out.strip()[:600]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
