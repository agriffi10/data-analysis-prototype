"""Hold the documentation layout to the shape it was cut back to on 2026-08-18.

Every rule below already existed in prose, in ``CLAUDE.md`` or ``docs/process.md``, and every
one of them was violated anyway — ``## Specs`` regrew to 371 lines of changelog, the Key
Decisions digest grew entries of 3,349 characters against a stated "one line each",
``docs/testing/`` reached sixteen files of four different genres, ``decisions/`` listed 50
of its 149 entries in a Contents nobody regenerated, and four arc headings in ``ARCS.md``
carried a status that had gone stale. A rule a reader has to remember is a rule that rots;
this file is the same rules where CI can see them.

Budgets are RATCHETS AT THE MEASURED LEVEL, not targets — the convention SPEC-150 set for the
coverage floors. Lowering one when a doc grows is the failure mode; the fix is to move the
detail down a tier, which is what every budget here exists to force. **One documented
exception: ``CLAUDE_MAX_BYTES``, whose entry below says why a ratchet was the wrong shape
for that one file.**

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
  FIXTURES_MAX_SCRIPTS: How many CLI check scripts ``docs/testing/fixtures/`` may hold. A
    ratchet at the measured level, and the unit is the PLANE: four specs build one control
    plane, and a script each would be four files sharing a token, a queue URL, a group digest
    and an envelope builder. A spec that owes a CLI check adds a SECTION to its plane's script.
  CLAUDE_MAX_BYTES: The always-loaded file's budget. It was 121,098 bytes before the first cut and
    51,995 before the second, which replaced a Key Decisions list of 105 one-per-spec lines with
    eight blocks grouped by AREA. The list had stopped being a reminder and become a changelog:
    every closing spec appended one, and the file hit its own ratchet exactly when a spec tried to
    close. Group into the existing blocks; do not start a new line per spec.

    **Raised from 34,000 to 50,000 (user decision, 2026-08-27), and this is the ONE budget here
    deliberately not held at the measured level.** A ratchet at the measured level assumes the file
    only grows by accretion, and after the second cut that stopped being true: what remains is
    fences, and the completion ritual REQUIRES every closing spec to fold in a clause. At 34,000
    with 161 bytes free, SPEC-195 could not close without pruning another area's fences to pay for
    its own — which is the gate causing the damage it exists to prevent. The anti-regrowth rules
    that actually bind are the shape ones (group by area, no per-spec line, DIGEST_MAX_CHARS), and
    they are unchanged. If this file approaches 50,000 the answer is still a cut, not another
    raise: two cuts have already been needed, and both were structural.
  DIGEST_MAX_CHARS: The longest a single Key Decisions bullet may be, measured on the LOGICAL
    bullet — continuation lines joined. It was measured per physical line until 2026-08-26, which
    stopped meaning anything the moment the section was rewritten as wrapped prose: the longest
    physical line went from 846 characters to 103, so the guard could no longer fire on anything
    while still being advertised in ``process.md``. The digest is a reminder with the reasoning in
    ``decisions/``; past this length it has become the reasoning.
  DELIVERY_MAX_LINES: A delivery doc is "what shipped + what changed", typically under a page.
  FR_CEILING: How many Functional Requirements one spec may carry (``docs/process.md`` §4). Named
    here rather than inlined so the number that enforces the rule is discoverable from the
    constants block if the rule ever moves.
  SPEC_OVERSIZE_MAX: How many specs may carry more than eight Functional Requirements. A ratchet
    at the measured level, and the only budget here whose unit is the SPEC rather than the file.
    ``docs/process.md`` §4 caps a spec at eight FRs: past that it is not a big spec, it is a spec
    that should have been two, and the cure is a second spec beside it with the pair's build order
    in ``ARCS.md``. Making that a per-spec failure would red ``main`` on 41 specs written before
    the rule, so the count is held instead — a new over-size spec fails, the existing ones do not,
    and splitting one LOWERS this number in the same PR. A genuinely indivisible spec may still sit
    above eight, but it is paid for out of this ratchet rather than waved through, which is what
    makes the trade visible.
  STATUS_WORDS: Words that must not appear in an ``ARCS.md`` arc heading. Status lives in
    ``INDEX.md``, which is the only place it can be kept true.
  SOURCE_TREES: Where source lives, per language, for the citation check.
  CITATION_RE: A spec, PR or issue citation in a comment, including a bare requirement number.
    Matched on the whole line rather than on comment syntax, because four languages' comment
    markers is four ways to miss one. ``FR-005`` is in the set because 429 of them survived a
    sweep that looked only for ``SPEC-``, and a requirement number without its spec is strictly
    less useful than the citation it hung off. The PR form is bounded at four digits: unbounded, it
    matches a six-digit hex colour such as the palette tokens in the Data Explorer.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every tree that holds prose docs, for the link and path checks below. ``docs/`` is the
#: cross-cutting one; the rest sit beside the code they describe, so the doc is found by whoever is
#: standing in the tree rather than by remembering a central path. A tree missing from this list is
#: not an error anywhere — it is simply unchecked, which is how a moved doc silently stops being
#: link-checked. Add the tree in the same commit that creates it.
DOC_TREES = ("docs", "apps/portal/info", "lambdas/info", "infra/info", "infra/modules")

TESTING_PERMANENT = frozenset({"e2e.md", "owed.md", "sessions.md"})
TESTING_INFLIGHT_MAX = 1

FIXTURES_MAX_SCRIPTS = 1
CLAUDE_MAX_BYTES = 50_000
DIGEST_MAX_CHARS = 1_400
DELIVERY_MAX_LINES = 260
FR_CEILING = 8
SPEC_OVERSIZE_MAX = 41
def decision_areas() -> list[str]:
    """Read the areas ``CLAUDE.md``'s Key Decisions digest groups by, in order.

    DERIVED, never transcribed. A hard-coded copy of these eight strings is what this function
    replaced, and it had already drifted: one area's wording differed from the heading it claimed to
    mirror, while the docstring beside it asserted the two agreed. That is the failure mode a second
    copy always has — the copy is not checked against the original, so the claim of agreement is the
    only thing holding, and a claim is not a check.

    Args:
      None.

    Returns:
      The area labels, in the order the digest declares them.

    Raises:
      None.
    """
    lines = (ROOT / "CLAUDE.md").read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## Key Decisions"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    return [line[4:].strip() for line in lines[start:end] if line.startswith("### ")]


STATUS_WORDS = ("shipped", "complete", "active", "draft", "in progress", "filed", "scoped")
SOURCE_TREES = (("apps/portal/src", (".ts", ".tsx")), ("lambdas", (".py",)), ("infra", (".tf", ".tftpl")))
CITATION_RE = re.compile(r"SPEC-\d{3}|(?<![\w#])#\d{3,4}(?![\w])|\b(?:FR|AC)-?\d+\b")


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


def check_fixture_scripts() -> list[str]:
    """Refuse a per-SPEC script in ``docs/testing/fixtures/``, and cap how many exist.

    The directory holds the CLI checks a signed-in browser session cannot run. Its regrowth
    pressure is the same one that took ``docs/testing/`` to sixteen files, arriving one spec at a
    time: each spec in an arc owes a check, each check needs a token, a queue URL, a group digest
    and an envelope, and copying the previous spec's script is the path of least resistance. Four
    copies later the digest is computed four ways and only one of them is right.

    So the unit is the PLANE. A spec adds a SECTION to its plane's script and points its
    ``owed.md`` row at that section.

    Args:
      None.

    Returns:
      One message per offending file, plus one if the directory has grown, empty when it has not.

    Raises:
      None.
    """
    fixtures = ROOT / "docs" / "testing" / "fixtures"
    if not fixtures.is_dir():
        return []
    scripts = sorted(p.name for p in fixtures.glob("*.sh"))
    errors = [
        f"docs/testing/fixtures/{name} is named after a SPEC. These scripts are per PLANE — four "
        "specs build one plane, and a file each is four copies of one token read, one queue URL "
        "and one group digest. Add a section to the plane's script and point the owed.md row at it."
        for name in scripts
        if re.match(r"spec-\d+", name)
    ]
    if len(scripts) > FIXTURES_MAX_SCRIPTS:
        errors.append(
            f"docs/testing/fixtures/ holds {len(scripts)} scripts ({', '.join(scripts)}) against a "
            f"ratchet of {FIXTURES_MAX_SCRIPTS}. If a second PLANE genuinely needs one, raise the "
            "ratchet in this file deliberately; do not let the directory grow a spec at a time."
        )
    return errors


def check_claude_budget() -> list[str]:
    """Hold the always-loaded file, and each Key Decisions line, to their budgets.

    Both numbers are ratchets at the measured level. A digest line past the cap has stopped
    being a reminder and become the reasoning, which belongs in ``decisions/``.

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
            "session: move the detail into docs/ behind a pointer. This cap was raised once, "
            "deliberately, so a closing spec was not forced to prune another area's fences — see "
            "CLAUDE_MAX_BYTES above. Raising it again is not the answer; both previous fixes were "
            "structural cuts."
        )
    section = text[text.index("## Key Decisions") : text.index("## Out of Scope")]

    # JOINED, because the section is wrapped prose. Measuring the physical line stopped meaning
    # anything when the per-spec list became area blocks: the longest line fell from 846 characters
    # to 103, and a guard that cannot fire is worse than none — it is advertised in process.md.
    bullets, current = [], None
    for line in section.split("\n"):
        if line.startswith("- "):
            if current is not None:
                bullets.append(current)
            current = line
        elif current is not None:
            if line.startswith("  ") and line.strip():
                current += " " + line.strip()
            else:
                bullets.append(current)
                current = None
    if current is not None:
        bullets.append(current)

    for bullet in bullets:
        if len(bullet) > DIGEST_MAX_CHARS:
            errors.append(
                f"A Key Decisions bullet is {len(bullet)} chars (cap {DIGEST_MAX_CHARS}): "
                f"{bullet[:70]}… — keep the claim and the fence here, the reasoning in decisions/."
            )
    return errors


