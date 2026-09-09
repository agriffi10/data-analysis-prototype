"""Hold the documentation layout to the shape it was cut back to on 2026-08-18.

Every rule below already existed in prose, in ``CLAUDE.md`` or ``docs/process/``, and every
one of them was violated anyway — ``## Specs`` regrew to 371 lines of changelog, the Key
Decisions digest grew entries of 3,349 characters against a stated "one line each",
``docs/testing/`` reached sixteen files of four different genres, ``decisions/`` listed 50
of its 149 entries in a Contents nobody regenerated, and four arc headings in ``ARCS.md``
carried a status that had gone stale. A rule a reader has to remember is a rule that rots;
this file is the same rules where CI can see them.

Budgets are RATCHETS AT THE MEASURED LEVEL, not targets — the convention SPEC-150 set for the
coverage floors. Lowering one when a doc grows is the failure mode; the fix is to move the
detail down a tier, which is what every budget here exists to force. A ratchet sits just
above the measurement, never exactly at it: a budget with nothing left to spend makes the gate
cause the damage it exists to prevent, and each entry below says how much room it leaves and
for what.

Runs on every pull request (``ci.yml``). Takes no arguments and imports nothing outside the
standard library.

Attributes:
  ROOT: The repository root, derived from this file's location.
  TESTING_PERMANENT: The three files ``docs/testing/`` always holds. Anything else there must
    be the ONE script an arc in flight is allowed, or a subdirectory.
  TESTING_INFLIGHT_MAX: How many temporary per-arc scripts may exist at once. One. An arc
    folds its script into ``e2e.md`` when it closes (``docs/process/completion-ritual.md``, step 8). Only a
    ``*-e2e.md`` name counts as one — a dated session file is refused on its name alone, and
    does not merely consume the slot, because the slot may be free.
  FIXTURES_MAX_SCRIPTS: How many CLI check scripts ``docs/testing/fixtures/`` may hold. A
    ratchet at the measured level, and the unit is the PLANE: four specs build one control
    plane, and a script each would be four files sharing a token, a queue URL, a group digest
    and an envelope builder. A spec that owes a CLI check adds a SECTION to its plane's script.
    Raised to 2 on 2026-09-06 for results-conversion, which qualifies on the same criterion
    file-ops did and for a reason its own spec states as scope: SPEC-221 and SPEC-222 both ship
    "nothing a user can reach", so a conversion is an authenticated POST rather than a click
    until SPEC-223 gives the plane a browser surface. Both scripts shrink when their planes get
    one — a raise here is a deliberate edit, and so is the reduction that should follow.
  CLAUDE_MAX_BYTES: The always-loaded file's budget. The file has been cut structurally five
    times, and the fifth (2026-09-05) changed its shape: the Key Decisions digest left it
    altogether — each area's fences now head that area's ``docs/decisions/<area>.md`` under a
    ``## Fences`` entry, and CLAUDE.md keeps an eight-row table pointing at them — and the method
    it points to became ``docs/process/``, a router and one file per part. Before that cut the
    file carried deliberate headroom, because the completion ritual folded a clause into it on
    every architectural close and a ratchet at the measured level made each close a forced prune
    of another area's fences (it happened once; #568 is titled for the prune it forced). The fold
    now lands in the area file, so that reason is gone. What still grows this file is a Tech Stack
    row when a dependency is added and the ``## Specs`` current-work paragraph, so the ratchet sits
    above the measurement by roughly two Tech Stack rows and one such paragraph, and no more. Past that the answer is a cut, never a raise: every one of the five was
    structural, and the next candidate is the conventions block, which a rulebook already carries
    in full. The measured size is deliberately not written here — it is a property of the file
    beside this one, and any edit would falsify it.
  PROCESS_MAX_BYTES: The budget on the other always-loaded files together — the ``docs/process/``
    files the router's "Loaded every session" table names, today the router itself and the
    session rhythm, the one part of the method every session reads. CLAUDE.md's first instruction is to read them, so their
    size is a per-session cost exactly like CLAUDE.md's. Nothing bounded the method until
    2026-09-01, when a single-file budget caught it slightly larger than the file that had been
    cut three times; four days later the split above made every other part of it on-demand. A
    ratchet just above the measured level: nothing mandates appending to either file, so under
    byte pressure defer the addition, or move a paragraph into one of the on-demand parts behind
    a pointer. Raising this number so a grown file passes is the failure the gate exists to catch.
  DIGEST_MAX_CHARS: The longest a single Fences bullet may be, measured on the LOGICAL bullet —
    continuation lines joined — under the ``## Fences`` entry of each register area file, where
    the CLAUDE.md digest now lives. It was measured per physical line until 2026-08-26, which
    stopped meaning anything the moment the section was rewritten as wrapped prose: the longest
    physical line went from 846 characters to 103, so the guard could no longer fire on anything
    while still being advertised as a fence. A fence is a reminder with the reasoning in the
    entries beneath it; past this length it has become the reasoning.
  PROCESS_ROUTER: The ``docs/process/`` router. Its "Loaded every session" table is the ONE
    statement of which process files every session reads, and ``always_loaded_process`` derives
    the pair ``PROCESS_MAX_BYTES`` bounds from it rather than transcribing it — a transcribed copy
    passed a plant that added a third row to the table. Its method table is the closed set of
    process files, held the way the register's areas are.
  RULE_BODY: The whole body of a ``.claude/rules/<area>.md``, rendered per area. A committed
    rule reaches every teammate's session on any Read of a matching file, so the body is held
    EQUAL to this template rather than merely short: a length cap leaves room for a line that is
    not a pointer, and a template does not.
  DELIVERY_MAX_LINES: A delivery doc is "what shipped + what changed", typically under a page.
  FR_CEILING: How many Functional Requirements one spec may carry (``docs/process/authoring-a-spec.md``). Named
    here rather than inlined so the number that enforces the rule is discoverable from the
    constants block if the rule ever moves.
  SPEC_OVERSIZE_MAX: How many specs may carry more than eight Functional Requirements. A ratchet
    at the measured level, and the only budget here whose unit is the SPEC rather than the file.
    ``docs/process/authoring-a-spec.md`` caps a spec at eight FRs: past that it is not a big spec, it is a spec
    that should have been two, and the cure is a second spec beside it with the pair's build order
    in ``ARCS.md``. Making that a per-spec failure would red ``main`` on 41 specs written before
    the rule, so the count is held instead — a new over-size spec fails, the existing ones do not,
    and splitting one LOWERS this number in the same PR. A genuinely indivisible spec may still sit
    above eight, but it is paid for out of this ratchet rather than waved through, which is what
    makes the trade visible.
  SPEC_REQUIRED_SECTIONS: The four top-level sections every live spec carries, matched
    case-insensitively on the heading's first words. They are the template's skeleton, and a spec
    missing one is a spec whose reader cannot find the scope or the phases without reading it whole.
  SPEC_BANNED_HEADINGS: Heading text, at any level, that a spec may not carry. An Open Question is
    resolved while authoring (``docs/process/authoring-a-spec.md``) and a Checkpoint is the
    per-phase approval the session rhythm retired; either parked in the spec is a decision deferred
    to whoever builds it.
  SPEC_PLACEHOLDERS: The template's unfilled markers, reported as a WARNING wherever they appear.
    ``YYYY-MM-DD`` is deliberately not in this tuple: three specs describe a date format in prose,
    so that marker is looked for on the ``**Last Updated:**`` header line and nowhere else.
  SPEC_SHAPE_EXEMPT: The statuses ``check_spec_shape`` does not judge. The Completed specs written
    from an earlier template carry its retired ``#### Checkpoint`` and ``## Open Questions``
    headings — sixty closed specs would fail at the commit that introduced the check, and a reader
    can re-measure that by emptying this set — and a Cancelled spec is reduced to a tombstone with
    no sections to require (``docs/process/spec-lifecycle.md``). The exemption keys on the Status header alone and
    fails CLOSED: a spec with no readable status, or any status outside this set — Draft, In
    Progress, Superseded, a misspelling — is judged in full.
  WARNING: The prefix a check puts on a finding that is reported but does not fail the run. The
    exit code is decided by the findings without it.
  STATUS_WORDS: Words that must not appear in an ``ARCS.md`` arc heading. Status lives in
    ``INDEX.md``, which is the only place it can be kept true.
  SOURCE_TREES: Where source lives, per language, for the citation check.
  CITATION_RE: A spec, PR or issue citation in a comment, including a bare requirement number.
    Matched on the whole line rather than on comment syntax, because four languages' comment
    markers is four ways to miss one. ``FR-005`` is in the set because 429 of them survived a
    sweep that looked only for ``SPEC-``, and a requirement number without its spec is strictly
    less useful than the citation it hung off. The PR form is bounded at four digits: unbounded, it
    matches a six-digit hex colour such as the palette tokens in the Data Explorer.
  TEST_CITATION_SCAN: The file types a test citation is looked for in. Markdown is in the set
    because a doc naming a guard makes the same promise a comment does, and Vitest ``*.test.tsx``
    files are deliberately NOT excluded — they carry four citations to Python tests, one of which
    names a test that no longer exists. Workflows and shell scripts are in it for the same reason
    a comment is: measured, they hold 12 citations, all of which resolve today, so the set costs
    nothing and closes a place a promise could be made unwatched.
  TEST_CITATION_WINDOW: How far either side of a citation a retirement record is looked for, in
    characters. Measured by binary search against the tree: the furthest record puts its verb 82
    characters past the citation, on the following line, so 81 drops it and 82 does not. It is not
    a budget with headroom to spend — widening it buys FALSE EXEMPTIONS, and widening it to the
    whole file was measured to drop 17 of this repo's findings in silence. A retirement verb in a
    neighbouring sentence within this distance will exempt a live citation; measured, that happens
    nowhere today. The corpus pins BOTH edges — the tree pins the low side at 82, and a fixture
    whose verb sits just past this number pins the high side — because an upper edge left to the
    tree alone is not pinned at all: nothing in a repository objects to being exempted.
  TEST_CITATION_GRAMMARS: The three forms a citation is written in, held as a POSITIVE CONTROL:
    each must match at least once per run. The reason is ``check_spec_size``'s — a ratchet at zero
    goes vacuous the moment the scan stops matching, and a scan finding nothing then looks exactly
    like a repository with nothing wrong. A global floor was the other option and the weaker one:
    only 11 of 255 sites are written bare and nowhere else, so that form could go dead in full
    while any plausible floor still passed. Paying the debt down does not remove sites — a
    repaired citation still cites — so this control does not weaken as the ratchet falls.
  TEST_CITATION_MAX: How many citations may name a test that does not exist. A ratchet at the
    measured level, and the one budget here whose end state is ZERO with no headroom: every unit
    it counts is a defect rather than a legitimate cost, so room to spare would be permission to
    add one. The single legitimate case that reaches a zero ratchet is a retirement record worded
    outside ``RETIREMENT_RE``, and the answer to that is to reword it, never to raise this.
"""

