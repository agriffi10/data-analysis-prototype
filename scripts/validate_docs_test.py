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