def check_decisions_register() -> list[str]:
    """Require one register file per AREA, one heading level per entry, and a reaching Contents.

    The register is pulled entry by entry, so an entry outside its file's Contents is only findable
    by reading the whole file — which is the cost the layering exists to avoid.

    The areas are a CLOSED set, and they are the same eight the ``CLAUDE.md`` digest groups by. That
    is the point of checking them: the digest is never the only home of a fact, so a reader who finds
    an area there must find the same area here. The register was ONE file ordered by spec number
    until 2026-08-28, which made it read as a changelog and feel disposable; it is now one file per
    area under ``docs/decisions/``, routed by ``INDEX.md``. An area file that exists under no digest
    heading, or a digest heading with no file, is the first step back to a register nobody can look
    something up in.

    Args:
      None.

    Returns:
      One message per unlisted entry, per unknown area file, per missing area file and per entry
      sitting above its file's Contents.

    Raises:
      None.
    """
    register = ROOT / "docs" / "decisions"
    errors = []

    expected_areas = decision_areas()
    if not expected_areas:
        errors.append("CLAUDE.md: no '### ' area headings under Key Decisions — the digest lost its grouping")

    index = register / "INDEX.md"
    if not index.exists():
        return [*errors, "docs/decisions/: INDEX.md is missing — the register has no router"]

    files = sorted(p for p in register.glob("*.md") if p.name != "INDEX.md")
    titles: dict[str, pathlib.Path] = {}
    for path in files:
        first = path.read_text().split("\n", 1)[0]
        if not first.startswith("# "):
            errors.append(f"{path.relative_to(ROOT)}: does not open with an '# Area' heading")
            continue
        area = first[2:].strip()
        if area in titles:
            errors.append(
                f"{path.relative_to(ROOT)}: '{area}' is already held by {titles[area].name}. Two files "
                "claiming one area means one of them is unreachable, and nothing else here would notice."
            )
            continue
        titles[area] = path

    for area in titles:
        if area not in expected_areas:
            errors.append(
                f"docs/decisions/{titles[area].name}: '{area}' is not one of the areas CLAUDE.md's "
                f"digest groups by. Add it there first, or file the entry under an existing one: {expected_areas}"
            )
    index_text = index.read_text()
    for expected in expected_areas:
        if expected not in titles:
            errors.append(f"docs/decisions/: no file holds the '{expected}' area")
        if expected not in index_text:
            errors.append(f"docs/decisions/INDEX.md: the '{expected}' area is not routed")

    # The INDEX and the digest are read as parallel lists, so they are checked as parallel lists.
    # Membership alone lets the two orders drift apart while both still "agree".
    routed = [a for _, a in sorted((index_text.index(a), a) for a in expected_areas if a in index_text)]
    if routed != [a for a in expected_areas if a in index_text]:
        errors.append(
            "docs/decisions/INDEX.md: the areas are routed in a different order from CLAUDE.md's "
            f"digest. Digest order: {expected_areas}"
        )

    for path in files:
        lines = path.read_text().split("\n")
        contents_at = next((i for i, line in enumerate(lines) if line.strip() == "## Contents"), None)
        if contents_at is None:
            errors.append(f"{path.relative_to(ROOT)}: has no '## Contents' — the file is only readable whole")
            continue
        listed = set(re.findall(r"\]\(#([^)]+)\)", "\n".join(lines)))
        seen: dict[str, int] = {}
        for i, line in enumerate(lines):
            if not line.startswith("## ") or line.strip() == "## Contents":
                continue
            heading = line[3:].strip()
            if i < contents_at:
                errors.append(f"{path.relative_to(ROOT)}: '{heading}' sits above the Contents")
            base = anchor(heading)
            seen[base] = seen.get(base, 0) + 1
            target = base if seen[base] == 1 else f"{base}-{seen[base] - 1}"
            if target not in listed:
                errors.append(f"{path.relative_to(ROOT)}: '{heading}' is not in the Contents (anchor #{target})")
        headings = {
            anchor(line[3:].strip())
            for line in lines[contents_at:]
            if line.startswith("## ") and line.strip() != "## Contents"
        }
        for target in sorted(listed):
            if target.rstrip("-0123456789") not in headings and target not in headings:
                errors.append(
                    f"{path.relative_to(ROOT)}: the Contents links to #{target}, which is no entry in "
                    "this file — the entry was moved or deleted and its listing was left behind"
                )
        for line in lines:
            if line.startswith("### "):
                errors.append(
                    f"{path.relative_to(ROOT)}: '{line[4:].strip()}' is a second heading level — "
                    "every entry sits at '##' so the Contents reaches all of them"
                )
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