import fnmatch
import os
import pathlib
import re
import sys
import typing

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every tree that holds prose docs, for the link and path checks below. ``docs/`` is the
#: cross-cutting one; the rest sit beside the code they describe, so the doc is found by whoever is
#: standing in the tree rather than by remembering a central path. A tree missing from this list is
#: not an error anywhere — it is simply unchecked, which is how a moved doc silently stops being
#: link-checked. Add the tree in the same commit that creates it.
DOC_TREES = ("docs", "apps/portal/info", "lambdas/info", "infra/info", "infra/modules")

#: Directories no walk in this file descends into. `.terraform` holds a vendored copy of every
#: provider, each with its own README and CHANGELOG carrying links this repo does not own —
#: measured, twelve dangling links across four provider READMEs. It is gitignored, so it never
#: reaches CI, which is exactly why this was easy to miss: the gate every reviewer is told to run
#: locally breaks the moment anyone runs `tofu init` inside a module directory, and it breaks with
#: a message about a link in HashiCorp's changelog.
#:
#: ONE TUPLE. `check_doc_paths_everywhere` had its own differently-spelled copy of this rule, which
#: is how the two came to disagree — the markdown walks skipped nothing while the source walk
#: skipped six directories.
VENDORED = (".terraform", "node_modules", "__pycache__", ".venv", "dist", "coverage", ".git", ".claude")



def _docs_in(tree):
    """Every markdown file in a doc tree, skipping vendored directories.

    Args:
      tree: A path relative to the repository root.

    Returns:
      The markdown files, sorted.

    Raises:
      None.
    """
    return sorted(
        path
        for path in (ROOT / tree).rglob("*.md")
        if not any(part in VENDORED for part in path.relative_to(ROOT).parts)
    )

TESTING_PERMANENT = frozenset({"e2e.md", "owed.md", "sessions.md"})
TESTING_INFLIGHT_MAX = 1

FIXTURES_MAX_SCRIPTS = 2
CLAUDE_MAX_BYTES = 17_000
PROCESS_MAX_BYTES = 15_000
DIGEST_MAX_CHARS = 1_400
DELIVERY_MAX_LINES = 260
FR_CEILING = 8
SPEC_OVERSIZE_MAX = 40
def decision_table() -> list[tuple[str, str]]:
    """Read the Key Decisions table in ``CLAUDE.md``: each area, and the register file it points at.

    DERIVED, never transcribed. A hard-coded copy of the eight area strings is what this replaced,
    and it had already drifted: one area's wording differed from the heading it claimed to mirror,
    while the docstring beside it asserted the two agreed. That is the failure mode a second copy
    always has — the copy is not checked against the original, so the claim of agreement is the
    only thing holding, and a claim is not a check. The table is the authority for the closed set
    of areas AND their order; the register's INDEX and the rules directory are held to it.

    Args:
      None.

    Returns:
      ``(area, target)`` pairs in table order, where ``target`` is the link path as written
      (``docs/decisions/<area>.md#fences``).

    Raises:
      None.
    """
    lines = (ROOT / "CLAUDE.md").read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## Key Decisions"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    rows = []
    for line in lines[start:end]:
        match = re.match(r"^\|\s*(?P<area>[^|]+?)\s*\|\s*\[[^\]]+\]\((?P<target>[^)]+)\)\s*\|$", line)
        if match and match.group("area") not in ("Area", "---"):
            rows.append((match.group("area"), match.group("target")))
    return rows


def decision_areas() -> list[str]:
    """The area labels ``CLAUDE.md``'s Key Decisions table declares, in its order.

    Args:
      None.

    Returns:
      The area labels, in table order.

    Raises:
      None.
    """
    return [area for area, _ in decision_table()]


SPEC_REQUIRED_SECTIONS = ("## Overview", "## Scope", "## Functional Requirements", "## Implementation Phases")
SPEC_BANNED_HEADINGS = ("Open Questions", "Checkpoint")
SPEC_PLACEHOLDERS = ("[Feature Name]", "[Requirement Name]", "SPEC-XXX")
SPEC_SHAPE_EXEMPT = frozenset({"completed", "cancelled"})
WARNING = "warning: "
STATUS_WORDS = ("shipped", "complete", "active", "draft", "in progress", "filed", "scoped")
SOURCE_TREES = (("apps/portal/src", (".ts", ".tsx")), ("lambdas", (".py",)), ("infra", (".tf", ".tftpl")))
CITATION_RE = re.compile(r"SPEC-\d{3}|(?<![\w#])#\d{3,4}(?![\w])|\b(?:FR|AC)-?\d+\b")
#: A cited test name. The character class carries UPPERCASE deliberately: 290 names in the
#: population have a capital in them, and a lowercase-only class truncates the longest of them
#: mid-word and then reports the stub it made as an unresolved citation.
TEST_NAME_RE = re.compile(r"\btest_[A-Za-z0-9_]+")

#: A citation written as a filename. Matched separately so the name resolves against a FILE as
#: well as a function — a citation naming a module names a module-wide sweep, not one assertion.
TEST_FILENAME_RE = re.compile(r"\btest_[A-Za-z0-9_]+\.py\b")

