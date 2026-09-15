"""The fixture corpus for ``validate_docs.py``.

Why this exists. ``validate_docs.py`` runs every check in its ``main()`` on every pull request,
and until this file it had no test of any kind. Running it against this repo's own documents
proves those documents pass; it proves nothing about whether any check still fires. A gate whose
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
a failures-only corpus perfectly. A case that expects exit 0 AND a text is a WARNING case: the
validator reported something and failed nothing, and both halves of that are asserted.

Usage: ``python3 scripts/validate_docs_test.py`` — takes no arguments, imports nothing outside
the standard library, and exits non-zero if any case does not behave as declared.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent

# The three shapes the layout checks hold the new always-loaded tier to. Fixtures that break a
# shape are written from these by hand, so a change to a baseline shape is visible at every plant
# that depends on it. Paths inside them are assembled the way D() assembles every fixture path, so
# this file states no doc-path claim for the scan to refuse.
CLAUDE = (
    "# P\n\n## Key Decisions (settled)\n\nIntro.\n\n| Area | Fences |\n|---|---|\n"
    "| Area one | [`area-one.md`](docs/decisions" + "/area-one.md#fences) |\n"
    "| Identity and access | [`identity-and-access.md`](docs/decisions" + "/identity-and-access.md#fences) |\n\n"
    "## Out of Scope\n\nx\n")
ROUTER = (
    "# Process\n\n## Loaded every session\n\n| File | Authoritative for |\n|---|---|\n"
    "| `CLAUDE.md` | rules |\n| `docs/process" + "/INDEX.md` (this file) | the router |\n"
    "| `docs/process" + "/session-rhythm.md` | the rhythm |\n\n"
    "## The method, one file per part\n\n| File | Holds | Pull it |\n|---|---|---|\n"
    "| [`session-rhythm.md`](session-rhythm.md) | rhythm | every session |\n"
    "| [`authoring-a-spec.md`](authoring-a-spec.md) | authoring | when writing |\n"
    "| [`completion-ritual.md`](completion-ritual.md) | closing | when closing |\n"
    "| [`spec-lifecycle.md`](spec-lifecycle.md) | statuses | when status changes |\n")
AREA_ONE = (
    "# Area one\n\n## Contents\n\n- [Fences](#fences)\n- [Alpha](#alpha)\n\n"
    "## Fences\n\n- **Alpha** — fence.\n\n## Alpha\n\nR.\n")
RULE = ("---\npaths:\n  - \"{glob}\"\n---\n\nThis file is in the **{label}** area of the Key Decisions register.\n"
        "Before changing it, read `docs/decisions" + "/{area}.md#fences` — the traps there apply green and fail later.\n")
# The inventory page every case starts from: the directory it covers declared in its H1, and one
# row on line 7, so a row a case appends is on line 8.
DEMO = "apps/portal/src/features/demo"
INVENTORY_PAGE = ("# Demo feature (`" + DEMO + "/`)\n\nIntro.\n\n| Symbol | File | Purpose |\n|---|---|---|\n"
                  "| `Widget` | `Widget.tsx` | The row the baseline needs. |\n")


def build(root: pathlib.Path) -> None:
    """Write the smallest documentation tree that passes every check.

    Every file here is load-bearing for at least one check, which is why the baseline is this
    large: the checks are cross-referential. The decisions register must be routed by its INDEX
    and its areas must match the rows of CLAUDE.md's Key Decisions table, each of which
    resolves to a file opening with its Fences and to a pointer rule under ``.claude/rules/``; the workflows README must have a row
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
    # The citation ratchet is EXACT — a count below it is an error too, because a fall means
    # either a repair or a scan that stopped looking. The fixture tree has no stale citation, so
    # its ratchet is zero; leaving the repository's own number here would fail every case.
    _citation_ratchet(root, 0)
    for d in ("docs/testing", "docs/decisions", "docs/specs", "docs/spec-delivery",
              "apps/portal/info", "lambdas/info/planes", "infra/info", "infra/modules",
              ".github/workflows", "docs/process", ".claude/rules"):
        (root / d).mkdir(parents=True, exist_ok=True)

    (root / "README.md").write_text("# R\n")
    (root / "CLAUDE.md").write_text(CLAUDE)
    (root / "docs" / "process" / "INDEX.md").write_text(ROUTER)
    (root / "docs" / "process" / "session-rhythm.md").write_text("# Rhythm\n")
    for name in ("authoring-a-spec.md", "completion-ritual.md", "spec-lifecycle.md"):  # named in validate_docs.py's docstrings
        (root / "docs" / "process" / name).write_text("# On demand\n")
    (root / ".claude" / "rules" / "area-one.md").write_text(RULE.format(glob="lambdas/**", label="Area one", area="area-one"))
    (root / ".claude" / "rules" / "identity-and-access.md").write_text(
        RULE.format(glob=".github/**", label="Identity and access", area="identity-and-access"))
    (root / "docs" / "reviewer-contract.md").write_text("# Reviewer contract\n")
    for name in ("e2e.md", "owed.md", "sessions.md"):
        (root / "docs" / "testing" / name).write_text("# t\n")
    (root / "docs" / "decisions" / "INDEX.md").write_text(
        "# Decisions\n\n- [Area one](area-one.md)\n- [Identity and access](identity-and-access.md)\n")
    (root / "docs" / "decisions" / "area-one.md").write_text(AREA_ONE)
    (root / "docs" / "decisions" / "identity-and-access.md").write_text(
        "# Identity and access\n\n## Contents\n\n- [Fences](#fences)\n- [X](#x)\n\n"
        "## Fences\n\n- **X** — fence.\n\n## X\n\nR.\n")
    (root / "docs" / "specs" / "INDEX.md").write_text("# Index\n")
    (root / "docs" / "specs" / "ARCS.md").write_text("# Arcs\n")
    (root / "lambdas" / "info" / "planes" / "api.md").write_text("# API plane\n")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n")
    (root / ".github" / "workflows" / "README.md").write_text(
        "# Workflows\n\n| File | Trigger | Purpose |\n|---|---|---|\n| `ci.yml` | PR | the one workflow |\n")
    # check_test_citations holds each of its three grammars to matching at least once, so the
    # baseline carries one of each and a suite that resolves them. Without this every `_ok` case
    # would fail on a control that is doing its job, and — worse — a corpus with no citations at
    # all could not tell a working scan from one that matches nothing.
    (root / "lambdas" / "cited").mkdir(parents=True, exist_ok=True)
    (root / "lambdas" / "cited" / "test_cited.py").write_text(
        "def test_the_cap_is_held():\n    assert True\n")
    (root / "lambdas" / "cited" / "cited.py").write_text(
        '"""Sized by the cap that ``test_the_cap_is_held`` reads back."""\n\nCAP = 1\n')
    (root / "infra" / "modules" / "cited").mkdir(parents=True, exist_ok=True)
    # Two citations, the BARE one second. The grammar tally records every match rather than the
    # first per file, and a fixture whose files each carry one citation cannot tell those apart —
    # so the only bare site in the tree deliberately sits behind a code span.
    (root / "infra" / "modules" / "cited" / "locals.tf").write_text(
        "locals {\n  # Sized against `test_the_cap_is_held`, which reads it back.\n"
        "  # test_the_cap_is_held READS THIS NUMBER.\n  cap = 1\n}\n")
    (root / "lambdas" / "info" / "planes" / "cited.md").write_text(
        "# Cited plane\n\nThe sweep in test_cited.py forbids a second one.\n")
    # check_inventory_files refuses a run that read no inventory page, and a page it read no row
    # from, so the baseline carries one page whose one row resolves.
    _write(root, INV("demo-feature.md"), INVENTORY_PAGE)
    _write(root, DEMO + "/Widget.tsx", "export const Widget = 1;\n")


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


def INV(name: str) -> str:
    """A fixture path in the component inventory, spelled so no literal names a ``.md`` file."""
    return f"apps/portal/info/component-inventory/{name}"


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _inventory(root, rows="", after="", page=INVENTORY_PAGE):
    """Rewrite the demo inventory page: its table plus ``rows``, then ``after`` beneath it."""
    _write(root, INV("demo-feature.md"), page + rows + after)