def check_spec_size() -> list[str]:
    """Hold the number of over-size specs at the level it was measured at.

    A spec is one coherent slice of behavior (``docs/process.md`` §4): aim 3-6 Functional
    Requirements, and past eight write a second spec beside the first rather than growing one.
    Across these specs the median carries six FRs and four in five carry eight or fewer, so the
    ones above the line are a tail rather than the norm — which is why this is a ratchet on the
    COUNT and not a failure per spec.

    FRs are counted as distinct ``### FR-NNN`` headings outside fenced blocks and HTML comments.
    Both exclusions are load-bearing: a spec that quotes FR headings in an example, or comments
    some out while splitting, would otherwise be told to split on requirements it does not have.

    Args:
      None.

    Returns:
      One message naming the over-size specs when the count exceeds the ratchet, else none.

    Raises:
      None.
    """
    fence = re.compile(r"^\s*```")
    heading = re.compile(r"^### (FR-\d+)")
    oversize: list[tuple[str, int]] = []
    unparsed: list[str] = []
    for path in sorted((ROOT / "docs" / "specs").glob("SPEC-*.md")):
        ids, in_fence, in_comment = set(), False, False
        for line in path.read_text().splitlines():
            if fence.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if in_comment:
                in_comment = "-->" not in line
                continue
            if "<!--" in line:
                in_comment = "-->" not in line
                continue
            found = heading.match(line)
            if found:
                ids.add(found.group(1))
        if not ids:
            unparsed.append(path.name)
        if len(ids) > FR_CEILING:
            oversize.append((path.name, len(ids)))
    # A ratchet sitting exactly at its threshold goes vacuous the moment the parse stops
    # matching: every spec reads as zero FRs, nothing is over the ceiling, and the only
    # enforcement of \u00a74 passes forever with no signal. Every spec has FRs, so none may parse
    # to none.
    errors = [
        f"{name}: no '### FR-NNN' headings — the size ratchet cannot see this spec"
        for name in unparsed
    ]
    if len(oversize) <= SPEC_OVERSIZE_MAX:
        return errors
    return [
        *errors,
        (
            f"{len(oversize)} specs carry more than {FR_CEILING} FRs "
            f"(ratchet {SPEC_OVERSIZE_MAX}). The spec you just added is over the ceiling: "
            "split it into two and record the pair in ARCS.md (docs/process.md \u00a74). "
            "Naming which existing specs are over is deliberately left out — with several "
            "sitting exactly at the line, any list names innocent files rather than yours. "
            "Raising this number is the failure mode; splitting one lowers it."
        )
    ]


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
    in ``docs/decisions/`` — findable by what it says rather than by when it happened. A comment
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
    files = [ROOT / "README.md", ROOT / "CLAUDE.md"]
    for tree in DOC_TREES:
        files.extend(sorted((ROOT / tree).rglob("*.md")))
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
    scanned = [ROOT / "CLAUDE.md"]
    for tree in DOC_TREES:
        scanned.extend(sorted((ROOT / tree).rglob("*.md")))
    for path in scanned:
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
    skip = ("node_modules", ".terraform", "dist", "coverage", ".git", ".claude")
    pattern = re.compile(
        r"(?:" + "|".join(re.escape(tree) for tree in DOC_TREES) + r")/[A-Za-z0-9_./-]+\.md"
    )
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
        check_fixture_scripts,
        check_claude_budget,
        check_decisions_register,
        check_arcs,
        check_spec_status,
        check_spec_size,
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