#: A code span, single or double backticked. The ``{1,2}`` is load-bearing, though not for the
#: reason it looks: a single-backtick pattern does not fail on ``x`` by matching an empty span —
#: ``[^`]+`` cannot match empty — it fails by treating the PROSE BETWEEN two double-backticked
#: names as a span of its own, and then losing the second name. Measured on ```` ``a`` then `b` ````
#: the single pattern returns ``a`` and `` then ``, and never sees ``b``.
CODE_SPAN_RE = re.compile(r"`{1,2}([^`]+)`{1,2}")

#: A code span left OPEN at end of line whose content has already reached ``test_``. This is the
#: only place lines are rejoined, and it is deliberately narrow: joining on any unclosed backtick
#: would fuse prose all over the tree, while this shape is exactly a citation that wrapped.
WRAPPED_CITATION_RE = re.compile(r"`[^`]*test_[A-Za-z0-9_]*$")

#: The start of a trailing comment. Two markers rather than a per-language table, for the reason
#: ``CITATION_RE`` gives: four languages' comment syntax is four ways to miss one.
COMMENT_START_RE = re.compile(r"#|//")

#: A past-tense retirement, sought in a window either side of a citation — a record of a guard
#: that is gone is legitimate prose, not a stale claim. ONE mechanism, and the window looks
#: BOTH ways because the four records in this repo put the verb on either side and one puts it
#: on the following line, 90 characters along. Retirement
#: words ONLY. `delete` and `remove` are deliberately absent, and that is not fastidiousness: this
#: repo is full of live sentences about deletion semantics, and admitting those two words would
#: exempt three of the findings this check was written to report — among them a manifest sweep and
#: a queue drain, each of which describes deleting and cites a test that does not exist.
RETIREMENT_RE = re.compile(r"retir(?:e|es|ed|ing|ement)\b", re.IGNORECASE)

TEST_CITATION_SCAN = (".py", ".tf", ".tftpl", ".ts", ".tsx", ".md", ".yml", ".yaml", ".sh")
TEST_CITATION_WINDOW = 100
TEST_CITATION_GRAMMARS = ("bare in a comment", "code span", "filename")


class Citations(typing.NamedTuple):
    """What one file cites: the deduped sites, and the grammar of every match behind them.

    Two fields rather than one list because they answer different questions. ``sites`` is the
    finding list, so a name written twice on one line is one finding. ``grammars`` is the
    positive control's input, so it counts matches rather than findings — a tally taken after
    the dedup measures which grammar saw a name FIRST, which is not the same as which grammars
    still work.

    Attributes:
      sites: ``(line number, name, exempt)`` per distinct name per line.
      grammars: The form of every match, before that dedup. A list rather than a set because the
        caller unions them across files, and because recording only the FIRST grammar per site was
        the bug this field exists to avoid.
    """

    sites: list[tuple[int, str, bool]]
    grammars: list[str]
TEST_CITATION_MAX = 11


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


PROCESS_ROUTER = "docs/process/INDEX.md"


def _router_section(heading: str) -> list[str]:
    """The lines of one ``## `` section of the process router, or ``[]`` if it has no such section.

    Args:
      heading: The section heading without its ``## ``.

    Returns:
      The lines after the heading up to the next ``## `` heading.

    Raises:
      None.
    """
    path = ROOT / PROCESS_ROUTER
    if not path.exists():
        return []
    lines = path.read_text().split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == f"## {heading}"), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1 : end]


def always_loaded_process() -> list[str]:
    """The ``docs/process/`` files the router's "Loaded every session" table says every session reads.

    DERIVED from the router, never transcribed: the table is the human-readable statement of the
    set and the budget must bound what it says, or a row added there is a file nothing measures.

    Args:
      None.

    Returns:
      Root-relative paths, in table order; the router itself when the table names nothing.

    Raises:
      None.
    """
    found = []
    for line in _router_section("Loaded every session"):
        for match in re.finditer(r"`(docs/process/[A-Za-z0-9_.-]+\.md)`", line):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found or [PROCESS_ROUTER]


def check_process_budget() -> list[str]:
    """Hold the always-loaded process files, together, to their budget.

    CLAUDE.md's first instruction is to read them, so they load every session and their size is
    the same kind of cost. The remedy is the one that has worked five times on CLAUDE.md: move a
    paragraph into one of the on-demand parts behind a pointer, never trim the reasoning in place.
    A missing file is its own error rather than a smaller total — the router names both as
    always-loaded, and a router pointing at nothing is the rot this file exists to catch.

    Args:
      None.

    Returns:
      One message per missing file, and one when the pair is over budget; empty otherwise.

    Raises:
      None.
    """
    errors = []
    size = 0
    for rel in always_loaded_process():
        path = ROOT / rel
        if not path.exists():
            errors.append(f"{rel} is missing — the router's 'Loaded every session' table names it")
            continue
        size += len(path.read_text().encode())
    if errors or size <= PROCESS_MAX_BYTES:
        return errors
    return [
        (
            f"docs/process/ always-loaded pair is {size:,} bytes against a {PROCESS_MAX_BYTES:,} "
            "budget. CLAUDE.md's first instruction is to read the router and session-rhythm.md, so "
            "they cost every session what CLAUDE.md costs: move a paragraph into one of the "
            "on-demand parts behind a pointer. See PROCESS_MAX_BYTES above."
        )
    ]


def check_process_router() -> list[str]:
    """Require every ``docs/process/`` file to be a row of the router's method table, and every row a file.

    The router calls its table "one file per part", and that is a closed-set claim of the same
    kind the register makes for its areas: a process file the router does not route is
    unreachable from the only place a session is told to look, and it is exactly where the next
    process paragraph would accrete unread.

    Args:
      None.

    Returns:
      One message per unrouted file and per routed name with no file behind it.

    Raises:
      None.
    """
    process = ROOT / "docs" / "process"
    if not (ROOT / PROCESS_ROUTER).exists():
        return [f"{PROCESS_ROUTER} is missing — the process directory has no router"]
    routed = []
    for line in _router_section("The method, one file per part"):
        routed.extend(re.findall(r"\]\(([A-Za-z0-9_.-]+\.md)\)", line))
    errors = [
        f"docs/process/{name} is routed by the router's table but does not exist"
        for name in routed
        if not (process / name).exists()
    ]
    errors.extend(
        f"docs/process/{path.name} is not a row of the router's method table — a part the router does not route is a part nobody is told to read"
        for path in sorted(process.glob("*.md"))
        if path.name != "INDEX.md" and path.name not in routed
    )
    return errors


def check_claude_budget() -> list[str]:
    """Hold the always-loaded file to its budget.

    A ratchet just above the measured level, with the headroom ``CLAUDE_MAX_BYTES`` names and no
    more. What used to grow this file — the Key Decisions digest — now heads each register area
    file and is measured there (``check_fences``).

    Args:
      None.

    Returns:
      One message when the file is over budget, empty otherwise.

    Raises:
      None.
    """
    size = len((ROOT / "CLAUDE.md").read_text().encode())
    if size <= CLAUDE_MAX_BYTES:
        return []
    return [
        (
            f"CLAUDE.md is {size:,} bytes against a {CLAUDE_MAX_BYTES:,} budget. It loads every "
            "session: move the detail into docs/ behind a pointer. Every previous fix was a "
            "structural cut, and the headroom this budget carries is sized for a Tech Stack row and "
            "a current-work paragraph, not for a new section — see CLAUDE_MAX_BYTES above."
        )
    ]


def _logical_bullets(lines: list[str]) -> list[str]:
    """Join wrapped bullet continuations so a bullet is measured whole.

    Measuring the physical line stopped meaning anything when the digest became wrapped prose:
    the longest line fell from 846 characters to 103, and a guard that cannot fire is worse than
    none — it is advertised as a fence.

    Args:
      lines: The lines of one section.

    Returns:
      One string per ``- `` bullet, continuation lines appended with a space.

    Raises:
      None.
    """
    bullets: list[str] = []
    current = None
    for line in lines:
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
    return bullets