def _touch(root, *rels):
    """Create the source files a row under test names, each exporting the name it is called by.

    So a row naming ``Thing`` in ``Thing.ts`` holds. That makes this helper's default a place the
    residency check cannot fail, which is why every case about residency writes its file's text
    itself, with a name that differs from the file's.
    """
    for rel in rels:
        _write(root, rel, f"export const {pathlib.PurePosixPath(rel).name.split('.')[0]} = 1;\n")


def _spec(n, frs, status="Draft"):
    """A spec in the template's shape: the four required sections, each FR with acceptance criteria."""
    body = "\n".join(f"### FR-{i:03d} A requirement\n\nText.\n\n#### Acceptance Criteria:\n\n- [ ] a\n"
                     for i in range(1, frs + 1))
    return (f"# SPEC-{n:03d}: Thing\n\nStatus: {status}\n\n## Overview\n\nWhy.\n\n## Scope\n\nWhat.\n\n"
            f"## Functional Requirements\n\n{body}\n## Implementation Phases\n\n### Phase 1\n\n- do\n")


def _ratchet(root, value):
    """Rewrite ``SPEC_OVERSIZE_MAX`` in the fixture's COPY of the validator.

    The ratchet cannot trip against a fixture small enough to read otherwise, and an environment
    override is the wrong seam: a budget a caller can redirect is a budget CI can be told to
    ignore. The copy is the fixture's own, so the live constant is untouched, and the substitution
    is counted so a renamed constant fails here rather than leaving the case to pass on the old
    value.
    """
    script = root / "scripts" / "validate_docs.py"
    text = script.read_text()
    if text.count("SPEC_OVERSIZE_MAX = 40\n") != 1:
        raise RuntimeError("the ratchet constant moved or changed value; update _ratchet() with it")
    script.write_text(text.replace("SPEC_OVERSIZE_MAX = 40\n", f"SPEC_OVERSIZE_MAX = {value}\n"))


def _citation_ratchet(root, value):
    """Rewrite ``TEST_CITATION_MAX`` in the fixture's COPY of the validator.

    The same seam ``_ratchet`` uses and for the same reason. The value is matched rather than
    written out, because this ratchet falls as the citation debt is paid and a hard-coded number
    would send every case here red on a PR that only lowered it — but the NAME is still required
    to appear exactly once, so a renamed constant fails here instead of leaving the cases to pass
    against a ratchet that no longer exists.
    """
    import re

    script = root / "scripts" / "validate_docs.py"
    text = script.read_text()
    found = re.findall(r"^TEST_CITATION_MAX = \d+$", text, re.MULTILINE)
    if len(found) != 1:
        raise RuntimeError("the citation ratchet moved or was renamed; update _citation_ratchet()")
    script.write_text(text.replace(found[0], f"TEST_CITATION_MAX = {value}"))


def _cite(root, value, rel, body):
    """Plant one citation with the ratchet at zero, so a single stale name decides the exit code."""
    _citation_ratchet(root, value)
    _write(root, rel, body)


