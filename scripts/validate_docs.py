"""Hold the documentation layout to the shape it was cut back to on 2026-08-18.

Every rule below already existed in prose, in ``CLAUDE.md`` or ``docs/process.md``, and every
one of them was violated anyway — ``## Specs`` regrew to 371 lines of changelog, the Key
Decisions digest grew entries of 3,349 characters against a stated "one line each",
``docs/testing/`` reached sixteen files of four different genres, ``decisions.md`` listed 50
of its 149 entries in a Contents nobody regenerated, and four arc headings in ``ARCS.md``
carried a status that had gone stale. A rule a reader has to remember is a rule that rots;
this file is the same rules where CI can see them.

Budgets are RATCHETS AT THE MEASURED LEVEL, not targets — the convention SPEC-150 set for the
coverage floors. Lowering one when a doc grows is the failure mode; the fix is to move the
detail down a tier, which is what every budget here exists to force.

Runs on every pull request (``ci.yml``). Takes no arguments and imports nothing outside the
standard library.

Attributes:
  ROOT: The repository root, derived from this file's location.
  TESTING_PERMANENT: The three files ``docs/testing/`` always holds. Anything else there must
    be the ONE script an arc in flight is allowed, or a subdirectory.
  TESTING_INFLIGHT_MAX: How many temporary per-arc scripts may exist at once. One. An arc
    folds its script into ``e2e.md`` when it closes (``docs/process.md`` §5 step 8). Only a
    ``*-e2e.md`` name counts as one — a dated session file is refused on its name alone, and
    does not merely consume the slot, because the slot may be free.
  CLAUDE_MAX_BYTES: The always-loaded file's budget. It was 121,098 bytes before the cut.
  DIGEST_MAX_CHARS: The longest a single Key Decisions line may be. The digest is a reminder
    with the reasoning in ``decisions.md``; past this length it has become the reasoning.
  DELIVERY_MAX_LINES: A delivery doc is "what shipped + what changed", typically under a page.
  STATUS_WORDS: Words that must not appear in an ``ARCS.md`` arc heading. Status lives in
    ``INDEX.md``, which is the only place it can be kept true.
  SOURCE_TREES: Where source lives, per language, for the citation check.
  CITATION_RE: A spec, PR or issue citation in a comment. Matched on the whole line rather than on
    comment syntax, because four languages' comment markers is four ways to miss one.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

TESTING_PERMANENT = frozenset({"e2e.md", "owed.md", "sessions.md"})
TESTING_INFLIGHT_MAX = 1
CLAUDE_MAX_BYTES = 52_000
DIGEST_MAX_CHARS = 900
DELIVERY_MAX_LINES = 260
STATUS_WORDS = ("shipped", "complete", "active", "draft", "in progress", "filed", "scoped")
SOURCE_TREES = (("apps/portal/src", (".ts", ".tsx")), ("lambdas", (".py",)), ("infra", (".tf", ".tftpl")))
CITATION_RE = re.compile(r"SPEC-\d{3}|(?<![\w#])#\d{3}(?![\w])")


class DocsError(Exception):
    """The documentation layout has drifted from the shape CI holds it to."""


def anchor(text: str) -> str:
    """Render a heading the way GitHub renders it into a fragment identifier.

    Each space becomes its own hyphen rather than collapsing a run, which is why
    ``A = B`` keeps a double hyphen. Getting this wrong makes a table of contents that
    looks right and jumps nowhere.

    Args:
      text: The heading text, without its leading hashes.

    Returns:
      The fragment identifier, without a leading ``#``.
    """
    cleaned = re.sub(r"[^\w \-]", "", text.replace("`", "").replace("*", "").strip().lower())
    return cleaned.replace(" ", "-")


def check_testing_layout() -> list[str]:
    """Refuse a new file in ``docs/testing/`` beyond the guide, the ledger and the log.

    Sixteen files across four genres is the state this replaced: a reader looking for
    "how do I validate this" had to know which genre held the answer. A spec that owes a
    live check adds a section to ``e2e.md``; one that cannot be run from a signed-in
    session adds a row to ``owed.md``.

    Args:
      None.

    Returns:
      One message per offending file, empty when the directory is as expected.

    Raises:
      None.
    """
    found = {p.name for p in (ROOT / "docs" / "testing").glob("*.md")}
    missing = sorted(TESTING_PERMANENT - found)
    others = sorted(found - TESTING_PERMANENT)
    inflight = [name for name in others if name.endswith("-e2e.md")]
    errors = [f"docs/testing/{name} is missing" for name in missing]
    for name in others:
        if not name.endswith("-e2e.md"):
            errors.append(
                f"docs/testing/{name} is neither the guide, the ledger, the log, nor an arc "
                "script. A session write-up is a dated SECTION at the top of sessions.md, never "
                "its own file — that is what made this directory sixteen files."
            )
    if len(inflight) > TESTING_INFLIGHT_MAX:
        errors.append(
            f"docs/testing/ holds {len(inflight)} arc scripts ({', '.join(inflight)}); "
            f"at most {TESTING_INFLIGHT_MAX} is allowed, and only while that arc is in flight. "
            "Fold a live check into e2e.md, or an unrunnable one into owed.md."
        )
    return errors


def check_claude_budget() -> list[str]:
    """Hold the always-loaded file, and each Key Decisions line, to their budgets.

    Both numbers are ratchets at the measured level. A digest line past the cap has stopped
    being a reminder and become the reasoning, which belongs in ``decisions.md``.

    Args:
      None.

    Returns:
      One message per breach, empty when both are within budget.

    Raises:
      None.
    """
    text = (ROOT / "CLAUDE.md").read_text()
    errors = []
    size = len(text.encode())
    if size > CLAUDE_MAX_BYTES:
        errors.append(
            f"CLAUDE.md is {size:,} bytes against a {CLAUDE_MAX_BYTES:,} budget. It loads every "
            "session: move the detail into docs/ behind a pointer rather than raising the cap."
        )
    section = text[text.index("## Key Decisions") : text.index("## Out of Scope")]
    for line in section.split("\n"):
        if line.startswith("- ") and len(line) > DIGEST_MAX_CHARS:
            errors.append(
                f"A Key Decisions line is {len(line)} chars (cap {DIGEST_MAX_CHARS}): "
                f"{line[:70]}… — keep the claim and the fence here, the reasoning in decisions.md."
            )
    return errors


def check_decisions_register() -> list[str]:
    """Require one heading level per entry, and a Contents that reaches every one of them.

    The register is pulled entry by entry, so an entry outside the Contents is only findable
    by reading the whole file — which is the cost the layering exists to avoid.

    Args:
      None.

    Returns:
      One message per unlisted entry, per broken anchor, or per stray heading level.

    Raises:
      None.
    """
    lines = (ROOT / "docs" / "decisions.md").read_text().split("\n")
    strays = [line for line in lines if line.startswith("## ") and not line.startswith("## Contents")]
    headings = [line[4:].strip() for line in lines if line.startswith("### ")]
    listed = set(re.findall(r"\]\(#([^)]+)\)", "\n".join(lines)))
    errors = [f"decisions.md: '{s}' is a ## heading; every entry is ###" for s in strays]
    seen: dict[str, int] = {}
    for heading in headings:
        base = anchor(heading)
        seen[base] = seen.get(base, 0) + 1
        target = base if seen[base] == 1 else f"{base}-{seen[base] - 1}"
        if target not in listed:
            errors.append(f"decisions.md: '{heading}' is not in the Contents (anchor #{target})")
    return errors


def check_arcs() -> list[str]:
    """Keep status out of ``ARCS.md`` headings, and every arc in its own list.

    Status written into a heading rots silently: four arcs carried a stale one, including
    seven Completed specs described as "active, all Draft".

    Args:
      None.

    Returns:
      One message per heading carrying status and per arc missing from the list.

    Raises:
      None.
    """
    lines = (ROOT / "docs" / "specs" / "ARCS.md").read_text().split("\n")
    headings = [line[3:].strip() for line in lines if line.startswith("## ")]
    listed = set(re.findall(r"\]\(#([^)]+)\)", "\n".join(lines)))
    errors = []
    for heading in headings:
        lowered = heading.lower()
        for word in STATUS_WORDS:
            if word in lowered:
                errors.append(
                    f"ARCS.md: '{heading}' carries status. INDEX.md owns status — "
                    "a heading that repeats it goes stale without anyone noticing."
                )
                break
        if anchor(heading) not in listed:
            errors.append(f"ARCS.md: '{heading}' is missing from the arc list at the top")
    return errors


def check_spec_status() -> list[str]:
    """Require each spec's own header to agree with its ``INDEX.md`` row, and Completed to deliver.

    Both places claim to be authoritative, so a disagreement means neither is.

    Args:
      None.

    Returns:
      One message per disagreement, per missing status header, and per Completed spec with no
      delivery doc.

    Raises:
      None.
    """
    specs = ROOT / "docs" / "specs"
    delivery = ROOT / "docs" / "spec-delivery"
    index = (specs / "INDEX.md").read_text()
    rows = dict(re.findall(r"^\|\s*(\d{3})[^|]*\|\s*([^|]+?)\s*\|", index, re.MULTILINE))
    errors = []
    for path in sorted(specs.glob("SPEC-*.md")):
        number = path.name[5:8]
        header = re.search(r"^\**Status:?\**[:\s]*\**\s*([A-Za-z ]+)", path.read_text(), re.MULTILINE)
        if number not in rows:
            errors.append(f"{path.name} has no row in INDEX.md")
            continue
        if header is None:
            errors.append(f"{path.name} has no Status header")
            continue
        stated, indexed = header.group(1).strip().lower(), rows[number].strip().lower()
        if not indexed.startswith(stated) and not stated.startswith(indexed):
            errors.append(f"{path.name}: header says '{stated}', INDEX.md says '{indexed}'")
        if stated == "completed" and not list(delivery.glob(f"SPEC-{number}-*.md")):
            errors.append(f"SPEC-{number} is Completed with no docs/spec-delivery/ write-up")
    return errors


def check_delivery_size() -> list[str]:
    """Keep a delivery doc to what shipped and what changed, not a second copy of the spec.

    Args:
      None.

    Returns:
      One message per oversized delivery doc.

    Raises:
      None.
    """
    errors = []
    for path in sorted((ROOT / "docs" / "spec-delivery").glob("*.md")):
        count = path.read_text().count("\n") + 1
        if count > DELIVERY_MAX_LINES:
            errors.append(
                f"docs/spec-delivery/{path.name} is {count} lines (cap {DELIVERY_MAX_LINES}): "
                "reuse belongs in the component inventory and reasoning in the spec."
            )
    return errors


def check_source_citations() -> list[str]:
    """Refuse a spec, PR or issue number in source.

    A number tells a reader that a decision was made somewhere else and leaves them to go and find
    it; a sentence tells them what is true. The reasoning belongs in the comment, and its full entry
    in ``docs/decisions.md`` — findable by what it says rather than by when it happened. A comment
    that cannot be written without citing a spec is a sign the reasoning never reached the register.

    Test files are excluded for now: 163 test NAMES carry the requirement they cover, and renaming
    them is its own change with its own blast radius.

    Args:
      None.

    Returns:
      One message per file still carrying citations, with the count and the first example.

    Raises:
      None.
    """
    errors = []
    for tree, suffixes in SOURCE_TREES:
        for path in sorted((ROOT / tree).rglob("*")):
            if path.suffix not in suffixes or ".test." in path.name or path.name.startswith("test_"):
                continue
            hits = [
                (number, line.strip())
                for line in path.read_text().split("\n")
                for number in CITATION_RE.findall(line)
            ]
            if hits:
                errors.append(
                    f"{path.relative_to(ROOT)}: {len(hits)} spec/PR citation(s), first is "
                    f"{hits[0][0] or hits[0][1][:60]!r} — say what is true, not where it was decided"
                )
    return errors


def check_links() -> list[str]:
    """Refuse a relative markdown link that points at nothing.

    A dangling link costs an agent a whole tool call to discover, and reads as a missing
    document rather than a stale pointer.

    Args:
      None.

    Returns:
      One message per dangling link.

    Raises:
      None.
    """
    errors = []
    files = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for path in files:
        for match in re.finditer(r"\[[^\]]*\]\(([^)#\s]+?)(?:#[^)]*)?\)", path.read_text()):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).exists() and not (ROOT / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: dangling link -> {target}")
    return errors


def check_section_pointers() -> list[str]:
    """Refuse a ``§N.N`` pointer into ``owed.md`` that names no section.

    Renumbering is what breaks these, and it breaks them silently: a reader following
    "the recipe is in §2.6" lands on the wrong procedure rather than on nothing, which is
    worse than a 404. Inserting one section shifted five references in a single pass.

    Args:
      None.

    Returns:
      One message per pointer naming a section that does not exist.

    Raises:
      None.
    """
    ledger = ROOT / "docs" / "testing" / "owed.md"
    sections = set(re.findall(r"^### (\d+\.\d+) ", ledger.read_text(), re.MULTILINE))
    errors = []
    for path in [ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        text = path.read_text()
        for match in re.finditer(r"(owed\.md`?[^.\n]{0,40}?|^)§(\d+\.\d+)", text, re.MULTILINE):
            cites_ledger = "owed.md" in match.group(1) or path == ledger
            if cites_ledger and match.group(2) not in sections:
                errors.append(
                    f"{path.relative_to(ROOT)}: §{match.group(2)} names no section of owed.md"
                )
    return errors


def check_doc_paths_everywhere() -> list[str]:
    """Refuse a reference to a missing ``docs/`` file from ANY tracked source file.

    Markdown is not where these rot unseen. The consolidation left two live pointers to deleted
    scripts in `infra/*.tf` — a comment and a Tofu output description — and a checker that walked
    only ``*.md`` reported the tree clean. A path in a comment is read by whoever is standing in
    that file, which is exactly when it is trusted most.

    Scoped to ``.md`` targets, which is enough on its own — the fixture keys that look like doc
    paths (`docs/2024/q1.csv` in the file-browser suite) carry data extensions and cannot match. A
    skip for test files was tried and removed: it hid two valid references and bought no accuracy.

    Args:
      None.

    Returns:
      One message per reference to a ``docs/`` path that does not exist.

    Raises:
      None.
    """
    suffixes = {".tf", ".tftpl", ".yml", ".yaml", ".py", ".ts", ".tsx", ".sh", ".toml"}
    skip = ("node_modules", ".terraform", "dist", "coverage", ".git")
    pattern = re.compile(r"docs/[A-Za-z0-9_./-]+\.md")
    errors = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in suffixes or any(part in skip for part in path.parts):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for target in sorted(set(pattern.findall(text))):
            if not (ROOT / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: references a missing doc -> {target}")
    return errors


def main() -> int:
    """Run every check and report all failures at once.

    Reports everything rather than stopping at the first, so one CI run tells the whole story.

    Args:
      None.

    Returns:
      ``0`` when the layout holds, ``1`` when any check failed.

    Raises:
      None.
    """
    errors: list[str] = []
    for check in (
        check_testing_layout,
        check_claude_budget,
        check_decisions_register,
        check_arcs,
        check_spec_status,
        check_delivery_size,
        check_source_citations,
        check_links,
        check_section_pointers,
        check_doc_paths_everywhere,
    ):
        errors.extend(check())
    if errors:
        print(f"Documentation layout: {len(errors)} problem(s)\n", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nEvery rule above is in CLAUDE.md or docs/process.md as prose, and every one of "
            "them was broken anyway. Fix the doc, not the budget.",
            file=sys.stderr,
        )
        return 1
    print("Documentation layout: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