def fences_section(path: pathlib.Path) -> list[str] | None:
    """The lines of a register file's ``## Fences`` entry, or ``None`` when it has no such entry.

    Args:
      path: A ``docs/decisions/<area>.md`` file.

    Returns:
      The lines between ``## Fences`` and the next ``## `` heading, heading excluded; ``None`` if
      the file carries no Fences entry.

    Raises:
      None.
    """
    lines = path.read_text().split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == "## Fences"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1 : end]


def check_fences() -> list[str]:
    """Require each register area to open with its Fences, reachable from the CLAUDE.md table.

    The fences are the traps that apply green and fail later. They were CLAUDE.md's always-loaded
    digest until 2026-09-05; they now head the area file that carries their reasoning, and the
    CLAUDE.md table is how a session reaches them. So: every table row resolves to a file whose
    first entry after its Contents is ``## Fences``, listed first in that Contents, and every
    bullet under it is a reminder rather than the reasoning — ``DIGEST_MAX_CHARS`` on the logical
    bullet. A Fences entry that is not first is the register's old shape coming back, where the
    fence is somewhere in a file nobody reads whole.

    Args:
      None.

    Returns:
      One message per table row that does not resolve, per area file whose Fences is missing or
      not first, and per over-long bullet.

    Raises:
      None.
    """
    errors = []
    for area, target in decision_table():
        rel, _, fragment = target.partition("#")
        path = ROOT / rel
        if fragment != "fences" or not path.exists():
            errors.append(f"CLAUDE.md: the '{area}' row points at {target}, which is not an existing file's #fences")
            continue
        lines = path.read_text().split("\n")
        contents_at = next((i for i, line in enumerate(lines) if line.strip() == "## Contents"), None)
        if contents_at is None:
            continue  # check_decisions_register reports the missing Contents
        first_item = next((line for line in lines[contents_at + 1 :] if line.startswith("- [")), "")
        if first_item.strip() != "- [Fences](#fences)":
            errors.append(f"{rel}: the Contents does not list [Fences](#fences) first")
        first_entry = next((line for line in lines[contents_at + 1 :] if line.startswith("## ")), "")
        if first_entry.strip() != "## Fences":
            errors.append(
                f"{rel}: the first entry after the Contents is '{first_entry[3:].strip()}', not 'Fences' — "
                "the fences head the file so a session reads them before the area's code"
            )
        for bullet in _logical_bullets(fences_section(path) or []):
            if len(bullet) > DIGEST_MAX_CHARS:
                errors.append(
                    f"{rel}: a Fences bullet is {len(bullet)} chars (cap {DIGEST_MAX_CHARS}): "
                    f"{bullet[:70]}… — keep the claim and the fence here, the reasoning in the entries below."
                )
    return errors