CASES = [
    # ---- check_testing_layout -------------------------------------------------------------
    ("testing_stray_file",
     lambda r: _write(r, D("testing", "notes-from-tuesday.md"), "# notes\n"),
     1, "docs/testing/"),
    ("testing_inflight_e2e_ok",
     lambda r: _write(r, D("testing", "arc-b-e2e.md"), "# in-flight arc script\n"),
     0, ""),

    # ---- check_fixture_scripts ------------------------------------------------------------
    # The ratchet is 2, so TWO plane scripts are allowed and a THIRD is refused. Both halves are
    # here deliberately: a corpus of only-refusals cannot see a cap that has been lowered by
    # accident, which would refuse the second plane's script while reading as the same rule.
    ("fixture_scripts_at_the_ratchet",
     lambda r: [_write(r, D("testing", "fixtures", "plane-a.sh"), "#!/bin/sh\n"),
                _write(r, D("testing", "fixtures", "plane-b.sh"), "#!/bin/sh\n")],
     0, ""),
    ("fixture_scripts_over_the_ratchet",
     lambda r: [_write(r, D("testing", "fixtures", "plane-a.sh"), "#!/bin/sh\n"),
                _write(r, D("testing", "fixtures", "plane-b.sh"), "#!/bin/sh\n"),
                _write(r, D("testing", "fixtures", "plane-c.sh"), "#!/bin/sh\n")],
     1, "fixtures"),

    # ---- check_claude_budget --------------------------------------------------------------
    ("claude_over_budget",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text() + "\nfiller " * 9000),
     1, "CLAUDE.md is"),
    ("fences_bullet_too_long",
     lambda r: _write(r, D("decisions", "area-one.md"), AREA_ONE.replace("- **Alpha** — fence.", "- **Alpha** — " + "reasoning " * 150)),
     1, "a Fences bullet is"),

    # ---- check_process_budget -------------------------------------------------------------
    ("process_pair_over_budget",
     lambda r: _write(r, D("process", "session-rhythm.md"), "# Rhythm\n" + ("filler line of prose. " * 900)),
     1, "always-loaded pair is"),
    ("process_always_loaded_file_missing",
     lambda r: (r / D("process", "session-rhythm.md")).unlink(),
     1, "session-rhythm.md is missing"),

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
     lambda r: _write(r, D("process", "spec-lifecycle.md"), "# Lifecycle\n\nSee [the thing](nowhere.md).\n"),
     1, "dangling link"),

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
    # ---- check_fences ---------------------------------------------------------------------
    ("fences_not_first",
     lambda r: _write(r, D("decisions", "area-one.md"),
                      "# Area one\n\n## Contents\n\n- [Alpha](#alpha)\n- [Fences](#fences)\n\n## Alpha\n\nR.\n\n## Fences\n\n- **Alpha** — fence.\n"),
     1, "not 'Fences'"),
    ("fences_missing",
     lambda r: _write(r, D("decisions", "area-one.md"), "# Area one\n\n## Contents\n\n- [Alpha](#alpha)\n\n## Alpha\n\nR.\n"),
     1, "does not list [Fences](#fences) first"),
    ("claude_table_row_points_nowhere",
     lambda r: _write(r, "CLAUDE.md", CLAUDE.replace("/area-one.md#fences", "/area-two.md#fences")),
     1, "is not an existing file's #fences"),
    ("claude_table_missing_an_area",
     lambda r: _write(r, "CLAUDE.md", "\n".join(line for line in CLAUDE.split("\n") if not line.startswith("| Area one")) ),
     1, "is not one of the areas in CLAUDE.md's"),
    ("register_index_order_differs",
     lambda r: _write(r, D("decisions", "INDEX.md"), "# Decisions\n\n- [Identity and access](identity-and-access.md)\n- [Area one](area-one.md)\n"),
     1, "different order"),
    ("fences_pointer_resolves_to_nothing",
     lambda r: _write(r, D("decisions", "area-one.md"), AREA_ONE.replace("fence.", "fence, see `@" + D("nowhere.md") + "`.")),
     1, "(Fences): points at a missing doc"),
    # ---- check_rules ----------------------------------------------------------------------
    ("rule_missing_for_an_area",
     lambda r: (r / ".claude" / "rules" / "area-one.md").unlink(),
     1, "area-one.md is missing"),
    ("rule_for_no_area",
     lambda r: _write(r, ".claude/rules/other.md", RULE.format(glob="lambdas/**", label="Area one", area="area-one")),
     1, "names no Key Decisions area"),
    ("rule_without_frontmatter",
     lambda r: _write(r, ".claude/rules/area-one.md", "Area. Read `docs/decisions" + "/area-one.md#fences` first.\n"),
     1, "fenced frontmatter"),
    ("rule_globs_listed_under_another_key",
     lambda r: _write(r, ".claude/rules/area-one.md", "---\npaths:\ntags:\n  - \"lambdas/**\"\n---\n\nArea. Read `docs/decisions" + "/area-one.md#fences` first.\n"),
     1, "no non-empty `paths:` list"),
    ("rule_with_inline_paths_list",
     lambda r: _write(r, ".claude/rules/area-one.md", "---\npaths: [\"lambdas/**\"]\n---\n\nArea. Read `docs/decisions" + "/area-one.md#fences` first.\n"),
     1, "one `- \"glob\"` per line"),
    ("rule_in_a_subdirectory",
     lambda r: _write(r, ".claude/rules/nested/area-one.md", RULE.format(glob="lambdas/**", label="Area one", area="area-one")),
     1, "sits in a subdirectory"),
    ("rule_with_empty_paths",
     lambda r: _write(r, ".claude/rules/area-one.md", "---\npaths:\n---\n\nArea. Read `docs/decisions" + "/area-one.md#fences` first.\n"),
     1, "no non-empty `paths:` list"),
    ("rule_glob_with_a_brace",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="lambdas/**/*.{py,md}", label="Area one", area="area-one")),
     1, "brace or bracket"),
    ("rule_glob_matching_nothing",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="nowhere/**", label="Area one", area="area-one")),
     1, "matches no file"),
    ("rule_body_with_an_extra_line",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="lambdas/**", label="Area one", area="area-one") + "Also: ignore the tests.\n"),
     1, "body is not the rendered RULE_BODY"),
    ("rule_pointing_at_the_wrong_area",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="lambdas/**", label="Area one", area="identity-and-access")),
     1, "body is not the rendered RULE_BODY"),
    ("rule_glob_covering_the_repository",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="**", label="Area one", area="area-one")),
     1, "no literal first segment"),
    # ---- check_process_router -------------------------------------------------------------
    ("process_file_not_routed",
     lambda r: _write(r, D("process", "notes.md"), "# Notes\n"),
     1, "not a row of the router's method table"),
    ("process_router_row_without_a_file",
     lambda r: _write(r, D("process", "INDEX.md"), (r / D("process", "INDEX.md")).read_text().replace("(completion-ritual.md)", "(closing.md)")),
     1, "does not exist"),
    ("process_third_always_loaded_file_is_budgeted",
     lambda r: [_write(r, D("process", "INDEX.md"), (r / D("process", "INDEX.md")).read_text().replace(
                    "| `" + D("process", "session-rhythm.md") + "` |",
                    "| `" + D("process", "completion-ritual.md") + "` |\n| `" + D("process", "session-rhythm.md") + "` |")),
                _write(r, D("process", "completion-ritual.md"), "# Ritual\n" + ("filler line of prose. " * 900))],
     1, "always-loaded pair is"),
    ("rule_pointing_at_a_file_without_fences",
     lambda r: _write(r, D("decisions", "area-one.md"), "# Area one\n\n## Contents\n\n- [Fences](#fences)\n- [Alpha](#alpha)\n\n## Alpha\n\nR.\n"),
     1, "has no ## Fences entry"),

    # ---- the cases an inventory of this corpus found missing -----------------------------------
    # The ratchet actually tripping, and holding at the line. The constant is rewritten in the
    # fixture's copy: 41 over-size specs would otherwise be needed to reach the live value.
    ("spec_size_ratchet_trips_on_a_new_oversize_spec",
     lambda r: [_ratchet(r, 0),
                _write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 9)),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "specs carry more than 8 FRs (ratchet 0)"),
    ("spec_size_ratchet_holds_at_the_line_ok",
     lambda r: [_ratchet(r, 1),
                _write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 9)),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_without_a_status_header",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 3).replace("Status: Draft\n\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "SPEC-001-thing.md has no Status header"),
    ("spec_without_an_index_row",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 3)),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 002 | Draft |\n")],
     1, "SPEC-001-thing.md has no row in INDEX.md"),
    ("register_area_held_by_two_files",
     lambda r: _write(r, D("decisions", "area-one-copy.md"), AREA_ONE),
     1, "'Area one' is already held by"),
    ("register_entry_at_a_second_heading_level",
     lambda r: _write(r, D("decisions", "area-one.md"), AREA_ONE + "\n### Alpha, in detail\n\nR.\n"),
     1, "is a second heading level"),
    ("register_contents_anchor_to_no_entry",
     lambda r: _write(r, D("decisions", "area-one.md"), AREA_ONE.replace("- [Alpha](#alpha)\n", "- [Alpha](#alpha)\n- [Gone](#gone)\n")),
     1, "links to #gone, which is no entry in this file"),
    ("testing_two_arc_scripts_in_flight",
     lambda r: [_write(r, D("testing", "arc-b-e2e.md"), "# b\n"),
                _write(r, D("testing", "arc-c-e2e.md"), "# c\n")],
     1, "holds 2 arc scripts"),
    ("fixture_script_named_after_a_spec",
     lambda r: _write(r, D("testing", "fixtures", "spec-221-conversion.sh"), "#!/bin/sh\n"),
     1, "spec-221-conversion.sh is named after a SPEC"),

    # ---- check_spec_shape -----------------------------------------------------------------
    # Every case indexes its spec: the status check runs beside the shape check, and a spec with
    # no INDEX row would fail for that reason and pass the shape assertion vacuously.
    ("spec_missing_a_required_section",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("## Scope\n\nWhat.\n\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "SPEC-001-thing.md: missing required section '## Scope'"),
    ("spec_section_only_at_a_deeper_level",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("## Scope\n", "### Scope\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Scope'"),
    ("spec_section_name_is_only_a_prefix",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("## Scope\n", "## Scoped\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Scope'"),
    # Several sections missing at once, and several specs at once: a check that stops after the
    # first missing section, or returns after the first file, passes every single-section,
    # single-spec case above.
    ("spec_missing_two_sections_names_each",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2).replace("## Scope\n\nWhat.\n\n", "").replace("## Implementation Phases\n", "## Phases\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Implementation Phases'"),
    # One case per required section, so dropping any ONE name from SPEC_REQUIRED_SECTIONS reddens
    # something: with only Scope and Phases ever removed, Overview and Functional Requirements
    # could vanish from the tuple with the corpus green — measured by a reviewer's plant.
    ("spec_missing_overview",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("## Overview\n\nWhy.\n\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Overview'"),
    ("spec_missing_functional_requirements",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("## Functional Requirements\n", "## Requirements\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Functional Requirements'"),
    ("spec_second_of_two_specs_fails",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2)),
                _write(r, D("specs", "SPEC-002-thing.md"), _spec(2, 2).replace("## Scope\n\nWhat.\n\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n| 002 | Draft |\n")],
     1, "SPEC-002-thing.md: missing required section '## Scope'"),
    ("spec_two_warnings_on_one_spec",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2).replace("#### Acceptance Criteria:\n\n- [ ] a\n", "") + "\nSee SPEC-XXX.\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "2 warning(s)"),
    ("spec_sections_in_any_case_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2).replace("## Overview", "## overview").replace("## Scope", "## SCOPE")
                       .replace("## Functional Requirements", "## Functional requirements")
                       .replace("## Implementation Phases", "## implementation phases")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_banned_heading_at_any_level",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n#### Checkpoint: pause here\n\nno\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "banned heading '#### Checkpoint: pause here'"),
    ("spec_banned_heading_names_its_line",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), "# S\n\nStatus: Draft\n\n## Open Questions\n\n" + _spec(1, 2).split("\n", 4)[4]),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "SPEC-001-thing.md line 5: banned heading"),
    ("spec_banned_heading_in_any_case",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n## open questions\n\nnone\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "banned heading '## open questions'"),
    ("spec_banned_heading_inside_a_fence_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n```\n## Open Questions\n#### Checkpoint\n```\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_banned_heading_inside_a_comment_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n<!--\n## Open Questions\n-->\n<!-- #### Checkpoint -->\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    # A comment opened mid-line swallows the lines after it until it closes: the banned heading
    # inside is not a heading. A reader that only enters comment state on a line STARTING with
    # `<!--` passes every other comment case here.
    ("spec_banned_heading_after_a_midline_comment_opener_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\nNote <!-- draft\n## Open Questions\n-->\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_banned_heading_inside_a_tilde_fence_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n~~~\n## Open Questions\n#### Checkpoint\n~~~\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_banned_heading_deep_inside_a_comment_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n<!--\ndraft note\n## Open Questions\n-->\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_fence_never_closed_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n```\n## Open Questions\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    # The banned word anywhere in the heading, not only at its start — the template's semantics.
    ("spec_banned_word_inside_a_heading",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n### Phase 2 checkpoint\n\nno\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "banned heading '### Phase 2 checkpoint'"),
    ("spec_required_section_inside_a_fence_does_not_count",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2).replace("## Scope\n\nWhat.\n\n", "```\n## Scope\n```\n\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Scope'"),
    # The exemption. A Completed spec from the earlier template, with both retired headings, is
    # left alone; so is a Cancelled tombstone with none of the required sections.
    ("spec_completed_before_the_rule_is_exempt_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2, "Completed") + "\n#### Checkpoint: old\n\n## Open Questions\n\nnone\n"),
                _write(r, D("spec-delivery", "SPEC-001-thing.md"), "# Completed Spec — SPEC-001\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Completed |\n")],
     0, ""),
    ("spec_cancelled_tombstone_is_exempt_ok",
     lambda r: [_write(r, D("specs", "SPEC-003-thing.md"),
                       "# SPEC-003: Thing\n\n**Status:** Cancelled\n\n## Why\n\nMoved.\n\n## Where the work went\n\nElsewhere.\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 003 | Cancelled |\n")],
     0, ""),
    # ...and it fails CLOSED: a status outside the exempt set, and no status at all, are judged.
    ("spec_superseded_is_not_exempt",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2, "Superseded") + "\n## Open Questions\n\nnone\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Superseded |\n")],
     1, "banned heading '## Open Questions'"),
    ("spec_in_progress_is_not_exempt",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2, "In Progress") + "\n## Open Questions\n\nnone\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | In Progress |\n")],
     1, "banned heading '## Open Questions'"),
    ("spec_without_a_status_is_judged",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"),
                       _spec(1, 2).replace("Status: Draft\n\n", "").replace("## Scope\n\nWhat.\n\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     1, "missing required section '## Scope'"),
    # The warnings: reported, exit 0. One case per placeholder, so dropping one from the tuple
    # is a red case rather than a quieter corpus.
    ("spec_placeholder_feature_name_warns",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("SPEC-001: Thing", "SPEC-001: [Feature Name]")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "SPEC-001-thing.md: unfilled template placeholder(s): [Feature Name]"),
    ("spec_placeholder_requirement_name_warns",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("FR-001 A requirement", "FR-001: [Requirement Name]")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "unfilled template placeholder(s): [Requirement Name]"),
    ("spec_placeholder_spec_xxx_warns",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\nSee SPEC-XXX.\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "unfilled template placeholder(s): SPEC-XXX"),
    ("spec_placeholder_last_updated_warns",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("Status: Draft\n", "Status: Draft\n**Last Updated:** YYYY-MM-DD\n")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "unfilled template placeholder(s): YYYY-MM-DD"),
    ("spec_date_format_described_in_prose_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\nKeys are `logs/dt=YYYY-MM-DD/`.\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_placeholder_inside_a_fence_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2) + "\n```\nSee SPEC-XXX.\n```\n"),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    ("spec_frs_without_acceptance_criteria_warn",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("#### Acceptance Criteria:\n\n- [ ] a\n", "")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, "SPEC-001-thing.md: has FR-* requirements but no 'Acceptance Criteria'"),
    ("spec_acceptance_criteria_in_any_case_ok",
     lambda r: [_write(r, D("specs", "SPEC-001-thing.md"), _spec(1, 2).replace("Acceptance Criteria", "acceptance criteria")),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n")],
     0, ""),
    # The live template, unfilled: its structure passes and its placeholders warn. Exit 0 is the
    # structural claim — a missing section would fail — and the text is the placeholder one.
    ("spec_template_unfilled_passes_its_shape_and_warns",
     lambda r: [_write(r, D("specs", "SPEC-000-template.md"), (REPO / "docs" / "templates" / "spec-template.md").read_text()),
                _write(r, D("specs", "INDEX.md"), "# Index\n\n| 000 | Draft |\n")],
     0, "SPEC-000-template.md: unfilled template placeholder(s): [Feature Name], [Requirement Name], SPEC-XXX, YYYY-MM-DD"),

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
    ("fences_bullet_within_cap_ok",
     lambda r: _write(r, D("decisions", "area-one.md"), AREA_ONE.replace("fence.", "fence, " + "short " * 40)),
     0, ""),
    ("rule_with_single_quoted_glob_ok",
     lambda r: _write(r, ".claude/rules/area-one.md", RULE.format(glob="lambdas/**", label="Area one", area="area-one").replace('"lambdas/**"', "'lambdas/**'")),
     0, ""),
    ("rules_with_overlapping_globs_ok",
     lambda r: _write(r, ".claude/rules/identity-and-access.md", RULE.format(glob="lambdas/**", label="Identity and access", area="identity-and-access")),
     0, ""),
    ("valid_always_loaded_pointer_ok",
     lambda r: _write(r, "CLAUDE.md", (r / "CLAUDE.md").read_text() + "\nSee `@" + D("process", "INDEX.md") + "`.\n"),
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

    # ---- check_test_citations -------------------------------------------------------------
    # Each plant carries its OWN absent name, and every case asserts that name in the output.
    # The ratchet message is identical whichever grammar found the citation, so asserting it
    # alone would let any neighbouring grammar satisfy any of these cases.
    ("citation_absent_in_a_code_span",
     lambda r: _cite(r, 0, "lambdas/cited/spanned.py",
                     '"""Held by ``test_absent_from_a_span``."""\n'),
     1, "names test_absent_from_a_span"),
    ("citation_absent_bare_in_a_comment",
     lambda r: _cite(r, 0, "infra/modules/cited/bare.tf",
                     "locals {\n  # test_absent_from_a_comment READS THIS NUMBER.\n  cap = 2\n}\n"),
     1, "names test_absent_from_a_comment"),
    ("citation_absent_as_a_filename",
     lambda r: _cite(r, 0, "lambdas/cited/named.py",
                     '"""The sweep in test_absent_module.py forbids it."""\n'),
     1, "names test_absent_module"),
    # An ASL template carries no comment marker anywhere in the tree, so bare matching there is
    # unconditional. Without that, a citation inside a JSON "Comment" string is invisible.
    ("citation_absent_in_a_state_machine_template",
     lambda r: _cite(r, 0, "infra/modules/cited/machine.asl.json.tftpl",
                     '{\n  "Comment": "The rollback arm cannot reach a deletion, which\n'
                     ' test_absent_from_a_template asserts by walking the graph."\n}\n'),
     1, "names test_absent_from_a_template"),
    # Vitest files are deliberately NOT excluded: one in this repo cites a Python test.
    ("citation_absent_in_a_vitest_file",
     lambda r: _cite(r, 0, "apps/portal/src/Thing.test.tsx",
                     "// Pinned by `test_absent_from_a_vitest_file`.\nexport const x = 1;\n"),
     1, "names test_absent_from_a_vitest_file"),
    # The name is split mid-identifier across a wrap. Asserting the FULL name is the point: without
    # the rejoin the check reports a truncated stub, which resolves against nothing either — so the
    # case would pass on the wrong finding if it asserted the failure loosely.
    ("citation_wrapped_across_a_line_break",
     lambda r: _cite(r, 0, "lambdas/cited/wrapped.py",
                     '"""A cap, and ``test_absent_and_split_across\n    _two_lines`` reads it."""\n'),
     1, "names test_absent_and_split_across_two_lines"),
    # The positive control. Deleting the only bare citation leaves that grammar matching nothing,
    # which must be reported as a broken scan rather than passing as a clean tree.
    ("citation_grammar_gone_quiet",
     lambda r: (r / "infra" / "modules" / "cited" / "locals.tf").unlink(),
     1, "matched nothing in 1 of its 3 grammars (bare in a comment)"),
    # The fall direction. A ceiling cannot see lost detection — narrowing the scanned set was
    # measured to drop eight findings in silence — so a count BELOW the ratchet is an error that
    # asks for the number to be moved deliberately.
    ("citation_below_the_ratchet",
     lambda r: _citation_ratchet(r, 1),
     1, "below the ratchet of 1 — lower it to 0"),
    ("citation_over_the_ratchet",
     lambda r: _cite(r, 1, "lambdas/cited/two.py",
                     '"""``test_absent_one`` and ``test_absent_two`` hold it."""\n'),
     1, "2 citations name a test that does not exist (ratchet 1)"),
    # ---- the retirement exemption, and the two ways it must NOT widen ----------------------
    ("citation_retired_before_the_name_ok",
     lambda r: _cite(r, 0, "lambdas/cited/before.py",
                     '"""Retires the layer tables, the build script and test_absent_before.py."""\n'),
     0, ""),
    ("citation_retired_after_the_name_ok",
     lambda r: _cite(r, 0, "lambdas/cited/after.py",
                     '"""``test_absent_after`` was retired in the cutover."""\n'),
     0, ""),
    # The verb lands on the FOLLOWING line, 90 characters past the citation. A window that did not
    # look forward across the line break would report this legitimate record as a finding.
    ("citation_retired_on_the_next_line_ok",
     lambda r: _cite(r, 0, D("decisions", "area-one.md"),
                     AREA_ONE + "\n~~`test_absent_next_line` fails if a second one appears, so the "
                     "exemption cannot\nquietly widen.~~ **Retired with the list**, and nothing "
                     "replaced it.\n"),
     0, ""),
    # THE case that decides the vocabulary. A LIVE claim that happens to describe deletion must
    # still fail; admitting `delete` or `remove` as retirement words would silence nine live
    # citations in this repo, two of them findings this check exists to report.
    ("citation_about_deletion_is_not_a_retirement",
     lambda r: _cite(r, 0, "lambdas/cited/deleting.py",
                     '"""``test_absent_but_about_deleting`` fails if a deleted object reappears,\n'
                     'and nothing is removed until it passes."""\n'),
     1, "names test_absent_but_about_deleting"),
    # THE OTHER EDGE OF THE SAME EXEMPTION: its vocabulary. The window has a width and a word
    # list, and a word list can be widened as silently as a number — seven near-misses were each
    # admitted with both gates green before this case existed. Every name here is cited in a LIVE
    # claim, so admitting any of these words drops the count below the ratchet and reddens. The
    # ratchet is set to the number of them, which also pins the citation list as WARNINGS rather
    # than errors: promoting them would make this case exit 1.
    ("citation_near_miss_words_are_not_retirements",
     lambda r: _cite(r, 7, "lambdas/cited/nearmiss.py",
                     '"""``test_absent_but_superseded`` is superseded by nothing.\n'
                     '``test_absent_but_dropped`` was dropped from the sweep.\n'
                     '``test_absent_but_gone`` is gone from the table.\n'
                     '``test_absent_but_obsolete`` is obsolete now.\n'
                     '``test_absent_but_replaced`` was replaced by the join.\n'
                     '``test_absent_but_withdrawn`` was withdrawn upstream.\n'
                     '``test_absent_but_sunset`` is sunset in the next arc."""\n'),
     0, "names test_absent_but_dropped"),
    # The hint is the ONLY place the remedy appears while the count sits AT the ratchet, which is
    # the whole of a paydown. Deleting it was silent before this case.
    ("citation_hint_names_the_remedy",
     lambda r: _cite(r, 1, "lambdas/cited/hinted.py",
                     '"""Held by ``test_absent_and_hinted``."""\n'),
     0, "the exemption is the word"),
    # ---- what is deliberately not a citation ----------------------------------------------
    ("citation_trailing_slash_is_a_directory_ok",
     lambda r: _cite(r, 0, "lambdas/cited/dir.py", '"""A table over ``test_absent_folder/``."""\n'),
     0, ""),
    ("citation_inside_a_markdown_fence_ok",
     lambda r: _cite(r, 0, D("testing", "arc-b-e2e.md"),
                     "# Script\n\n```\n`test_absent_from_a_fence` is an example\n```\n"),
     0, ""),
    # Markdown's `#` opens a heading, not a comment, so the bare grammar does not apply there.
    ("citation_bare_in_markdown_ok",
     lambda r: _cite(r, 0, D("testing", "arc-b-e2e.md"),
                     "# A folder called test_absent_bare_in_prose\n\nNot a citation.\n"),
     0, ""),
    # THE UPPER EDGE of the exemption window, which is the direction that loses findings: widening
    # it to the whole file was measured to drop 17 of this repo's 46 findings in silence, and the
    # tree pins only the LOW side. The verb is placed just past the constant, so the band this case
    # leaves unguarded is a couple of characters rather than the hundred a round-number fixture
    # leaves — a verb at ~215 let the window be more than doubled with the corpus green.
    ("citation_retired_too_far_from_the_name",
     lambda r: _cite(r, 0, "lambdas/cited/faraway.py",
                     '"""Retired when the manifest verbs landed, and nothing replaced it\n'
                     'because nothing now can replace it.\n'
                     '``test_absent_far_from_the_verb`` still holds the cap at four."""\n'),
     1, "names test_absent_far_from_the_verb"),
    # The dedup key is (line, name), so one name cited on two lines is two findings. Collapsing the
    # key to the name alone survives every other case here.
    ("citation_absent_twice_in_one_file",
     lambda r: _cite(r, 1, "lambdas/cited/twice.py",
                     '"""``test_absent_on_two_lines`` sizes it.\n\n'
                     'And ``test_absent_on_two_lines`` is read back here too."""\n'),
     1, "2 citations name a test that does not exist (ratchet 1)"),
    # The bare grammar in a `//` comment, in a .ts file. Both halves are otherwise untested: every
    # bare citation in the tree today is .tf or .tftpl, and the one .tsx case writes its name in
    # backticks, so `//` and the .ts suffix were both carried by other grammars.
    ("citation_absent_bare_in_a_slash_comment",
     lambda r: _cite(r, 0, "apps/portal/src/thing.ts",
                     "// Sized by test_absent_from_a_slash_comment, which reads this number.\n"
                     "export const CAP = 4;\n"),
     1, "names test_absent_from_a_slash_comment"),
    # Workflows and shell scripts joined the scanned set because a comment there makes the same
    # promise. Both need their own case: the 12 citations they carry today all resolve, so
    # dropping either suffix changes no count and goes unnoticed without a planted absence.
    ("citation_absent_in_a_workflow",
     lambda r: _cite(r, 0, "infra/modules/cited/probe.yml",
                     "steps:\n  # test_absent_from_a_workflow pins this matrix.\n  - run: true\n"),
     1, "names test_absent_from_a_workflow"),
    ("citation_absent_in_a_shell_script",
     lambda r: _cite(r, 0, "infra/modules/cited/probe.sh",
                     "#!/bin/sh\n# Guarded by test_absent_from_a_shell_script.\nexit 0\n"),
     1, "names test_absent_from_a_shell_script"),
    # The same grammar in a Python comment, which is neither .tf nor .tftpl — the branch that
    # admits it is `suffix != ".md"`, and narrowing that to .tf alone survives otherwise.
    ("citation_absent_bare_in_a_python_comment",
     lambda r: _cite(r, 0, "lambdas/cited/hashed.py",
                     "# test_absent_from_a_python_comment READS THIS NUMBER.\nCAP = 4\n"),
     1, "names test_absent_from_a_python_comment"),
    # ---- the tier exclusions, and the one that is deliberately narrower than its tree -------
    ("citation_in_a_spec_is_history_ok",
     lambda r: [_write(r, D("specs", "INDEX.md"), "# Index\n\n| 001 | Draft |\n"),
                _cite(r, 0, D("specs", "SPEC-001-thing.md"),
                      _spec(1, 1).replace("Text.", "Pinned by `test_absent_from_a_spec`."))],
     0, ""),
    # ARCS.md is live narrative the completion ritual still edits, so the exclusion is per-spec
    # rather than per-tree. Blanket-excluding the directory hid two false citations in this file.
    ("citation_in_arcs_is_judged",
     lambda r: _cite(r, 0, D("specs", "ARCS.md"),
                     "# Arcs\n\nPinned by `test_absent_from_arcs`.\n"),
     1, "names test_absent_from_arcs"),
    ("citation_in_a_test_module_ok",
     lambda r: _cite(r, 0, "lambdas/cited/test_other.py",
                     '"""Delegated to ``test_absent_from_a_suite``."""\n\n'
                     "def test_something():\n    assert True\n"),
     0, ""),
    # The population anchors `def` at the start of a line. Relaxing it to a search would let a
    # COMMENTED-OUT definition, or one inside a string, resolve a citation — a guard that is only
    # described somewhere is exactly what this check exists to refuse.
    ("citation_resolved_by_a_commented_out_def",
     lambda r: [_write(r, "lambdas/cited/ghost.py",
                       "# def test_absent_but_commented_out():\n#     assert True\n"),
                _cite(r, 0, "lambdas/cited/ghostref.py",
                      '"""Held by ``test_absent_but_commented_out``."""\n')],
     1, "names test_absent_but_commented_out"),
    ("citation_resolved_by_a_module_stem_ok",
     lambda r: _cite(r, 0, "lambdas/cited/stem.py", '"""The sweep in ``test_cited`` forbids it."""\n'),
     0, ""),
    # 290 names in the population carry a capital. A lowercase-only class truncates this one at
    # `test_the_` and then reports that stub as unresolved.
    ("citation_with_uppercase_resolves_ok",
     lambda r: [_write(r, "lambdas/cited/test_upper.py",
                       "def test_the_CAP_is_held():\n    assert True\n"),
                _cite(r, 0, "lambdas/cited/upper.py",
                      '"""Held by ``test_the_CAP_is_held``."""\n')],
     0, ""),

    # ---- check_inventory_files ------------------------------------------------------------
    # The case the check exists for. The line number is asserted here once, so a message that
    # blames the wrong row cannot pass.
    ("inventory_row_outlives_its_file",
     lambda r: _inventory(r, "| `Panel` | `Panel.tsx` | Deleted. |\n"),
     1, "demo-feature.md:8: `Panel.tsx` is not in `" + DEMO + "/`"),
    # A bare name means the declared directory itself. Read against the directories above it as
    # well, it would find this file higher up and pass a row naming nothing in the feature.
    ("inventory_bare_name_found_only_higher_up",
     lambda r: [_touch(r, "apps/portal/src/main.tsx"),
                _inventory(r, "| `main` | `main.tsx` | Not in this feature. |\n")],
     1, "`main.tsx` is not in `" + DEMO + "/`"),
    ("inventory_spelled_path_resolves_nowhere",
     lambda r: _inventory(r, "| `helper` | `lib/absent.ts` | Gone. |\n"),
     1, "`lib/absent.ts` is not in `" + DEMO + "/` or any directory above it"),
    # Every span in a cell is a claim, not only the first.
    ("inventory_second_name_in_a_cell",
     lambda r: _inventory(r, "| `Widget` / `Absent` | `Widget.tsx`, `Absent.tsx` | Half gone. |\n"),
     1, "`Absent.tsx` is not in"),
    ("inventory_same_folder_symbol_without_a_file",
     lambda r: _inventory(r, "| `Widget`, `Ghost` | (same folder) | One gone. |\n"),
     1, "`Ghost` is filed as (same folder), but Ghost.tsx or Ghost.ts is not in"),
    ("inventory_glob_symbol_without_a_file",
     lambda r: _inventory(r, "| `Widget` / `Ghost` | `*.tsx` | One gone. |\n"),
     1, "`Ghost` is filed as `*.tsx`, but Ghost.tsx is not in"),
    ("inventory_derived_form_without_symbols",
     lambda r: _inventory(r, "| — | (same folder) | Names nothing. |\n"),
     1, "the Symbol cell '—' names no symbol this check can read"),
    # A tombstone claims ABSENCE, so it is checked the other way round.
    ("inventory_tombstone_for_a_file_that_is_back",
     lambda r: _inventory(r, "| — | `Widget.tsx` is **gone** | It came back. |\n"),
     1, "`Widget.tsx` is recorded as gone, but it exists"),
    # Refused rather than skipped: a cell the check cannot read is a row it has stopped checking.
    ("inventory_cell_without_backticks",
     lambda r: _inventory(r, "| `Widget` | Widget.tsx | Unquoted. |\n"),
     1, "the File cell 'Widget.tsx' names nothing in backticks"),
    # The grammar refuses a dot segment, and says so. Without it this row still fails, since no
    # directory listing holds `..`, but as a missing file, which is false: the file is there.
    ("inventory_span_that_walks_out",
     lambda r: _inventory(r, "| `Widget` | `../demo/Widget.tsx` | Traverses. |\n"),
     1, "`../demo/Widget.tsx` in the File column is neither a file nor a directory name"),
    # Passes on a case-insensitive disk — macOS, where these sessions run — and fails on the Linux
    # runner, unless the check matches the spelling of each component.
    ("inventory_wrong_case",
     lambda r: _inventory(r, "| `Widget` | `widget.tsx` | Wrong case. |\n"),
     1, "`widget.tsx` is not in"),
    ("inventory_moved_to_a_directory_that_is_gone",
     lambda r: _inventory(r, "| `Thing` | moved to `features/gone/` | Moved again. |\n"),
     1, "`features/gone/` is not in `" + DEMO + "/` or any directory above it"),
    ("inventory_declared_directory_missing",
     lambda r: _inventory(r, page=INVENTORY_PAGE.replace(DEMO, "apps/portal/src/features/renamed")),
     1, "declares `apps/portal/src/features/renamed/`, which is not a directory in this repository"),
    # An absolute path is outside the tree the check reads. Reported, rather than raised from deep
    # in the resolver, where it took every other check's report down with it.
    ("inventory_declared_directory_outside_the_repo",
     lambda r: _inventory(r, page=INVENTORY_PAGE.replace(DEMO + "/", "/etc/")),
     1, "declares `/etc/`, which is not a directory in this repository"),
    # A trailing slash names a directory, and a file of that name is not one.
    ("inventory_file_named_as_a_directory",
     lambda r: _inventory(r, "| `Widget` | `Widget.tsx/` | Not a folder. |\n"),
     1, "`Widget.tsx/` is not in"),
    ("inventory_row_shorter_than_its_header",
     lambda r: _inventory(r, "| `Widget` |\n"),
     1, "the File cell '' names nothing in backticks"),
    ("inventory_same_folder_beside_a_name",
     lambda r: [_touch(r, DEMO + "/useWidget.ts"),
                _inventory(r, "| `Widget`, `Ghost` | (same folder), `useWidget.ts` | One gone. |\n")],
     1, "`Ghost` is filed as (same folder), but Ghost.tsx or Ghost.ts is not in"),
    # Tables are found by their delimiter row. A table indented, or written without outer pipes,
    # is read like any other; found by a leading pipe instead, each passed with its row unread.
    ("inventory_indented_table_is_read",
     lambda r: _inventory(r, after="\n   | Symbol | File | Purpose |\n   |---|---|---|\n"
                                   "   | `Ghost` | `Ghost.tsx` | Indented. |\n"),
     1, "`Ghost.tsx` is not in"),
    # A table ends at a blank line or a heading, never at a line without a pipe: GitHub renders
    # that line as one more row. Ended there instead, a hard-wrapped row hid every row under it.
    ("inventory_row_after_a_wrapped_line_is_read",
     lambda r: _inventory(r, "| `Widget` | `Widget.tsx` | A purpose that wraps |\nonto a line with no pipe\n"
                             "| `Ghost` | `Ghost.tsx` | Gone. |\n"),
     1, "`Ghost.tsx` is not in"),
    ("inventory_table_without_outer_pipes_is_read",
     lambda r: _inventory(r, after="\nSymbol | File | Purpose\n--- | --- | ---\n"
                                   "`Ghost` | `Ghost.tsx` | Pipeless.\n"),
     1, "`Ghost.tsx` is not in"),
    # Under a heading declaring its own directory, a bare name is read THERE. `Widget.tsx` is in
    # the page's directory, so a check still reading the H1's would pass this row.
    ("inventory_subheading_rebases",
     lambda r: [_touch(r, "apps/portal/src/routes/Route.tsx"),
                _inventory(r, after="\n## Routes (`apps/portal/src/routes/`)\n\n| Symbol | File | Purpose |\n"
                                    "|---|---|---|\n| `Widget` | `Widget.tsx` | Not a route. |\n")],
     1, "`Widget.tsx` is not in `apps/portal/src/routes/`"),
    # The three positive controls. Each would otherwise pass exactly like an inventory with nothing
    # wrong in it. The first sits on a page whose other table is fine, which is what the per-page
    # control cannot see: one good table satisfies it.
    ("inventory_table_without_a_file_column",
     lambda r: _inventory(r, after="\n### Services\n\n| Symbol | Purpose |\n|---|---|\n"
                                   "| `ghost()` | Its file is named nowhere the check reads. |\n"),
     1, "demo-feature.md:11: a table headed 'Symbol | Purpose' has no `File` column"),
    ("inventory_page_with_no_table",
     lambda r: _write(r, INV("other-feature.md"), "# Other (`" + DEMO + "/`)\n\nProse, and no table.\n"),
     1, "other-feature.md: no row read from a table with a `File` column"),
    ("inventory_directory_gone",
     lambda r: shutil.rmtree(r / INV("")),
     1, "component-inventory/ holds no pages"),
    # The last row names a page beside its source. The page exports nothing, and the name's home
    # is the source file, so the row holds.
    ("inventory_multi_name_cells_ok",
     lambda r: [_touch(r, DEMO + "/useWidget.ts"),
                _write(r, DEMO + "/notes.md", "# Notes\n"),
                _inventory(r, "| `Widget` / `useWidget` | `Widget.tsx` / `useWidget.ts` | Slash. |\n"
                              "| `Widget`, `useWidget` | `Widget.tsx`, `useWidget.ts` | Comma. |\n"
                              "| `useWidget` | `useWidget.ts` (+ `Widget.tsx`) | Parenthesised. |\n"
                              "| `useWidget` | `useWidget.ts` (+ `notes.md`) | Beside a page. |\n")],
     0, ""),
    # Rows spell paths from different roots, and each has to resolve.
    ("inventory_spelled_paths_ok",
     lambda r: [_touch(r, "apps/portal/src/lib/helper.ts"),
                _inventory(r, "| `helper` | `lib/helper.ts` | From src. |\n"
                              "| `helper` | `src/lib/helper.ts` | From the portal. |\n"
                              "| `helper` | `apps/portal/src/lib/helper.ts` | From the root. |\n"
                              "| `Widget` | `features/demo/Widget.tsx` | Its own feature, spelled out. |\n")],
     0, ""),
    ("inventory_symbol_named_files_ok",
     lambda r: [_touch(r, DEMO + "/Gadget.ts", DEMO + "/Gizmo.tsx"),
                _inventory(r, "| `Widget`, `Gadget` | (same folder) | A .tsx and a .ts. |\n"
                              "| `Widget` / `Gizmo(props)` | `*.tsx` | Each in its own file. |\n")],
     0, ""),
    # A tombstone names no source, so its row need name no symbol; one that does name the symbol
    # the file took with it has no file left to read the name in.
    ("inventory_tombstones_ok",
     lambda r: [_touch(r, "apps/portal/src/features/other/Thing.ts"),
                _inventory(r, "| `Thing` | moved to `features/other/` | Moved. |\n"
                              "| — | `old.format.ts` is **gone** | Deleted. |\n"
                              "| `normalizeColumnType` | `older.format.ts` is **gone** | Went with it. |\n")],
     0, ""),
    # An escaped pipe is not a column boundary. Split on it, and the File column reads `null)`.
    ("inventory_escaped_pipe_ok",
     lambda r: [_touch(r, DEMO + "/useWidget.ts"),
                _inventory(r, "| `useWidget(id \\| null)` | `useWidget.ts` | Escaped. |\n")],
     0, ""),
    # The router declares no directory, and its File column is links to the pages beside it —
    # which is where a page that declares nothing is read.
    ("inventory_router_page_ok",
     lambda r: _write(r, INV("INDEX.md"), "# Inventory\n\nRouter.\n\n| Area | File |\n|---|---|\n"
                      "| Demo | [`demo-feature.md`](demo-feature.md) |\n"),
     0, ""),
    # A declaring subheading's scope ends at the next heading at its level.
    ("inventory_subheading_scope_ends_ok",
     lambda r: [_touch(r, "apps/portal/src/routes/Route.tsx"),
                _inventory(r, after="\n## Routes (`apps/portal/src/routes/`)\n\n| Symbol | File | Purpose |\n"
                                    "|---|---|---|\n| `Route` | `Route.tsx` | A route. |\n"
                                    "\n## More\n\n| Symbol | File | Purpose |\n|---|---|---|\n"
                                    "| `Widget` | `Widget.tsx` | Back in the feature. |\n")],
     0, ""),

    # ---- check_inventory_files: each name in the Symbol cell is exported by the row's file ------
    # The case residency exists for: the file is still there and the symbol moved to its sibling,
    # which the File-cell check passes. The line number is asserted once here too.
    ("inventory_symbol_moved_to_a_sibling_file",
     lambda r: [_write(r, DEMO + "/athena.service.ts", "export function getQueryStatus() {}\n"),
                _write(r, DEMO + "/rowCount.service.ts", "export function getQueryRowCount() {}\n"),
                _inventory(r, "| `getQueryRowCount(id)` | `athena.service.ts` | Moved out. |\n")],
     1, "demo-feature.md:8: `getQueryRowCount` is not exported from `athena.service.ts`"),
    # Named in a file is not exported from it. Every line here names `helper`, most after the word
    # `export`, one in each form the reader knows, and one at the start of a line inside a block
    # comment; a reader that looks for the name, or for any of those forms anywhere, passes the row.
    ("inventory_symbol_named_but_not_exported",
     lambda r: [_write(r, DEMO + "/util.ts",
                       "import {helper} from './other';\n/**\n * export function helper() moved out.\n */\n"
                       "// export const helper = 1;\n// export {helper} from './helper';\n"
                       "// export default helper;\n/*\nexport function helper() {}\n*/\n"
                       "const local = helper;\nexport const other = local;\n"),
                _inventory(r, "| `helper()` | `util.ts` | Imported, not exported. |\n")],
     1, "`helper` is not exported from `util.ts`"),
    # An item exported `as` another name is exported by that name, and by no other.
    ("inventory_symbol_exported_under_another_name",
     lambda r: [_write(r, DEMO + "/util.ts", "const helper = 1;\nexport {helper as assist};\n"),
                _inventory(r, "| `helper` | `util.ts` | Renamed on the way out. |\n")],
     1, "`helper` is not exported from `util.ts`"),
    # A directory is read one level deep, and only its source: an export in a subdirectory, or a
    # code sample in a README, is not the directory's.
    ("inventory_symbol_only_below_a_named_directory",
     lambda r: [_write(r, "apps/portal/src/features/other/other.ts", "export const Other = 1;\n"),
                _write(r, "apps/portal/src/features/other/deep/thing.ts", "export const Thing = 1;\n"),
                _inventory(r, "| `Thing` | moved to `features/other/` | Moved. |\n")],
     1, "`Thing` is not exported from any source file directly in `features/other/`"),
    ("inventory_symbol_only_in_a_readme",
     lambda r: [_write(r, "apps/portal/src/features/other/other.ts", "export const Other = 1;\n"),
                _write(r, "apps/portal/src/features/other/README.md", "```ts\nexport const Thing = 1;\n```\n"),
                _inventory(r, "| `Thing` | moved to `features/other/` | Moved. |\n")],
     1, "`Thing` is not exported from any source file directly in `features/other/`"),
    # Under `(same folder)` the name is read in its own file, which here exports another.
    ("inventory_same_folder_symbol_not_exported",
     lambda r: [_write(r, DEMO + "/Gadget.ts", "export const gadget = 1;\n"),
                _inventory(r, "| `Gadget` | (same folder) | Its file exports another name. |\n")],
     1, "`Gadget` is not exported from `Gadget.ts`"),
    # The JSX form claims its component, and a member the name before the dot. Read any other way,
    # each row claims nothing, or is refused, and says so in other words.
    ("inventory_jsx_form_is_read",
     lambda r: _inventory(r, "| `<Ghost prop>` | `Widget.tsx` | A component. |\n"),
     1, "`Ghost` is not exported from `Widget.tsx`"),
    ("inventory_member_form_is_read",
     lambda r: _inventory(r, "| `Ghost.field` | `Widget.tsx` | A member. |\n"),
     1, "`Ghost` is not exported from `Widget.tsx`"),
    # A span is one name, matched whole. Each of these carries a second name, or a family of them,
    # in a place a reader of its first name alone never looks, and each row holds if the span is
    # read that way: `Widget` is exported and `Ghost` is not. One case per place, so loosening
    # the match anywhere turns one red by name.
    ("inventory_symbol_runs_on_past_its_name",
     lambda r: _inventory(r, "| `Widget/Ghost` | `Widget.tsx` | Two names in one span. |\n"),
     1, "`Widget/Ghost` in the Symbol column is not one name"),
    ("inventory_symbol_runs_on_after_a_space",
     lambda r: _inventory(r, "| `Widget Ghost` | `Widget.tsx` | Two names, a space apart. |\n"),
     1, "`Widget Ghost` in the Symbol column is not one name"),
    ("inventory_symbol_second_name_after_a_call",
     lambda r: _inventory(r, "| `Widget(id) / Ghost()` | `Widget.tsx` | Two calls. |\n"),
     1, "`Widget(id) / Ghost()` in the Symbol column is not one name"),
    ("inventory_symbol_second_name_after_a_type_argument",
     lambda r: _inventory(r, "| `Widget<T> / Ghost<U>` | `Widget.tsx` | Two types. |\n"),
     1, "`Widget<T> / Ghost<U>` in the Symbol column is not one name"),
    ("inventory_symbol_second_tag_after_a_jsx_tag",
     lambda r: _inventory(r, "| `<Widget prop> or <Ghost>` | `Widget.tsx` | Two tags. |\n"),
     1, "`<Widget prop> or <Ghost>` in the Symbol column is not one name"),
    ("inventory_symbol_second_name_after_a_member",
     lambda r: _inventory(r, "| `Widget.size, Ghost` | `Widget.tsx` | A member, then a name. |\n"),
     1, "`Widget.size, Ghost` in the Symbol column is not one name"),
    # Beside a name, a leading wildcard keeps the per-row control quiet, so only this refusal
    # stands between it and a family nobody checks.
    ("inventory_symbol_span_without_a_name",
     lambda r: _inventory(r, "| `Widget` / `*Props` | `Widget.tsx` | A family, unnamed. |\n"),
     1, "`*Props` in the Symbol column is not one name"),
    # A span is a return only when an arrow and nothing else stands before it. Here words do too,
    # and the span is a claim like any other.
    ("inventory_symbol_after_an_arrow_and_words_is_read",
     lambda r: _inventory(r, "| `Widget()` → a list, and `Ghost()` | `Widget.tsx` | Then a claim. |\n"),
     1, "`Ghost` is not exported from `Widget.tsx`"),
    # Brackets are read one deep, and a deeper span says it is refused rather than being misread.
    ("inventory_symbol_nested_brackets_refused",
     lambda r: _inventory(r, "| `Widget(wrap(id))` | `Widget.tsx` | Nested. |\n"),
     1, "`Widget(wrap(id))` in the Symbol column is not one name"),
    # A stylesheet exports nothing, so "not exported" would be a true sentence with a false reason.
    ("inventory_symbol_filed_only_in_a_non_source_file",
     lambda r: [_write(r, DEMO + "/tokens.css", ":root {}\n"),
                _inventory(r, "| `brand` | `tokens.css` | A token. |\n")],
     1, "`brand` is filed only in `tokens.css`, which is not source and exports nothing"),
    # The positive control: a row that names source must name a symbol. A table whose Symbol
    # column was renamed reads an empty cell on every row, and passes exactly like a table whose
    # every symbol is at home unless this fires.
    ("inventory_table_with_its_symbol_column_renamed",
     lambda r: _inventory(r, after="\n### Hooks\n\n| Name | File | Purpose |\n|---|---|---|\n"
                                   "| `useGhost` | `Widget.tsx` | Not read as a symbol. |\n"),
     1, "demo-feature.md:13: the Symbol cell '' names no symbol this check can read"),
    ("inventory_symbol_cell_without_backticks",
     lambda r: _inventory(r, "| useGhost | `Widget.tsx` | Unquoted. |\n"),
     1, "the Symbol cell 'useGhost' names no symbol this check can read"),
    ("inventory_directory_row_without_a_symbol",
     lambda r: [_touch(r, "apps/portal/src/features/other/Thing.ts"),
                _inventory(r, "| — | moved to `features/other/` | Moved, but what? |\n")],
     1, "the Symbol cell '—' names no symbol this check can read"),
    # Every export form the reader knows, each claimed by name, so a form it stops reading turns
    # this case red.
    ("inventory_export_forms_ok",
     lambda r: [_write(r, DEMO + "/forms.ts",
                       "export function fnA(x) {}\nexport function* fnGen() {}\nexport async function fnB() {}\n"
                       "export const cC = 1;\nexport let lD = 1;\nexport var vV = 1;\nexport type TE<T> = T;\n"
                       "export interface IF {}\nexport enum EG {}\nexport const enum CEH {}\nexport class KI {}\n"
                       "export abstract class KJ {}\nexport declare const dS: number;\nexport namespace NS {}\n"
                       "export default function DefK() {}\nconst lL = 1;\nconst lM = 1;\n"
                       "export {lL};\nexport {lM as aliasM};\nexport {type TO} from './types';\n"
                       "export type {TU} from './types';\n"
                       "export {\n  // a comment the reader skips\n  lP,\n  /* and another */ lQ,\n} from './more';\n"
                       "export * as NSX from './ns';\n/** Documented on the line it is declared. */ export function docd() {}\n"),
                _write(r, DEMO + "/Def.ts", "const DefR = 1;\nexport default DefR;\n"),
                _write(r, DEMO + "/Bom.ts", "﻿export const BomFirst = 1;\n"),
                # A comment is removed only where it opens a line: this glob is not one, and read
                # as one it would swallow the export beneath it.
                _write(r, DEMO + "/Glob.ts", "const glob = 'src/*.ts';\nexport const afterGlob = 1;\n// */\n"),
                _inventory(r, "| `fnA(x)` / `fnGen()` / `fnB()` / `cC` / `lD` / `vV` / `TE<T>` / `IF` / `EG` | `forms.ts` | Declared. |\n"
                              "| `CEH` / `KI` / `KJ` / `dS` / `NS` / `DefK` | `forms.ts` | Declared too. |\n"
                              "| `lL` / `aliasM` / `TO` / `TU` / `lP` / `lQ` | `forms.ts` | Listed. |\n"
                              "| `NSX` / `docd()` | `forms.ts` | A namespace, and one after its doc. |\n"
                              "| `DefR` | `Def.ts` | A default, declared above it. |\n"
                              "| `BomFirst` | `Bom.ts` | On a first line behind a byte-order mark. |\n"
                              "| `afterGlob` | `Glob.ts` | Beneath a glob that is not a comment. |\n")],
     0, ""),
    # Every Symbol-cell form that claims a name, and the ones that claim nothing: a return after
    # either arrow, whatever it is, a shape, and a member continuing the span before it.
    ("inventory_symbol_forms_ok",
     lambda r: [_write(r, DEMO + "/Widget.tsx",
                       "export const Widget = 1;\nexport function useWidget() {}\nexport type WidgetProps<T> = T;\n"
                       "export const widgetKeys = {};\nexport function Gadget() {}\nexport function Gizmo() {}\n"),
                _inventory(r, "| `useWidget(id)` → `{status, error}` | `Widget.tsx` | A call, and a shape. |\n"
                              "| `useWidget(id)` → `boolean` | `Widget.tsx` | A call, and a type. |\n"
                              "| `useWidget(id)` -> `[flags, status]` | `Widget.tsx` | A tuple, after an ASCII arrow. |\n"
                              "| `WidgetProps<T>` | `Widget.tsx` | A type argument. |\n"
                              "| `widgetKeys.list(id)` / `.detail(id)` | `Widget.tsx` | Members. |\n"
                              "| `<Widget prop>` / `<Gadget>` / `<Gizmo/>` | `Widget.tsx` | JSX. |\n")],
     0, ""),
    # A path the row spells out is read at every level it exists. The nearer one here exports
    # another name, and read alone it would fail a row whose symbol is where the row says.
    ("inventory_symbol_in_the_farther_reading_ok",
     lambda r: [_write(r, DEMO + "/lib/helper.ts", "export const other = 1;\n"),
                _write(r, "apps/portal/src/lib/helper.ts", "export const helper = 1;\n"),
                _write(r, DEMO + "/lib/shared/near.ts", "export const Near = 1;\n"),
                _write(r, "apps/portal/src/lib/shared/far.ts", "export const Far = 1;\n"),
                _inventory(r, "| `helper` | `lib/helper.ts` | The shared one. |\n"
                              "| `Far` | moved to `lib/shared/` | The shared directory. |\n")],
     0, ""),
    # A name re-exported by a directory's barrel is in the directory. The subdirectory beside it
    # is kept out by its missing suffix; the `is_file` test is for one named like a source file,
    # which no case can plant, because `check_source_citations` raises on it first.
    ("inventory_symbol_in_a_named_directory_ok",
     lambda r: [_write(r, "apps/portal/src/features/other/index.ts", "export {Thing} from './impl';\n"),
                _write(r, "apps/portal/src/features/other/impl/impl.ts", "export const Thing = 1;\n"),
                _inventory(r, "| `Thing` | moved to `features/other/` | Re-exported by the barrel. |\n")],
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
            # A warning breaks silence too: it exits 0, so without this line a warning fired on
            # legitimate content passes every `_ok` case — measured, when the unanchored date
            # placeholder plant reddened nothing.
            if "problem(s)" in out or "warning(s)" in out:
                why = "expected silence, got a problem or a warning"
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