def check_decisions_register() -> list[str]:
    """Require one register file per AREA, one heading level per entry, and a reaching Contents.

    The register is pulled entry by entry, so an entry outside its file's Contents is only findable
    by reading the whole file — which is the cost the layering exists to avoid.

    The areas are a CLOSED set, and they are the rows of ``CLAUDE.md``'s Key Decisions table. That
    is the point of checking them: the table is how a session reaches an area's fences, so a reader
    who finds an area there must find the same area here. The register was ONE file ordered by spec number
    until 2026-08-28, which made it read as a changelog and feel disposable; it is now one file per
    area under ``docs/decisions/``, routed by ``INDEX.md``. An area file that exists under no table
    row, or a table row with no file, is the first step back to a register nobody can look
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
        errors.append("CLAUDE.md: no area rows in the Key Decisions table — the register has no closed set")

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
                f"docs/decisions/{titles[area].name}: '{area}' is not one of the areas in CLAUDE.md's "
                f"Key Decisions table. Add a row there first, or file the entry under an existing one: {expected_areas}"
            )
    index_text = index.read_text()
    for expected in expected_areas:
        if expected not in titles:
            errors.append(f"docs/decisions/: no file holds the '{expected}' area")
        if expected not in index_text:
            errors.append(f"docs/decisions/INDEX.md: the '{expected}' area is not routed")

    # The INDEX and the table are read as parallel lists, so they are checked as parallel lists.
    # Membership alone lets the two orders drift apart while both still "agree".
    routed = [a for _, a in sorted((index_text.index(a), a) for a in expected_areas if a in index_text)]
    if routed != [a for a in expected_areas if a in index_text]:
        errors.append(
            "docs/decisions/INDEX.md: the areas are routed in a different order from CLAUDE.md's "
            f"Key Decisions table. Table order: {expected_areas}"
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


def spec_status(text: str) -> str | None:
    """A spec's Status header, lower-cased and stripped, or ``None`` when it has none.

    One reader for the three checks that key on it, so they cannot disagree about what counts as
    a status line.

    Args:
      text: The spec's full text.

    Returns:
      The status as written, normalised; ``None`` if no header parses.

    Raises:
      None.
    """
    found = re.search(r"^\**Status:?\**[:\s]*\**\s*([A-Za-z ]+)", text, re.MULTILINE)
    return found.group(1).strip().lower() if found else None


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """A spec's lines outside fenced blocks and HTML comments, each with its 1-based number.

    A comment closes before a fence opens, so a fence marker quoted inside a comment cannot
    swallow the rest of the file. A one-line ``<!-- ... -->`` is stripped rather than skipped, so a heading with
    a trailing note still counts. Both exclusions are load-bearing for every check that reads
    headings: a spec quoting a heading in an example, or commenting one out while splitting, would
    otherwise be judged on text it does not carry.

    Args:
      text: The spec's full text.

    Returns:
      ``(line number, line)`` pairs, in order, with inline comments removed.

    Raises:
      None.
    """
    fence = re.compile(r"^\s*(?:```|~~~)")
    inline_comment = re.compile(r"<!--[^>]*-->")
    kept: list[tuple[int, str]] = []
    in_fence = in_comment = False
    for number, raw in enumerate(text.splitlines(), 1):
        if in_comment:
            in_comment = "-->" not in raw
            continue
        if in_fence:
            if fence.match(raw):
                in_fence = False
            continue
        if fence.match(raw):
            in_fence = True
            continue
        line = inline_comment.sub("", raw)
        if "<!--" in line:
            in_comment = True
            continue
        kept.append((number, line))
    return kept


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
        stated = spec_status(path.read_text())
        if number not in rows:
            errors.append(f"{path.name} has no row in INDEX.md")
            continue
        if stated is None:
            errors.append(f"{path.name} has no Status header")
            continue
        indexed = rows[number].strip().lower()
        if not indexed.startswith(stated) and not stated.startswith(indexed):
            errors.append(f"{path.name}: header says '{stated}', INDEX.md says '{indexed}'")
        if stated == "completed" and not list(delivery.glob(f"SPEC-{number}-*.md")):
            errors.append(f"SPEC-{number} is Completed with no docs/spec-delivery/ write-up")
    return errors


def check_spec_size() -> list[str]:
    """Hold the number of over-size specs at the level it was measured at.

    A spec is one coherent slice of behavior (``docs/process/authoring-a-spec.md``): aim 3-6 Functional
    Requirements, and past eight write a second spec beside the first rather than growing one.
    Across these specs the median carries six FRs and four in five carry eight or fewer, so the
    ones above the line are a tail rather than the norm — which is why this is a ratchet on the
    COUNT and not a failure per spec.

    FRs are counted as distinct ``### FR-NNN`` headings outside fenced blocks and HTML comments
    (``_prose_lines``): a spec that quotes FR headings in an example, or comments some out while
    splitting, would otherwise be told to split on requirements it does not have.

    Args:
      None.

    Returns:
      One message naming the over-size specs when the count exceeds the ratchet, else none.

    Raises:
      None.
    """
    heading = re.compile(r"^### (FR-\d+)")
    oversize: list[tuple[str, int]] = []
    unparsed: list[str] = []
    for path in sorted((ROOT / "docs" / "specs").glob("SPEC-*.md")):
        text = path.read_text()
        if spec_status(text) == "cancelled":
            continue
        ids = set()
        for _, line in _prose_lines(text):
            found = heading.match(line)
            if found:
                ids.add(found.group(1))
        if not ids:
            unparsed.append(path.name)
        if len(ids) > FR_CEILING:
            oversize.append((path.name, len(ids)))
    # A ratchet sitting exactly at its threshold goes vacuous the moment the parse stops
    # matching: every spec reads as zero FRs, nothing is over the ceiling, and the only
    # enforcement of §4 passes forever with no signal. Every LIVE spec has FRs, so none may
    # parse to none. A CANCELLED one is skipped above rather than exempted here: it carries no
    # requirements to size, and reducing one to a tombstone pointing at where the work went is the
    # intended shape. The vacuity guard keeps its teeth over every spec that is still work.
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
            f"(ratchet {SPEC_OVERSIZE_MAX}). A spec in this PR crossed the ceiling — added "
            "or grown. Split it into two and record the pair in ARCS.md "
            "(docs/process/authoring-a-spec.md). Which existing specs are over is deliberately not "
            "listed: several sit exactly at the line, so any list names other people's "
            "files rather than the one in your diff. If yours is genuinely indivisible, "
            "raise this constant by one and say why in the spec (docs/process/authoring-a-spec.md) — "
            "that is the argued exception, not the reflex."
        )
    ]


def check_spec_shape() -> list[str]:
    """Require a live spec to carry the template's four sections and no parked question.

    The template's shape is what makes a spec buildable by a session that was not there when it
    was written (``docs/process/authoring-a-spec.md``): an Overview, a Scope, the Functional
    Requirements and the Implementation Phases, each a top-level ``## `` heading matched on its
    first words case-insensitively — ``## Scope`` but not ``### Scope`` and not ``## Scoped``. A
    heading at any level naming an Open Question or a Checkpoint FAILS: the first is a decision the
    author deferred to the builder, the second the per-phase approval the session rhythm retired,
    and both are resolved in authoring or in session rather than parked in the file. Two findings
    are WARNINGS, reported and not failed, as the template's own linter treats them: an unfilled
    placeholder — ``[Feature Name]``, ``[Requirement Name]``, ``SPEC-XXX``, and ``YYYY-MM-DD`` on
    the ``**Last Updated:**`` line only, because three specs describe a date format in prose — and
    ``### FR-`` headings with no ``Acceptance Criteria`` anywhere.

    The check reads the spec outside fenced blocks and HTML comments (``_prose_lines``), so a
    heading quoted in an example or commented out is not a heading.

    WHO IS EXEMPT, and why it fails closed. The Completed specs written from an earlier template
    carry ``#### Checkpoint`` and ``## Open Questions`` headings, and a Cancelled spec is a
    tombstone with nothing to require. Rewriting sixty closed files to satisfy a rule that governs
    specs still being built would be churn with no reader, so ``SPEC_SHAPE_EXEMPT`` skips them —
    keyed on the Status header alone. Everything else is judged in full: no status,
    Draft, In Progress, Superseded, or a status nobody can parse. An exemption that widened to
    "anything that does not say Draft" would let the next unlabelled spec through, which is the
    silent direction.

    Args:
      None.

    Returns:
      One message per missing section and per banned heading, and one ``WARNING``-prefixed message
      per spec for placeholders and for FRs with no acceptance criteria; empty when every live
      spec has the shape.

    Raises:
      None.
    """
    banned = re.compile(
        r"^#{1,6}\s.*(?:" + "|".join(re.escape(h) for h in SPEC_BANNED_HEADINGS) + ")",
        re.IGNORECASE,
    )
    fr_heading = re.compile(r"^### FR-")
    findings = []
    for path in sorted((ROOT / "docs" / "specs").glob("SPEC-*.md")):
        text = path.read_text()
        if spec_status(text) in SPEC_SHAPE_EXEMPT:
            continue
        lines = _prose_lines(text)
        for section in SPEC_REQUIRED_SECTIONS:
            present = re.compile(r"^" + re.escape(section) + r"(\s|$)", re.IGNORECASE)
            if not any(present.match(line) for _, line in lines):
                findings.append(f"{path.name}: missing required section '{section}'")
        for number, line in lines:
            if banned.match(line):
                findings.append(
                    f"{path.name} line {number}: banned heading '{line.strip()}' — an Open Question "
                    "or a Checkpoint is resolved while authoring or in session, never parked in the "
                    "spec (docs/process/authoring-a-spec.md)"
                )
        placeholders = [
            marker for marker in SPEC_PLACEHOLDERS if any(marker in line for _, line in lines)
        ]
        if any(line.startswith("**Last Updated") and "YYYY-MM-DD" in line for _, line in lines):
            placeholders.append("YYYY-MM-DD")
        if placeholders:
            findings.append(
                f"{WARNING}{path.name}: unfilled template placeholder(s): {', '.join(placeholders)}"
            )
        has_frs = any(fr_heading.match(line) for _, line in lines)
        if has_frs and not any("acceptance criteria" in line.lower() for _, line in lines):
            findings.append(f"{WARNING}{path.name}: has FR-* requirements but no 'Acceptance Criteria'")
    return findings


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


def _test_name_population() -> set[str]:
    """Every name a test citation may legitimately resolve against.

    Two kinds, because the repo cites both: the FUNCTION names a ``def test_…`` line declares,
    and the STEM of every test module, since a citation naming a module names a module-wide
    sweep rather than one assertion.

    Walks the working tree rather than ``git ls-files``, for the reason
    ``check_doc_paths_everywhere`` records: the fixture corpus runs this file in a tree with no
    repository, where a ``git`` population would collapse to empty and take every case with it.
    The residual is the same one — an untracked local ``test_*.py`` resolves a citation here that
    CI's clean checkout will refuse.

    Args:
      None.

    Returns:
      The function names and module stems, as one set.

    Raises:
      None.
    """
    definition = re.compile(r"\s*def (test_[A-Za-z0-9_]+)")
    names: set[str] = set()
    for path in ROOT.rglob("*.py"):
        if any(part in VENDORED for part in path.relative_to(ROOT).parts):
            continue
        # Only the ``test_`` prefix, deliberately, where ``_cites_tests`` needs both forms. A
        # citation can only ever name something matching ``\btest_``, so a ``*_test.py`` stem is
        # unreachable here — it would read as symmetry while resolving nothing.
        if path.name.startswith("test_"):
            names.add(path.stem)
        for line in path.read_text().split("\n"):
            found = definition.match(line)
            if found:
                names.add(found.group(1))
    return names


def _citation_lines(path: pathlib.Path, text: str) -> tuple[str, list[tuple[int, int, str]]]:
    """One file flattened for citation matching, and a map back to its line numbers.

    Two transformations. Markdown goes through ``_prose_lines`` first, so a citation quoted inside
    a fenced example is not judged. Then a citation WRAPPED across a line break is rejoined —
    one register entry splits a name mid-identifier and three Python docstrings split theirs at an
    indent, and without this each reports a truncated stub that resolves against nothing. The continuation's leading whitespace and blockquote marker come off, and no space is
    inserted, because the two halves are halves of one identifier.

    The flattened text is what the retirement window is measured over: the one strikethrough site
    carries its verb on the FOLLOWING line, so a window confined to a single line cannot see it.

    Args:
      path: The file, whose suffix decides whether markdown stripping applies.
      text: Its full text.

    Returns:
      ``(flat, spans)`` where ``flat`` is the joined text and each span is
      ``(offset, line number, line)`` for one joined line.

    Raises:
      None.
    """
    pairs = _prose_lines(text) if path.suffix == ".md" else list(enumerate(text.split("\n"), 1))
    joined: list[tuple[int, str]] = []
    index = 0
    while index < len(pairs):
        number, line = pairs[index]
        while WRAPPED_CITATION_RE.search(line) and index + 1 < len(pairs):
            index += 1
            line += re.sub(r"^[\s>]*", "", pairs[index][1])
        joined.append((number, line))
        index += 1
    spans: list[tuple[int, int, str]] = []
    offset = 0
    for number, line in joined:
        spans.append((offset, number, line))
        offset += len(line) + 1
    return "\n".join(line for _, line in joined), spans


def _citations(path: pathlib.Path, text: str) -> "Citations":
    """Every test a file cites, and whether the citation is an exempt retirement record.

    Three grammars, because the repo writes citations three ways. A name in backticks is the
    common form. A ``test_*.py`` filename is how a module-wide sweep is named. A BARE identifier
    in a comment is how 11 citations in this repo are written — 10 in Terraform comments, one in
    a state-machine template — and it is not a stylistic variant to be tidied away: a
    backticks-only grammar cannot see the seven ``locals.tf`` claims this check exists for.

    Bare matching is scoped to a comment in code, and to nothing at all in markdown, where ``#``
    opens a heading rather than a comment; measured, admitting markdown yields one match tree-wide
    and it is a user-visible folder name, not a citation. ``.tftpl`` is the exception in the other
    direction: an ASL template carries no ``#`` or ``//`` anywhere in the tree, and its citations
    live inside JSON ``"Comment"`` strings, so a comment-scoped rule would be dead there.

    A name followed by ``/`` is a directory and not a citation.

    Args:
      path: The file being scanned.
      text: Its full text.

    Returns:
      ``Citations(sites, grammars)``. ``sites`` holds ``(line number, name, exempt)`` once per
      distinct name per line; ``grammars`` holds the form of EVERY match, before that dedup, so
      the positive control counts what the scan actually matched. Counting after the dedup made
      one grammar's tally depend on which grammar happened to see a name first, and measured, that
      left the filename form reading as live while it was unreachable in markdown — every filename
      citation in a doc is written inside backticks, so the code span always won the key.

    Raises:
      None.
    """
    flat, spans = _citation_lines(path, text)
    seen: dict[tuple[int, str], bool] = {}
    matched: list[str] = []
    for offset, number, line in spans:
        found: list[tuple[str, int, str]] = []
        for span in CODE_SPAN_RE.finditer(line):
            for name in TEST_NAME_RE.finditer(span.group(1)):
                found.append((name.group(0), span.start(1) + name.start(), "code span"))
        for name in TEST_FILENAME_RE.finditer(line):
            found.append((name.group(0)[: -len(".py")], name.start(), "filename"))
        bare_from = None
        if path.suffix == ".tftpl":
            bare_from = 0
        elif path.suffix != ".md":
            marker = COMMENT_START_RE.search(line)
            bare_from = marker.start() if marker else None
        if bare_from is not None:
            for name in TEST_NAME_RE.finditer(line, bare_from):
                found.append((name.group(0), name.start(), "bare in a comment"))
        for name, column, grammar in found:
            if line[column + len(name):].startswith("/"):
                continue
            start = max(0, offset + column - TEST_CITATION_WINDOW)
            window = flat[start: offset + column + len(name) + TEST_CITATION_WINDOW]
            matched.append(grammar)
            seen[(number, name)] = seen.get((number, name), False) or bool(
                RETIREMENT_RE.search(window)
            )
    return Citations(
        sites=[(number, name, exempt) for (number, name), exempt in seen.items()],
        grammars=matched,
    )


def _cites_tests(relative: pathlib.PurePath) -> bool:
    """Whether a file is scanned for test citations.

    Four exclusions, each for its own reason. ``docs/specs/SPEC-*.md`` and ``docs/spec-delivery/``
    are HISTORY: they record what a spec cited when it was written, and holding them to today's
    test suite would make 101 findings out of documents that are correct as they stand. The
    per-spec glob is deliberately narrower than the tree — ``ARCS.md`` is live narrative the
    completion ritual still edits, and blanket-excluding the directory hid two present-tense false
    citations in it.

    Test modules and ``conftest.py`` are excluded so a suite's own ``def test_…`` lines are not
    read as citations of themselves. That exclusion is NOT free and the cost is stated rather than
    implied: it also hides four genuine false citations, in which one test's comment delegates a
    check to a named guard in the same suite that no longer exists. Lifting it would admit eight
    false positives, of five kinds — an author's deliberate ellipsis, a dict key in an inline
    fixture, a prefix being described, a provenance record, and a record of a guard that never
    existed at all, which no rewording can turn into a retirement — so the four are paid down by
    hand instead.

    ``lambdas/fixtures/retired-layer-artifacts/`` holds verbatim captures of code that was
    deliberately deleted. It suppresses nothing today: its only scanned file is ``PROVENANCE.md``
    and that file's one citation still resolves. It is here for what the directory is FOR, and a
    reader should not take it as evidence anything is being held back.

    Args:
      relative: The file's path from the repository root.

    Returns:
      True when the file's citations are judged.

    Raises:
      None.
    """
    text = relative.as_posix()
    if relative.name == "conftest.py":
        return False
    if fnmatch.fnmatch(relative.name, "test_*.py") or fnmatch.fnmatch(relative.name, "*_test.py"):
        return False
    if fnmatch.fnmatch(text, "docs/specs/SPEC-*.md"):
        return False
    return not text.startswith(("docs/spec-delivery/", "lambdas/fixtures/retired-layer-artifacts/"))


def check_test_citations() -> list[str]:
    """Refuse a comment or doc that names a test which does not exist.

    A citation that has gone stale is worse than no citation at all: it tells a reader the claim
    beside it is already enforced, so the check a careful engineer would otherwise make is the one
    thing the comment talks them out of. Every one of these arrived the same way — one commit
    deleted 57 files, 53 of them test modules, and left every reference to them standing.

    Unresolved citations are reported as WARNINGS on every run and the RATCHET decides the exit
    code, so the debt is legible while it is being paid rather than only at the moment it crosses
    a line. The direction matches ``check_spec_size``: measured above the constant fails.

    Three things a name-resolution gate cannot see, recorded here rather than answered with more
    mechanism — an earlier attempt at a cross-plane check produced nine false positives, no true
    positive, and contradicted its own path to zero, because ``cpcommon`` is shared by every plane
    by design: (a) a citation written as a filename resolves on the filename whatever the file
    contains; (b) a module deleted and recreated as a stub keeps its citations green — file-ops
    carries seven false claims that resolve exactly this way; (c) resolution is global by name, so
    one plane's guard satisfies another plane's identical citation, which is why two guards this
    repo restored to two planes carry plane-qualified names. And (d) the ratchet compares a TOTAL,
    so a change that narrows the scanned set and adds an offsetting citation in the same commit
    nets to zero and passes — the exact ratchet catches a narrowing on its own, not a narrowing
    paid for.

    Each grammar is a positive control on itself, for ``check_spec_size``'s reason: a ratchet
    sitting at zero goes vacuous the moment the scan stops matching, and a broken scanner finding
    nothing is then indistinguishable from a clean repository, forever.

    Args:
      None.

    Returns:
      One warning per unresolved citation, plus an error when the count exceeds the ratchet or
      any grammar matched nothing at all.

    Raises:
      None.
    """
    names = _test_name_population()
    grammars: set[str] = set()
    unresolved: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in TEST_CITATION_SCAN or not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in VENDORED for part in relative.parts) or not _cites_tests(relative):
            continue
        found = _citations(path, path.read_text())
        grammars.update(found.grammars)
        for number, name, exempt in sorted(found.sites):
            if not exempt and name not in names:
                unresolved.append(f"{relative}:{number} names {name}, which no test defines")
    findings = [f"{WARNING}stale test citation: {site}" for site in unresolved]
    if unresolved:
        # The remedy is repeated here because the ratchet error below is the only other
        # place it appears, and that error does not fire while the count sits AT the
        # ratchet — which is the whole of the paydown, and exactly when this wording gets
        # written. An author who reaches for "dropped" or "no longer exists" would
        # otherwise get a warning with no hint and a green run.
        findings.insert(
            0,
            WARNING
            + "each stale citation below names a test that no `def` and no test module\n"
            "    provides. Restore the guard, or say what is true without naming a\n"
            "    test. If the sentence RECORDS a retirement, the exemption is the word\n"
            "    'retired' within 100 characters of the name — not 'deleted' or\n"
            "    'removed', which this repo uses in live claims about deletion\n"
            "    semantics.",
        )
    silent = sorted(set(TEST_CITATION_GRAMMARS) - grammars)
    if silent:
        findings.append(
            f"the test-citation scan matched nothing in {len(silent)} of its "
            f"{len(TEST_CITATION_GRAMMARS)} grammars ({', '.join(silent)}). That is a broken scan, "
            "not a clean tree: every citation written that way now reads as resolved, and the "
            "ratchet below agrees. Each grammar is how some part of this repo actually writes a "
            "citation — 11 sites are written bare and nowhere else — so none may go quiet."
        )
    if len(unresolved) > TEST_CITATION_MAX:
        findings.append(
            f"{len(unresolved)} citations name a test that does not exist (ratchet "
            f"{TEST_CITATION_MAX}); each is a WARNING above. A comment that names a guard which "
            "is gone actively discourages the check a reader would otherwise make, so write what "
            "is true instead, or restore the guard. If the citation is a past-tense record of a "
            "RETIREMENT, word it with 'retired' — that is the exemption, and it is the one "
            "legitimate case that reaches a ratchet of zero. Raising this number is not."
        )
    elif len(unresolved) < TEST_CITATION_MAX:
        findings.append(
            f"{len(unresolved)} citations name a test that does not exist, below the ratchet of "
            f"{TEST_CITATION_MAX} — lower it to {len(unresolved)} in this pull request. This is "
            "the good direction and the message is still an error, because a count that FELL has "
            "two causes that look identical from here: citations were repaired, or the scan "
            "stopped seeing a file. A ceiling cannot tell them apart, so it never reddens on lost "
            "detection — narrowing the scanned set by one filename was measured to drop eight "
            "findings in silence. Read the warnings above, confirm they went away for the reason "
            "you intended, then move the number."
        )
    return findings


def check_workflow_table() -> list[str]:
    """Every workflow has a row in the workflows README, and every row a workflow.

    The table opened with "This directory contains five workflows" while eleven existed —
    a hand-maintained list nothing compared, so it rotted the way they do, silently and in
    the one direction that matters: a workflow nobody has described reads as one that does
    not exist. The count is gone; this is what replaces it.

    Both directions are checked. A missing row is an undocumented workflow; a row with no
    file is a workflow someone deleted while leaving its description behind, which sends the
    next reader looking for something that is not there.

    ``.yaml`` counts as much as ``.yml``: GitHub Actions accepts both, so matching only one
    would leave a workflow added under the other spelling invisible to exactly the check
    written to notice it.

    Args:
      None.

    Returns:
      One message per drift, in either direction.

    Raises:
      None.
    """
    readme = ROOT / ".github" / "workflows" / "README.md"
    if not readme.exists():
        return [f"{readme.relative_to(ROOT)} is missing — the workflow table lives there"]

    text = readme.read_text()
    header = "| File | Trigger | Purpose |"
    if header not in text:
        return [f"{readme.relative_to(ROOT)} has no workflow table — this check has no subject"]

    start = text.index(header)
    end = text.find("\n\n", start)
    body = text[start : end if end != -1 else len(text)]
    described = set(re.findall(r"^\| `([^`]+\.ya?ml)`", body, re.MULTILINE))

    workflows = ROOT / ".github" / "workflows"
    on_disk = {path.name for path in workflows.glob("*.yml")} | {
        path.name for path in workflows.glob("*.yaml")
    }
    if not on_disk:
        return ["no workflows found on disk — this comparison would pass vacuously"]

    errors = []
    for name in sorted(on_disk - described):
        errors.append(
            f".github/workflows/README.md describes no `{name}` — every workflow gets a row, "
            "or it is one nobody has described"
        )
    for name in sorted(described - on_disk):
        errors.append(
            f".github/workflows/README.md describes `{name}`, which does not exist — a row "
            "outliving its workflow sends a reader after something that is not there"
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
        files.extend(_docs_in(tree))
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
        scanned.extend(_docs_in(tree))
    for path in scanned:
        text = path.read_text()
        for match in re.finditer(r"(owed\.md`?[^.\n]{0,40}?|^)§(\d+\.\d+)", text, re.MULTILINE):
            cites_ledger = "owed.md" in match.group(1) or path == ledger
            if cites_ledger and match.group(2) not in sections:
                errors.append(
                    f"{path.relative_to(ROOT)}: §{match.group(2)} names no section of owed.md"
                )
    return errors


def check_always_loaded_pointers() -> list[str]:
    """Refuse an ``@doc/path.md`` pointer that resolves to nothing, wherever a session is told to read it.

    CLAUDE.md is a router: it carries pointers instead of the detail it points at, and every cut
    has deepened that reliance. The same is true of the two always-loaded process files and of
    each area's Fences, which carry the pointers the digest carried when it lived in CLAUDE.md —
    the identity fences point at the API plane page, for one. A pointer is only a cut worth
    making while it resolves, and nothing else here reads it — ``check_links`` matches
    ``[text](target)`` markdown links, and ``check_doc_paths_everywhere`` walks code suffixes, so
    a bare ``@`` pointer in a ``.md`` file falls between them. Verified by planting a broken one,
    which passed the whole suite.

    Args:
      None.

    Returns:
      One message per ``@`` pointer in an always-loaded file or a Fences entry that names a
      ``.md`` file under ``DOC_TREES`` and does not resolve. Deliberately narrow, and the gaps are
      real: a pointer to a DIRECTORY (``@docs/testing/``), to a tree outside ``DOC_TREES``
      (``@scripts/…``), or with the tree itself misspelt (``@doc/process/INDEX.md``) is invisible
      to this, and CLAUDE.md carries live pointers of the first kind. Widening it needs the glob
      placeholders (``@docs/specs/SPEC-XXX-*.md``, ``@docs/decisions/<area>.md``) handled
      deliberately rather than by accident of this character class.

    Raises:
      None.
    """
    pattern = re.compile(
        r"@((?:" + "|".join(re.escape(tree) for tree in DOC_TREES) + r")/[A-Za-z0-9_./-]+\.md)"
    )
    sources: list[tuple[str, str]] = [("CLAUDE.md", (ROOT / "CLAUDE.md").read_text())]
    for rel in always_loaded_process():
        if (ROOT / rel).exists():
            sources.append((rel, (ROOT / rel).read_text()))
    for _, target in decision_table():
        rel = target.partition("#")[0]
        if (ROOT / rel).exists():
            sources.append((rel + " (Fences)", "\n".join(fences_section(ROOT / rel) or [])))
    return [
        f"{name}: points at a missing doc -> @{target}"
        for name, text in sources
        for target in sorted(set(pattern.findall(text)))
        if not (ROOT / target).exists()
    ]


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
    skip = VENDORED
    candidates = scanned = 0
    pattern = re.compile(
        r"(?:" + "|".join(re.escape(tree) for tree in DOC_TREES) + r")/[A-Za-z0-9_./-]+\.md"
    )
    errors = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in suffixes:
            continue
        candidates += 1
        if any(part in skip for part in path.relative_to(ROOT).parts):
            continue
        scanned += 1
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for target in sorted(set(pattern.findall(text))):
            if not (ROOT / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: references a missing doc -> {target}")

    if candidates and not scanned:
        errors.append(
            f"this check found {candidates} source files and skipped every one of them as "
            "vendored. It has not passed, it has not run — and a check that did not run reads "
            "exactly like a clean one. The cause this control was written for: the skip compared "
            "ABSOLUTE path parts, so a checkout nested inside any directory named in VENDORED "
            "excluded its own entire tree. A git worktree under `.claude/worktrees/` is exactly "
            "that, and this check reported OK having read none of it. The control is "
            "all-or-nothing because the fault is: a prefix match applies to every path in the "
            "tree alike. It would NOT catch a skip that swallowed merely most of them."
        )
    return errors


RULE_BODY = (
    "This file is in the **{area}** area of the Key Decisions register.\n"
    "Before changing it, read `{target}` — the traps there apply green and fail later.\n"
)


def _tree_files() -> list[str]:
    """Every file under the repository as a root-relative POSIX path, vendored trees pruned.

    Walks with pruning rather than ``rglob`` because ``node_modules`` is most of the tree and a
    filter after the walk still pays for it.

    Args:
      None.

    Returns:
      Relative paths, in no particular order.

    Raises:
      None.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in VENDORED]
        rel_dir = pathlib.Path(dirpath).relative_to(ROOT)
        for name in filenames:
            found.append((rel_dir / name).as_posix())
    return found


def _paths_globs(frontmatter: str) -> list[str] | None:
    """The globs listed under a rule's ``paths:`` key, and only that key.

    Read by position rather than by any list item in the block: a list under a different key is
    not a path scope, and reading it as one would pass a rule Claude Code loads every session —
    the exact rule the check exists to refuse.

    Args:
      frontmatter: The text between the rule's ``---`` fences.

    Returns:
      The globs, quotes stripped, in order; ``[]`` when ``paths:`` is absent or lists nothing;
      ``None`` when ``paths:`` is written as an inline list, which this reader does not parse.

    Raises:
      None.
    """
    lines = frontmatter.split("\n")
    start = next((i for i, line in enumerate(lines) if re.match(r"^paths:", line)), None)
    if start is None:
        return []
    if lines[start].strip() != "paths:":
        return None
    globs = []
    for line in lines[start + 1 :]:
        item = re.match(r"^\s+-\s*(.+?)\s*$", line)
        if not item:
            break
        globs.append(item.group(1).strip("\"'"))
    return globs


def check_rules() -> list[str]:
    """Require one path-scoped pointer rule per Key Decisions area, and nothing else in it.

    ``.claude/rules/<area>.md`` is Claude Code's mechanism for loading a file only when a
    matching source file is read. Here each rule is a backstop that points a session touching an
    area's code at that area's Fences; the fence itself has one home, in the register. So a rule
    is held to being exactly that: named for the register file, a ``paths`` list at byte 0 whose
    every glob matches something in the tree, and a body carrying a pointer that
    resolves — a body that IS the rendered ``RULE_BODY`` and nothing more, because a committed rule
    reaches every teammate's session on any Read of a matching file, and a body held to a template
    is the only shape that leaves no room for a line that is not a pointer. Each glob's first
    segment must be literal, which bounds a rule to one top-level tree; how wide it reaches within
    that tree is left to review of the diff that changes it. Globs may not carry a brace or a ``[``: Claude Code's matcher
    expands braces and Python's does not, and this check runs Python's ``fnmatch`` as a proxy for a
    matcher it cannot run — a permissive proxy, since ``fnmatch``'s ``*`` crosses ``/`` where Claude
    Code's does not, so only the ``dir/**`` and ``dir/**/*.ext`` forms mean the same thing to both.
    The "matches something" verdict walks the working tree rather than ``git ls-files``, because
    the fixture corpus runs this file in a tree with no repository; an untracked local file can
    therefore satisfy a glob here that CI's clean checkout will refuse. The rules directory is read
    directly and NOT recursively — ``.claude`` is in ``VENDORED`` because every agent worktree
    under ``.claude/worktrees/`` carries its own copy — and a rule in a subdirectory is refused by
    name, since Claude Code would load it and nothing here would read it.

    Measured on Claude Code 2.1.223 (2026-09-05) by planting a rule and watching which read
    surfaced it: a rule fires when a matching file is opened with the Read tool and does not fire
    when the file is read through the shell (``cat``, ``head``, ``grep``). That is why the
    instruction in ``CLAUDE.md`` to read an area's fences first stays the primary path and the
    rule is a backstop.

    A rule without a ``paths`` block is not a broken rule: Claude Code loads it every session,
    silently, which is the always-loaded regrowth this whole layout exists to prevent. That is why
    the frontmatter is checked by position and shape rather than by presence.

    Args:
      None.

    Returns:
      One message per area without a rule, per rule for no area, and per rule breaking the shape.

    Raises:
      None.
    """
    rules_dir = ROOT / ".claude" / "rules"
    expected = {pathlib.Path(target.partition("#")[0]).stem: (area, target) for area, target in decision_table()}
    found = {p.stem: p for p in rules_dir.glob("*.md")} if rules_dir.is_dir() else {}
    errors = [
        f".claude/rules/{stem}.md is missing — every Key Decisions area has one pointer rule"
        for stem in expected
        if stem not in found
    ]
    nested = [p for p in rules_dir.rglob("*.md") if p.parent != rules_dir] if rules_dir.is_dir() else []
    errors.extend(
        f"{p.relative_to(ROOT).as_posix()}: sits in a subdirectory of .claude/rules/ — Claude Code loads it, this check does not read it"
        for p in sorted(nested)
    )
    files = None
    for stem, path in sorted(found.items()):
        rel = f".claude/rules/{path.name}"
        if stem not in expected:
            errors.append(f"{rel}: names no Key Decisions area — a rule is a pointer to an area's Fences, nothing else")
            continue
        text = path.read_text()
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            errors.append(f"{rel}: does not open with a ----fenced frontmatter block — Claude Code would load it every session")
            continue
        frontmatter, body = text[4:].split("\n---\n", 1)
        globs = _paths_globs(frontmatter)
        if globs is None:
            errors.append(f"{rel}: writes `paths:` inline — write the list one `- \"glob\"` per line so this check can read it")
            continue
        if not globs:
            errors.append(f"{rel}: has no non-empty `paths:` list — Claude Code would load it every session")
            continue
        for glob in globs:
            if "{" in glob or "[" in glob:
                errors.append(f"{rel}: the glob {glob!r} uses a brace or bracket, which this check cannot evaluate the way Claude Code does")
                continue
            if "*" in glob.split("/", 1)[0] or "?" in glob.split("/", 1)[0]:
                errors.append(f"{rel}: the glob {glob!r} has no literal first segment — a rule is scoped to one tree, never to the repository")
                continue
            if files is None:
                files = _tree_files()
            if not any(fnmatch.fnmatch(f, glob) for f in files):
                errors.append(f"{rel}: the glob {glob!r} matches no file in the tree")
        area, target = expected[stem]
        if body.strip() != RULE_BODY.format(area=area, target=target).strip():
            errors.append(f"{rel}: body is not the rendered RULE_BODY for '{area}' — a rule is a pointer to {target} and nothing else")
        elif fences_section(ROOT / target.partition("#")[0]) is None:
            errors.append(f"{rel}: points at {target}, which has no ## Fences entry")
    return errors


def main() -> int:
    """Run every check and report all failures at once.

    Reports everything rather than stopping at the first, so one CI run tells the whole story.

    Args:
      None.

    Returns:
      ``0`` when the layout holds, warnings or not; ``1`` when any check failed.

    Raises:
      None.
    """
    findings: list[str] = []
    for check in (
        check_testing_layout,
        check_fixture_scripts,
        check_claude_budget,
        check_process_budget,
        check_decisions_register,
        check_fences,
        check_rules,
        check_process_router,
        check_arcs,
        check_spec_status,
        check_spec_shape,
        check_spec_size,
        check_delivery_size,
        check_source_citations,
        check_test_citations,
        check_workflow_table,
        check_links,
        check_section_pointers,
        check_doc_paths_everywhere,
        check_always_loaded_pointers,
    ):
        findings.extend(check())
    # A warning is reported in full and decides nothing: the exit code is the errors' alone.
    warnings = [f[len(WARNING):] for f in findings if f.startswith(WARNING)]
    errors = [f for f in findings if not f.startswith(WARNING)]
    if warnings:
        print(f"Documentation layout: {len(warnings)} warning(s)\n", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
        print(file=sys.stderr)
    if errors:
        print(f"Documentation layout: {len(errors)} problem(s)\n", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nEvery rule above is in CLAUDE.md or docs/process/ as prose, and every one of "
            "them was broken anyway. Fix the doc, not the budget.",
            file=sys.stderr,
        )
        return 1
    print("Documentation layout: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
