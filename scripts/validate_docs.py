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
    altogether — each decision's fence is now its own file's ``description``, listed in the
    generated ``docs/decisions/index.yaml``, and CLAUDE.md keeps an eight-row table naming the
    areas — and the method it points to became ``docs/process/``, a router and one file per part.
    Before that cut the
    file carried deliberate headroom, because the completion ritual folded a clause into it on
    every architectural close and a ratchet at the measured level made each close a forced prune
    of another area's fences (it happened once; #568 is titled for the prune it forced). The fold
    now lands in a decision's own file, so that reason is gone. What still grows this file is a Tech Stack
    row when a dependency is added and the ``## Specs`` current-work paragraph, and that room has been
    spent: what is left is a sentence's worth, so the next row or paragraph pays for itself. The answer is a cut, never a raise: every one of the five was
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
  FENCE_MAX_BYTES: The longest a decision's fence may be, its frontmatter ``description``
    unescaped, in bytes. A fence is written on one line, so wrapping cannot hide one from this cap
    the way wrapped prose once hid a digest entry from a per-line one. It is the template's number
    and the old per-bullet cap's: when the register split on 2026-11-02 the curated bullets moved
    verbatim, so this was re-derived against them rather than carried over, and they sit close
    under it. A fence is a reminder with the reasoning in the body beneath it; past this length it
    has become the reasoning.
  PROCESS_ROUTER: The ``docs/process/`` router. Its "Loaded every session" table is the ONE
    statement of which process files every session reads, and ``always_loaded_process`` derives
    the pair ``PROCESS_MAX_BYTES`` bounds from it rather than transcribing it — a transcribed copy
    passed a plant that added a third row to the table. Its method table is the closed set of
    process files, held the way the register's areas are.
  RULE_BODY: The whole body of a ``.claude/rules/decisions-<slug>.md``, rendered per area. A committed
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
    ``YYYY-MM-DD`` is deliberately not in this tuple: three specs describe a date format in prose.
  SPEC_SHAPE_EXEMPT: The statuses ``check_spec_shape`` does not judge. The Completed specs written
    from an earlier template carry its retired ``#### Checkpoint`` and ``## Open Questions``
    headings — sixty closed specs would fail at the commit that introduced the check, and a reader
    can re-measure that by emptying this set — and a Cancelled spec is reduced to a tombstone with
    no sections to require (``docs/process/spec-lifecycle.md``). The exemption keys on ``spec_status`` alone and
    fails CLOSED: a spec with no readable status, or any status outside this set — Draft, In
    Progress, Superseded, a misspelling — is judged in full.
  WARNING: The prefix a check puts on a finding that is reported but does not fail the run. The
    exit code is decided by the findings without it.
  STATUS_WORDS: Words that must not appear in an ``ARCS.md`` arc heading. Status lives in each
    spec's ``spec_status``, which is the only place it can be kept true.
  SPEC_STATUSES: The values ``spec_status`` may hold (``docs/process/knowledge-layout.md``).
    Cancelled and Superseded are this repo's, on top of the template's three, because it has
    specs in both states and ``SPEC_SHAPE_EXEMPT`` keys on one of them.
  SPEC_HEADER_LINE: A bold header line of the layout this replaced. Its values now live in the
    frontmatter, so one surviving in a body is a second copy nothing compares.
  FRONTMATTER_READER: The one reader of a governed file's frontmatter, taken whole from the
    template with the generator beside it, so an index is never generated from one reading of a
    file and linted against another.
  GEN_INDEX: The generator of ``docs/specs/index.yaml`` and ``docs/decisions/index.yaml``.
  RULEBOOK_TREES: Where the rulebooks live, beside the code they govern. Every ``.md`` under one
    but its ``INDEX.md`` router is a rulebook.
  STALE_WARNING_DAYS: How long before a rulebook's ``stale_after`` this gate starts warning. The
    template fails on the date and keeps that check out of CI, because a clock-driven red lands on
    unrelated work. This gate IS CI, so the date gets a month of notice first, then the same hard
    stop; a re-read is one short pull request.
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
  INVENTORY_DIR: The component inventory, one page per area of the portal's source, each a table
    of the reusable symbols there and the file each lives in. ``check_inventory_files`` reads
    every page under it, and refuses to pass having found none.
"""

import datetime
import fnmatch
import functools
import os
import pathlib
import re
import subprocess
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
FENCE_MAX_BYTES = 1_400
FENCE_LINK_RE = re.compile(r"\]\([^)\s]+\)")
DELIVERY_MAX_LINES = 260
FR_CEILING = 8
SPEC_OVERSIZE_MAX = 40
def _key_decisions_section() -> list[str]:
    """The lines of ``CLAUDE.md``'s Key Decisions section, heading excluded.

    Args:
      None.

    Returns:
      The lines up to the next ``## `` heading.

    Raises:
      None.
    """
    lines = (ROOT / "CLAUDE.md").read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## Key Decisions"))
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## "))
    return lines[start + 1 : end]


def decision_table() -> list[tuple[str, str]]:
    """Read the Key Decisions table in ``CLAUDE.md``: each area, and the directory that holds it.

    DERIVED, never transcribed. A hard-coded copy of the eight area strings is what this replaced,
    and it had already drifted: one area's wording differed from the heading it claimed to mirror,
    while the docstring beside it asserted the two agreed. That is the failure mode a second copy
    always has — the copy is not checked against the original, so the claim of agreement is the
    only thing holding, and a claim is not a check. The table is the authority for the closed set
    of areas; each area's concept and the rules directory are held to it.

    Args:
      None.

    Returns:
      ``(area, slug)`` pairs in table order, where ``slug`` names ``docs/decisions/<slug>/``.

    Raises:
      None.
    """
    return [(found.group("area"), found.group("slug"))
            for found in map(TABLE_ROW_RE.match, _key_decisions_section()) if found]


#: A row of the Key Decisions table, the one form the section may hold a row in.
TABLE_ROW_RE = re.compile(r"^\|\s*(?P<area>[^|]+?)\s*\|\s*`docs/decisions/(?P<slug>[^/`]+)/`\s*\|$")
#: A line that is a fence marker's shape: its run of backticks or tildes, and what follows the run.
FENCE_MARKER_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
#: A code span of any backtick run: it closes only on a run of the same length.
ANY_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
SPEC_STATUSES = ("Draft", "In Progress", "Completed", "Cancelled", "Superseded")
SPEC_HEADER_LINE = re.compile(r"^\*\*(?:ID|Status|Last Updated|Depends On):?\*\*")
FRONTMATTER_READER = "scripts/frontmatter.awk"
GEN_INDEX = "scripts/gen-index.sh"
RULEBOOK_TREES = ("apps/portal/info/best-practices", "lambdas/info/best-practices", "infra/info/best-practices", "docs/best-practices")
STALE_WARNING_DAYS = 30
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
TEST_CITATION_MAX = 0
INVENTORY_DIR = "apps/portal/info/component-inventory"


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


class Frontmatter(typing.NamedTuple):
    """What the shared reader made of one governed file's frontmatter.

    Attributes:
      errors: ``(line, message)`` for every line the subset refuses, empty when the file reads.
      keys: The scalar keys, unquoted and unescaped.
      lists: The flow-list keys and their elements, in order.
      sources: The ``sources`` block, each item's fields under its 1-based number.
      body_line: The 1-based number of the first line after the closing ``---``.
    """

    errors: list[tuple[int, str]]
    keys: dict[str, str]
    lists: dict[str, list[str]]
    sources: dict[int, dict[str, str]]
    body_line: int


@functools.cache
def read_frontmatter(path: pathlib.Path) -> Frontmatter:
    """Read one governed file through ``frontmatter.awk``, failing closed on a reader that did not run.

    Two things are checked because neither alone is enough: the exit status, and that exactly one
    verdict came back. An awk that dies prints nothing, and every check downstream of a reader that
    printed nothing iterates over nothing and passes.

    Args:
      path: An absolute path under ``ROOT``.

    Returns:
      What the reader printed; a failed reader comes back as one error on line 0.

    Raises:
      None.
    """
    rel = path.relative_to(ROOT).as_posix()
    # Both operands are ours: the reader's path is a constant and the file came from this tree's
    # own listing. Run from ROOT with the path relative, so a checkout path holding a `=` cannot
    # read as an awk assignment.
    done = subprocess.run(  # noqa: S603
        ["awk", "-f", FRONTMATTER_READER, rel],  # noqa: S607
        cwd=ROOT, env={**os.environ, "LC_ALL": "C"}, capture_output=True, encoding="utf-8", errors="replace",
        check=False)
    records = [line.split("\t") for line in done.stdout.split("\n") if line]
    if done.returncode != 0 or sum(r[1] == "F" for r in records) != 1:
        reason = done.stderr.strip().split("\n")[0] or "no single verdict"
        return Frontmatter([(0, f"the frontmatter reader failed: {reason}")], {}, {}, {}, 1)
    fields = Frontmatter([], {}, {}, {}, 1)
    body_line = 1
    for record in records:
        kind = record[1]
        if kind == "E":
            fields.errors.append((int(record[2]), record[3]))
        elif kind == "K":
            fields.keys[record[2]] = record[3] if len(record) > 3 else ""
        elif kind == "L":
            fields.lists[record[2]] = []
        elif kind == "I":
            fields.lists[record[2]].append(record[3])
        elif kind == "S":
            fields.sources.setdefault(int(record[2]), {})[record[3]] = record[4] if len(record) > 4 else ""
        elif kind == "B":
            body_line = int(record[2])
    return fields._replace(body_line=body_line)


def _refusals(rel: str, fields: Frontmatter) -> list[str]:
    """The reader's refusals of one file, one message per line it refused.

    Args:
      rel: The file as a message names it.
      fields: What the reader made of it.

    Returns:
      One message per refusal, pointing at the subset's one statement.

    Raises:
      None.
    """
    return [f"{rel}:{line}: frontmatter: {message} (docs/process/knowledge-layout.md → Frontmatter)"
            for line, message in fields.errors]


def _listed_scalars(rel: str, fields: Frontmatter, lists: tuple[str, ...]) -> list[str]:
    """Refuse a key written as a flow list where it takes one value.

    The reader files a list apart from a scalar, so without this ``status: [draft]`` is a key no check
    of ``status`` ever sees, and the index lists the decision as stable.

    Args:
      rel: The file as a message names it.
      fields: What the reader made of it.
      lists: The keys this kind of file may hold a list under.

    Returns:
      One message per such key.

    Raises:
      None.
    """
    return [f"{rel}: frontmatter `{key}` is a list; it takes one value" for key in sorted(fields.lists) if key not in lists]


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

    A ratchet just above the measured level, whose headroom ``CLAUDE_MAX_BYTES`` accounts for. What used to grow this file — the Key Decisions digest — is now each decision's own fence,
    measured there (``check_decisions_register``).

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
            "structural cut, and this budget has almost no headroom left — see CLAUDE_MAX_BYTES above."
        )
    ]


def _register_files() -> list[tuple[str, pathlib.Path]]:
    """Every readable register file as ``(slug, path)``: each area's concept and its decisions.

    Args:
      None.

    Returns:
      The ``.md`` files directly inside an area directory, in order.

    Raises:
      None.
    """
    register = ROOT / "docs" / "decisions"
    return [(area.name, path) for area in sorted(p for p in register.iterdir() if p.is_dir())
            for path in sorted(area.glob("*.md"))]


def _body_prose(path: pathlib.Path, start: int) -> list[tuple[int, str]]:
    """A governed file's body outside fences and comments, by the file's own line numbers.

    Args:
      path: The file.
      start: The 1-based first body line, from the reader.

    Returns:
      ``(line number, line)`` pairs from the body.

    Raises:
      None.
    """
    return [(number, line) for number, line in _prose_lines(path.read_text()) if number >= start]


def _says_something(number: int, line: str, kind: str) -> bool:
    """Whether one body line is an entry's content: not a blank, a heading, a rule, a comment or a marker.

    A fenced block's content counts and its markers do not, so an empty pair of fences is no entry.

    Args:
      number: The line's number, unused but for the shape ``_classified_lines`` yields.
      line: The line.
      kind: What ``_classified_lines`` called it.

    Returns:
      True when the line carries content.

    Raises:
      None.
    """
    if kind == "code":
        return bool(line.strip())
    return kind == "prose" and bool(line.strip()) and not re.match(r"^\s*(?:#{1,6}(?:\s|$)|([-*_])\1{2,}\s*$)", line)


def _decision_body_problems(rel: str, fields: Frontmatter, path: pathlib.Path) -> list[str]:
    """What is wrong with one decision's body: its entry and its History.

    The entry is a line that says something above the History (``_says_something``), so a lone
    heading, comment or empty fence does not pass for reasoning: a fence is never the only home of a fact. The
    History closes the body, one ``### YYYY-MM-DD`` per date, newest first, none after today, each
    with a bullet; and a deprecated decision's newest date must say so.

    Args:
      rel: The file as a message names it.
      fields: What the reader made of it.
      path: The decision.

    Returns:
      One message per problem.

    Raises:
      None.
    """
    errors = []
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    prose = _body_prose(path, fields.body_line)
    at = [i for i, (_, line) in enumerate(prose) if line.rstrip() == "## History"]
    if len(at) != 1:
        return [f"{rel}: has {len(at)} `## History` headings, not one — the dated record closes the body"]
    history_at = prose[at[0]][0]
    if not any(fields.body_line <= number < history_at and _says_something(number, line, kind)
               for number, line, kind in _classified_lines(path.read_text())):
        errors.append(f"{rel}: has no entry above its History — a fence is never the only home of a fact")
    dates: list[str] = []
    newest: list[str] = []
    bullets: dict[str, int] = {}
    for number, line in prose[at[0] + 1:]:
        if line.startswith("## "):
            errors.append(f"{rel}:{number}: '{line.strip()}' follows the History, which closes the body")
        elif line.startswith("### "):
            date = line[4:].strip()
            try:
                datetime.date.fromisoformat(date)
                valid = re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is not None
            except ValueError:
                valid = False
            if not valid:
                errors.append(f"{rel}:{number}: '{line.strip()}' is not a `### YYYY-MM-DD` History heading")
                continue
            if date > today:
                errors.append(f"{rel}:{number}: History date {date} is after today")
            if dates and date >= dates[-1]:
                errors.append(f"{rel}:{number}: History date {date} is not older than {dates[-1]} — newest first, one heading per date")
            dates.append(date)
            bullets[date] = 0
        elif dates:
            if line.startswith("- "):
                bullets[dates[-1]] += 1
            if len(dates) == 1:
                newest.append(line)
        elif line.strip():
            errors.append(f"{rel}:{number}: History text before its first date")
    if not dates:
        errors.append(f"{rel}: its History has no `### YYYY-MM-DD` entry — the first is when the decision was settled")
    errors.extend(f"{rel}: History {date} has no bullet" for date, count in bullets.items() if not count)
    if fields.keys.get("status") == "deprecated" and dates and "deprecat" not in " ".join(newest).lower():
        errors.append(f"{rel}: has status: deprecated, but its newest History entry does not say so — deprecating a decision is a reversal too")
    return errors


def check_decisions_register() -> list[str]:
    """Hold the register to one file per decision, one directory per area, and its table.

    The areas are a CLOSED set, and they are the rows of ``CLAUDE.md``'s Key Decisions table: every
    row a directory, every directory a row, in slug order, the order the index lists them, each row
    naming its area by the concept's title. An area file under no row is the first step back to a
    register nobody can look something up in. Every file reads through the shared reader and
    carries the keys for its kind; a decision has a fence within ``FENCE_MAX_BYTES``, an entry and a
    History (``_decision_body_problems``); nothing sits flat, a level too deep, or under a name OKF
    reserves. ``docs/process/knowledge-layout.md`` is the prose of all this.

    Args:
      None.

    Returns:
      One message per problem.

    Raises:
      None.
    """
    register = ROOT / "docs" / "decisions"
    errors = []
    table = decision_table()
    if not table:
        errors.append("CLAUDE.md: no area rows in the Key Decisions table — the register has no closed set")
    slugs = [slug for _, slug in table]
    errors.extend(f"CLAUDE.md: docs/decisions/{slug}/ has more than one row in the Key Decisions table"
                  for slug in sorted({slug for slug in slugs if slugs.count(slug) > 1}))
    for line in _key_decisions_section():
        if line.startswith("- "):
            errors.append(f"CLAUDE.md: the Key Decisions section holds a bullet, {line[:60]!r} — a fence lives in its decision's file, and this section is prose and the table")
        elif line.startswith("|") and not TABLE_ROW_RE.match(line) and line.strip() != "| Area | Directory |" and not re.fullmatch(r"\|[-| :]+\|", line.strip()):
            errors.append(f"CLAUDE.md: {line[:60]!r} is not a Key Decisions row — one is `| Area | `docs/decisions/<slug>/` |`")
    if slugs != sorted(slugs):
        errors.append(f"CLAUDE.md: the Key Decisions rows are not in slug order, the order the index lists areas: {sorted(slugs)}")
    for path in sorted(register.rglob("*")):
        if path.is_dir() or path.name == ".DS_Store":
            continue
        rel = path.relative_to(ROOT)
        depth = len(path.relative_to(register).parts)
        if depth == 1 and path.name != "index.yaml":
            errors.append(f"{rel}: sits flat under docs/decisions/ — a decision lives in docs/decisions/<area>/")
        elif depth == 2 and path.suffix != ".md":
            errors.append(f"{rel}: only .md files and the index belong in the register")
        elif depth > 2:
            errors.append(f"{rel}: sits a level below an area, where the index does not read")
    on_disk = {p.name for p in register.iterdir() if p.is_dir()}
    errors.extend(f"docs/decisions/{slug}/: no row in CLAUDE.md's Key Decisions table — add the row with the area" for slug in sorted(on_disk - set(slugs)))
    errors.extend(f"CLAUDE.md: the '{area}' row names docs/decisions/{slug}/, which does not exist" for area, slug in table if slug not in on_disk)
    titles = {slug: area for area, slug in table}
    for slug in sorted(on_disk):
        if not (register / slug / f"{slug}.md").exists():
            errors.append(f"docs/decisions/{slug}/ has no {slug}.md — an area's concept is what names it")
    for slug, path in _register_files():
        rel = path.relative_to(ROOT).as_posix()
        fields = read_frontmatter(path)
        if path.name in ("index.md", "log.md"):
            errors.append(f"{rel}: is named {path.name}, which OKF reserves — a decision takes a name of its own")
        if fields.errors:
            errors.extend(_refusals(rel, fields))
            continue
        errors.extend(f"{rel}:{n}: '{line.strip()}' is a title line — the title's one home is the frontmatter"
                      for n, line in _body_prose(path, fields.body_line) if line.startswith("# "))
        errors.extend(_listed_scalars(rel, fields, ("governs",) if path.stem == slug else ()))
        if path.stem == slug:
            if fields.keys.get("type") != "Decision Area":
                errors.append(f"{rel}: type is {fields.keys.get('type')!r}, not 'Decision Area' — {slug}.md is the area concept")
            if not fields.keys.get("title", "").strip():
                errors.append(f"{rel}: frontmatter has no `title` — the area name the Key Decisions row repeats")
            elif slug in titles and fields.keys["title"] != titles[slug]:
                errors.append(f"{rel}: title {fields.keys['title']!r} is not what CLAUDE.md's row says, {titles[slug]!r}")
            if "governs" not in fields.lists:
                errors.append(f"{rel}: `governs` is not a flow list — write `governs: [dir/**]`, or `governs: []` for none")
            if "status" in fields.keys:
                errors.append(f"{rel}: an area concept carries no `status`; a decision does")
            continue
        if fields.keys.get("type") != "Decision":
            errors.append(f"{rel}: type is {fields.keys.get('type')!r}, not 'Decision' — every .md in an area but its concept is one decision")
        if not fields.keys.get("title", "").strip():
            errors.append(f"{rel}: frontmatter has no `title` — the decision label")
        fence = fields.keys.get("description", "")
        if not fence.strip():
            errors.append(f"{rel}: has no fence — its frontmatter has no `description`, the claim and its constraint in one line")
        elif len(fence.encode()) > FENCE_MAX_BYTES:
            errors.append(f"{rel}: its fence is {len(fence.encode())} bytes (cap {FENCE_MAX_BYTES}): {fence[:70]}… — the reasoning goes in the entry below")
        if FENCE_LINK_RE.search(fence):
            errors.append(f"{rel}: its fence holds a markdown link, and a fence is read in the index, where a path relative to this file is dead — name the file in backticks")
        status = fields.keys.get("status")
        if status == "draft":
            errors.append(f"{rel}: status is 'draft' — a register holds settled decisions; an unsettled one belongs in its spec")
        elif "status" in fields.keys and status not in ("stable", "deprecated"):
            errors.append(f"{rel}: status {status!r} is not stable or deprecated (absent means stable)")
        errors.extend(_decision_body_problems(rel, fields, path))
    return errors


def check_indexes() -> list[str]:
    """Regenerate each index and refuse a committed copy whose bytes differ.

    The frontmatter is the authority and an index a view of it, written by ``gen-index.sh`` and
    never by hand. The generator is deterministic, so a byte comparison is a freshness check. It
    refuses a tree it cannot read, and a refusal is reported here rather than read as an empty
    index.

    Args:
      None.

    Returns:
      One message per missing, stale or refused index.

    Raises:
      None.
    """
    errors = []
    for tree, rel in (("specs", "docs/specs/index.yaml"), ("decisions", "docs/decisions/index.yaml")):
        # Both operands are ours: a constant script path and a constant tree name.
        done = subprocess.run(  # noqa: S603
            ["sh", GEN_INDEX, "--print", tree],  # noqa: S607
            cwd=ROOT, capture_output=True, check=False)
        if done.returncode != 0:
            reason = done.stderr.decode(errors="replace").strip()
            errors.append(f"{rel} cannot be regenerated, because {GEN_INDEX} refused the tree:\n{reason}")
            continue
        committed = ROOT / rel
        if not committed.exists():
            errors.append(f"{rel} is missing — run `sh {GEN_INDEX}` and commit what it writes")
        elif committed.read_bytes() != done.stdout:
            errors.append(f"{rel} is stale against the frontmatter — run `sh {GEN_INDEX}` and commit what it writes; a conflict in an index is resolved the same way, never by hand")
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
                    f"ARCS.md: '{heading}' carries status. Each spec's spec_status owns status — "
                    "a heading that repeats it goes stale without anyone noticing."
                )
                break
        if anchor(heading) not in listed:
            errors.append(f"ARCS.md: '{heading}' is missing from the arc list at the top")
    return errors


def spec_status(path: pathlib.Path) -> str | None:
    """A spec's ``spec_status``, lower-cased, or ``None`` when it has none or cannot be read.

    One reader for the checks that key on it, so they cannot disagree about what counts as a
    status. ``None`` is what makes ``check_spec_shape`` judge an unreadable spec in full.

    Args:
      path: The spec.

    Returns:
      The status, normalised; ``None`` if the frontmatter does not state one.

    Raises:
      None.
    """
    status = read_frontmatter(path).keys.get("spec_status")
    return status.lower() if status else None


def _classified_lines(text: str) -> list[tuple[int, str, str]]:
    """Every line of a document, with its 1-based number and what kind of line it is.

    One scanner for every check that reads prose. A leading frontmatter block is taken verbatim and
    opens no state: a fence saying ``Strip <!-- markers.`` is a value, not a comment. A comment closes
    before a fence opens, so a fence marker quoted inside a comment cannot swallow the rest of the
    file; a one-line ``<!-- ... -->`` is stripped rather than skipped, so a heading with a trailing
    note still counts. A ``<!--`` written in a code span opens nothing. A fence closes only on a run
    of its own character at least as long as the one that opened it, with nothing after it, so a
    four-backtick fence can quote a three-backtick one and an opener with an info string cannot close
    anything. Both exclusions are load-bearing for every check that reads headings: a spec quoting
    one in an example, or commenting one out while splitting, would otherwise be judged on text it
    does not carry.

    Args:
      text: The document's full text.

    Returns:
      ``(line number, line, kind)``, in order. ``kind`` is ``frontmatter``, ``prose``, ``comment``,
      ``marker`` (a fence's own line) or ``code`` (inside a fence). A ``prose`` line has its one-line
      comments removed.

    Raises:
      None.
    """
    lines = text.splitlines()
    found: list[tuple[int, str, str]] = []
    start = 0
    if lines and lines[0].rstrip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
        if close is not None:
            start = close + 1
            found.extend((i + 1, lines[i], "frontmatter") for i in range(start))
    fence = None
    in_comment = False
    for index in range(start, len(lines)):
        number, raw = index + 1, lines[index]
        if in_comment:
            in_comment = "-->" not in raw
            found.append((number, raw, "comment"))
            continue
        marker = FENCE_MARKER_RE.match(raw)
        if fence:
            closes = marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip()
            if closes:
                fence = None
            found.append((number, raw, "marker" if closes else "code"))
            continue
        if marker and not (marker.group(1)[0] == "`" and "`" in marker.group(2)):
            fence = marker.group(1)
            found.append((number, raw, "marker"))
            continue
        line = re.sub(r"<!--.*?-->", "", raw)
        if "<!--" in ANY_CODE_SPAN_RE.sub("", line):
            in_comment = True
            found.append((number, raw, "comment"))
            continue
        found.append((number, line, "prose"))
    return found


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """A document's lines outside fenced blocks and HTML comments, each with its 1-based number.

    Args:
      text: The document's full text.

    Returns:
      ``(line number, line)`` pairs, in order, the frontmatter included, with inline comments removed.

    Raises:
      None.
    """
    return [(number, line) for number, line, kind in _classified_lines(text) if kind in ("frontmatter", "prose")]


def check_spec_status() -> list[str]:
    """Require a Completed spec to have delivered.

    Args:
      None.

    Returns:
      One message per Completed spec with no delivery doc.

    Raises:
      None.
    """
    specs = ROOT / "docs" / "specs"
    delivery = ROOT / "docs" / "spec-delivery"
    return [
        f"SPEC-{path.name[5:8]} is Completed with no docs/spec-delivery/ write-up"
        for path in sorted(specs.glob("SPEC-*.md"))
        if spec_status(path) == "completed" and not list(delivery.glob(f"SPEC-{path.name[5:8]}-*.md"))
    ]


def check_spec_frontmatter() -> list[str]:
    """Hold every spec's frontmatter to its keys, and the cross-spec claims those keys make.

    The frontmatter is the one home of a spec's title, status and dependencies, and the index is
    generated from it, so this is what makes the index worth reading: the reader's refusals, the
    required keys, ``type``, ``id`` against the filename, the status vocabulary, that every
    ``depends_on`` names a spec in the directory and not itself, that no dependency leads back to
    the spec, that a Superseded spec and only a Superseded spec names a real successor, the arc keys
    both or neither, no two specs in one arc place, no spec depending on one later in its own arc, no
    two files sharing a number, nothing in the directory but specs, ``ARCS.md`` and the index, and that neither a bold header line nor a
    ``# `` title survives in the body as a second copy. Cross-spec lookups resolve from FILENAMES,
    so one broken neighbour does not cascade into a failure on every spec that names it.

    Args:
      None.

    Returns:
      One message per problem.

    Raises:
      None.
    """
    paths = sorted((ROOT / "docs" / "specs").glob("SPEC-*.md"))
    known: dict[str, list[str]] = {}
    errors_named: list[str] = []
    for path in paths:
        prefix = re.match(r"SPEC-\d+", path.name)
        if prefix:
            known.setdefault(prefix.group(0), []).append(path.name)
        else:
            errors_named.append(f"docs/specs/{path.name}: the filename has no SPEC-<number> prefix, so its id cannot be checked against it")
    numbers: dict[int, list[str]] = {}
    for spec, names in known.items():
        numbers.setdefault(int(spec[5:]), []).extend(names)
    errors = [*errors_named, *(f"docs/specs/: spec number {number} is shared by {', '.join(sorted(names))} — two specs cannot have one number"
                               for number, names in sorted(numbers.items()) if len(names) > 1)]
    errors.extend(f"docs/specs/{entry.name}: only specs named SPEC-<number>-<slug>.md, ARCS.md and the index belong here — nothing reads anything else"
                  for entry in sorted((ROOT / "docs" / "specs").iterdir())
                  if entry.name not in ("ARCS.md", "index.yaml", ".DS_Store") and not fnmatch.fnmatch(entry.name, "SPEC-*.md"))
    arcs: dict[str, dict[str, int]] = {}
    places: dict[tuple[str, int], str] = {}
    depends: dict[str, list[str]] = {}
    for path in paths:
        rel = f"docs/specs/{path.name}"
        prefix = re.match(r"SPEC-\d+", path.name)
        fields = read_frontmatter(path)
        if fields.errors:
            errors.extend(_refusals(rel, fields))
            continue
        keys = fields.keys
        errors.extend(_listed_scalars(rel, fields, ("depends_on",)))
        for key in ("type", "id", "title", "description", "spec_status"):
            if not keys.get(key, "").strip():
                errors.append(f"{rel}: frontmatter has no `{key}` — a spec carries type, id, title, description, spec_status and depends_on")
        if keys.get("type") and keys["type"] != "Spec":
            errors.append(f"{rel}: type is {keys['type']!r}, not 'Spec'")
        if keys.get("id") and prefix and keys["id"] != prefix.group(0):
            errors.append(f"{rel}: id {keys['id']!r} is not the filename prefix {prefix.group(0)} — the id and the filename name one spec")
        if keys.get("spec_status") and keys["spec_status"] not in SPEC_STATUSES:
            errors.append(f"{rel}: spec_status {keys['spec_status']!r} is not one of {', '.join(SPEC_STATUSES)}")
        if "depends_on" not in fields.lists:
            errors.append(f"{rel}: depends_on is not a flow list — write `depends_on: [SPEC-001, SPEC-002]`, or `[]`")
        own = prefix.group(0) if prefix else ""
        deps = fields.lists.get("depends_on", [])
        for dep in deps:
            if dep == own:
                errors.append(f"{rel}: depends_on names {dep}, which is this spec")
            elif dep not in known:
                errors.append(f"{rel}: depends_on names {dep}, but no {dep}-*.md is in the spec directory")
        if len(set(deps)) != len(deps):
            errors.append(f"{rel}: depends_on lists a spec twice")
        depends[own] = deps
        successor = keys.get("superseded_by")
        if keys.get("spec_status") == "Superseded" and not successor:
            errors.append(f"{rel}: is Superseded with no `superseded_by` naming what replaced it")
        if successor:
            if keys.get("spec_status") != "Superseded":
                errors.append(f"{rel}: has a `superseded_by` but is {keys.get('spec_status')!r}, not Superseded")
            if successor == own:
                errors.append(f"{rel}: superseded_by names {successor}, which is this spec")
            elif successor not in known:
                errors.append(f"{rel}: superseded_by names {successor}, but no {successor}-*.md is in the spec directory")
        arc, order = keys.get("arc"), keys.get("arc_order")
        if bool(arc) != bool(order):
            errors.append(f"{rel}: arc and arc_order go together — arc names the arc, arc_order the place in it")
        elif arc:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", arc):
                errors.append(f"{rel}: arc {arc!r} is not a slug")
            if not re.fullmatch(r"[1-9][0-9]*", order or ""):
                errors.append(f"{rel}: arc_order {order!r} is not a positive integer")
            else:
                place = (arc, int(order or 0))
                if place in places:
                    errors.append(f"{rel}: arc {arc!r} has arc_order {order} here and in {places[place]} — give each spec its own place")
                places[place] = path.name
                arcs.setdefault(arc, {})[own] = int(order or 0)
        for number, line in _body_prose(path, fields.body_line):
            if line.startswith("# "):
                errors.append(f"{rel}:{number}: '{line.strip()}' is a title line — the title's one home is the frontmatter")
            elif SPEC_HEADER_LINE.match(line):
                errors.append(f"{rel}:{number}: '{line.strip()[:50]}' is a bold header line — its value's one home is the frontmatter")
    for members in arcs.values():
        for spec, order in members.items():
            for dep in depends.get(spec, []):
                if members.get(dep, 0) > order:
                    errors.append(f"docs/specs: {spec} depends on {dep}, which comes later in its own arc — the authored order contradicts the dependency")

    def leads_back(start: str) -> bool:
        seen: set[str] = set()
        stack = list(depends.get(start, []))
        while stack:
            spec = stack.pop()
            if spec == start:
                return True
            if spec not in seen:
                seen.add(spec)
                stack.extend(depends.get(spec, []))
        return False

    errors.extend(f"docs/specs: {spec}'s depends_on leads back to itself — a cycle, so no build order exists"
                  for spec in sorted(depends) if spec and leads_back(spec))
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
        if spec_status(path) == "cancelled":
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
    placeholder — ``[Feature Name]``, ``[Requirement Name]``, ``SPEC-XXX`` — and ``### FR-``
    headings with no ``Acceptance Criteria`` anywhere.

    The check reads the spec outside fenced blocks and HTML comments (``_prose_lines``), so a
    heading quoted in an example or commented out is not a heading.

    WHO IS EXEMPT, and why it fails closed. The Completed specs written from an earlier template
    carry ``#### Checkpoint`` and ``## Open Questions`` headings, and a Cancelled spec is a
    tombstone with nothing to require. Rewriting sixty closed files to satisfy a rule that governs
    specs still being built would be churn with no reader, so ``SPEC_SHAPE_EXEMPT`` skips them —
    keyed on ``spec_status`` alone. Everything else is judged in full: no status,
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
        if spec_status(path) in SPEC_SHAPE_EXEMPT:
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


#: A heading that declares the directory the tables beneath it cover: its text ENDS in that
#: directory as a code span in parentheses, the form every inventory page's H1 takes. A deeper
#: heading in the same form re-bases the tables under it, until the next heading at its level or
#: above; one page does this, for route components that live outside its feature.
INVENTORY_BASE_RE = re.compile(r"^(#{1,6}) .*\(`([^`]+/)`\)\s*$")

#: A File-column code span that names a file, or a directory when it ends in ``/``. No segment
#: may begin with a dot. A ``..`` would never resolve anyway, since no directory listing holds
#: one, but it would be reported as a missing file, which is false of a row whose file is there.
INVENTORY_NAME_RE = re.compile(
    r"^(?:[\w@+-][\w.@+-]*/)*[\w@+-][\w.@+-]*\.[A-Za-z0-9]+$|^(?:[\w@+-][\w.@+-]*/)+$"
)

#: A table's delimiter row, the one line that makes the line above it a header. Tables are found
#: by it rather than by a leading pipe, so an indented table, or one written without outer pipes,
#: is read like any other instead of being skipped. The lookahead keeps a bare ``---`` out.
INVENTORY_DELIMITER_RE = re.compile(r"^ {0,3}(?=.*\|)\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")

#: ``*.tsx`` in a File cell: each symbol in the row, in a file of its own name.
INVENTORY_GLOB_RE = re.compile(r"^\*(\.[A-Za-z0-9]+)$")

#: A tombstone: a row recording that a file was deleted, which is a claim that it is ABSENT.
INVENTORY_GONE_RE = re.compile(r"`([^`]+)` is \*\*gone\*\*")

#: One name as a Symbol-column span writes it: the name, then calls, type arguments and members
#: (``useFeature(key)``, ``Result<T>``, ``keys.list(id)``), each one bracket deep. The name is the
#: first group.
ONE_NAME = r"([A-Za-z_$][\w$]*)(?:\([^()]*\)|<[^<>]*>|\.[A-Za-z_$][\w$]*)*"

#: A span that claims a name: ``ONE_NAME``, matched whole.
INVENTORY_NAME_SPAN_RE = re.compile(ONE_NAME)

#: The same, written as a JSX tag, ``<FeatureGate flag>`` or ``<Gizmo/>``, matched whole. Its props
#: hold no angle bracket outside an ``{expression}``, so a second tag after the first cannot pass
#: as a prop while ``onChange={(v) => set(v)}`` still can.
INVENTORY_JSX_SPAN_RE = re.compile(r"<([A-Za-z_$][\w$]*)(?:[\s.](?:\{[^{}]*\}|[^<>{}])*)?/?>")

#: What stands between a code span and the one before it when it is that span's return: an arrow,
#: and nothing else.
INVENTORY_RETURN_RE = re.compile(r"\s*(?:→|->)\s*")

#: A span that is a return, matched whole: a shape ``{status, error}`` or a tuple ``[a, b]``, one
#: bracket deep, or a type written as ``ONE_NAME`` alone or in a union (``string | null``). A
#: return claims nothing, so this is what keeps a second claim from riding in one.
INVENTORY_RETURN_SPAN_RE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]|" + ONE_NAME + r"(?:\s*\\?\|\s*" + ONE_NAME + r")*")

#: Block comments that open a line, with the spaces after each. ``_exported_names`` removes them
#: first, so a declaration left commented out in one is not read as live, and one written after
#: them on the same line (``/** Doc. */ export function x``) is. The ``/*`` must be followed by
#: ``*``, a space or the line's end, so a glob such as ``/*.csv`` opening a line of a template
#: literal is not taken for a comment; a ``/* `` that does open such a line is, and an export
#: between it and the next ``*/`` goes unread, which fails the row naming it, loudly.
LEADING_BLOCK_COMMENT_RE = re.compile(r"^[ \t]*(?:/\*(?=[*\s]).*?\*/[ \t]*)+", re.MULTILINE | re.DOTALL)

#: A declaration exported where it is written: ``export const x``, ``export async function x``,
#: ``export default function X``, ``export type X``, ``export * as ns from`` and TypeScript's
#: other declaration keywords. Anchored at the start of a line, so an export quoted in a line
#: comment or a JSDoc line, or indented inside a ``declare module`` block, is not the file's own.
#: One at the start of a line inside a template literal, or inside a block comment opened
#: mid-line, is read as the file's, since nothing short of a parser tells those apart.
EXPORT_DECLARATION_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:abstract\s+)?"
    r"(?:function\s*\*?\s*|\*\s*as\s+|(?:const\s+enum|const|let|var|class|type|interface|enum|namespace)\s+)"
    r"([A-Za-z_$][\w$]*)", re.MULTILINE)

#: An export list, ``export {a, b as c}`` or ``export type {A} from './a'``, over as many lines as
#: it takes. Its items are read by ``EXPORT_ITEM_RE``.
EXPORT_LIST_RE = re.compile(r"^export\s+(?:type\s+)?\{([^}]*)\}", re.MULTILINE)

#: One item of an export list. An item exported ``as`` another name is exported by that name only.
EXPORT_ITEM_RE = re.compile(r"(?:type\s+)?([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?")

#: ``export default name;``: a binding declared earlier in the file, exported as its default.
EXPORT_DEFAULT_NAME_RE = re.compile(r"^export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$", re.MULTILINE)

#: The files whose exports are read. A Markdown page or a stylesheet exports nothing, and a code
#: sample at the start of a line in one would otherwise read as an export of its directory.
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _spelled_exactly(path: pathlib.Path, directory: bool) -> bool:
    """Whether ``path`` exists with every component in the case the doc spells it.

    ``Path.exists`` says yes to ``uploadlist.tsx`` on macOS, whose default filesystem ignores
    case, and no on the Linux runner, so a row naming the wrong case would pass the session that
    wrote it and fail CI. Matching each component against its directory's entries makes the two
    agree.

    Args:
      path: An absolute path, normally under ``ROOT``; one outside it is not there.
      directory: Whether a directory is wanted rather than a file.

    Returns:
      ``True`` when every component is an entry of its parent and the last is of the wanted kind.

    Raises:
      None.
    """
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        return False
    current = ROOT
    for part in parts:
        try:
            entries = os.listdir(current)
        except OSError:
            return False
        if part not in entries:
            return False
        current = current / part
    return current.is_dir() if directory else current.is_file()


def _inventory_paths(name: str, base: pathlib.Path) -> list[pathlib.Path]:
    """Where a File-column name is, if it is where its row says it is.

    A bare name must be IN the directory the page declares: letting it match further up would let
    an ``index.ts`` resolve to some other folder's. A name carrying a slash is a path the row
    spells out, and rows spell them from different roots — ``features/auth/useAuth.ts`` from
    ``src/``, ``src/types/archive.types.ts`` from the portal — so it is read against the declared
    directory and each directory above it, up to the repository root and never past it. Every
    reading that exists is returned, so a nearer file of the same spelling does not hide the one
    the row means.

    Args:
      name: The name as the cell spells it; a trailing ``/`` names a directory.
      base: The directory the page declares for this row.

    Returns:
      Each reading of the name that exists in the case it is spelled, nearest first.

    Raises:
      None.
    """
    anchors = [base]
    if "/" in name.rstrip("/"):
        anchors += [p for p in base.parents if p == ROOT or ROOT in p.parents]
    return [a / name.rstrip("/") for a in anchors if _spelled_exactly(a / name.rstrip("/"), name.endswith("/"))]


def _inventory_names(symbol_cell: str) -> tuple[list[str], list[str]]:
    """The names a row's Symbol cell claims, and what is wrong with any span that hides one.

    Every code span is matched WHOLE by one form, or refused. ``name``, ``name(args)``,
    ``Name<T>``, ``Name.member`` and the JSX tag ``<Name prop>`` each claim ``Name``
    (``INVENTORY_NAME_SPAN_RE``, ``INVENTORY_JSX_SPAN_RE``). Two forms claim nothing, and each
    must follow another span: a return, with an arrow and nothing else before it, which is a
    type, a union, a shape or a tuple (``INVENTORY_RETURN_RE``, ``INVENTORY_RETURN_SPAN_RE``); and
    a member, ``.list(…)``, continuing the span before it. Any other span is refused, because
    whatever a span carries past one name — ``Role/Status``, ``mock*``, ``*Props``,
    ``useX() / useY()`` — is a claim that, read as its first name, is half checked, and skipped,
    is not checked at all. Brackets are read one deep, so a nested call or type argument is
    refused too, and says so.

    Args:
      symbol_cell: The row's Symbol cell, stripped; empty when the table has none.

    Returns:
      The names claimed, in order, and one message per span refused.

    Raises:
      None.
    """
    names: list[str] = []
    problems: list[str] = []
    end: int | None = None
    for match in CODE_SPAN_RE.finditer(symbol_cell):
        span, between, follows = match.group(1), symbol_cell[end or 0:match.start()], end is not None
        end = match.end()
        if follows and INVENTORY_RETURN_RE.fullmatch(between) and INVENTORY_RETURN_SPAN_RE.fullmatch(span):
            continue
        if follows and span.startswith(".") and INVENTORY_NAME_SPAN_RE.fullmatch(span[1:]):
            continue
        one = INVENTORY_NAME_SPAN_RE.fullmatch(span) or INVENTORY_JSX_SPAN_RE.fullmatch(span)
        if one:
            names.append(one.group(1))
        else:
            problems.append(f"`{span}` in the Symbol column is not one name, so what it claims cannot be "
                            "read — write each name in a code span of its own, as `name`, `name(args)`, "
                            "`Name<T>`, `name.member` or `<Name prop>`, with brackets one deep. After "
                            "another span, a return follows an arrow, and a member `.x(…)` continues it")
    return names, problems


@functools.cache
def _exported_names(path: pathlib.Path) -> frozenset[str]:
    """The names a source file exports, read from its text.

    Declarations (``EXPORT_DECLARATION_RE``), export lists with or without ``from``
    (``EXPORT_LIST_RE``) and ``export default name;`` (``EXPORT_DEFAULT_NAME_RE``) are read, after
    a byte-order mark and every block comment that opens a line (``LEADING_BLOCK_COMMENT_RE``) are
    removed. ``export *`` without ``as`` is not followed, so a name that reaches a file only
    through one is not that file's, and its row is pointed at the file that declares it. A
    destructured or multi-declarator ``export const`` is read as its first name at most, and a row
    naming another of its names fails, loudly.

    Args:
      path: A file a row names; one whose suffix is not in ``SOURCE_SUFFIXES`` exports nothing.

    Returns:
      Every name the file exports, by the name it is exported as; a default export counts by the
      name it is declared with, since that is the name a route's row gives it.

    Raises:
      None.
    """
    if path.suffix not in SOURCE_SUFFIXES:
        return frozenset()
    text = LEADING_BLOCK_COMMENT_RE.sub("", path.read_text(encoding="utf-8-sig", errors="replace"))
    names = set(EXPORT_DECLARATION_RE.findall(text)) | set(EXPORT_DEFAULT_NAME_RE.findall(text))
    for body in EXPORT_LIST_RE.findall(text):
        for item in re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.DOTALL).split(","):
            item_match = EXPORT_ITEM_RE.fullmatch(item.strip())
            if item_match:
                names.add(item_match.group(2) or item_match.group(1))
    return frozenset(names)


def _table_cells(line: str) -> list[str]:
    """A markdown table row's cells, split on unescaped pipes, with the outer pipes optional.

    Args:
      line: One row of a table, its header or its body.

    Returns:
      The cells in order, each stripped.

    Raises:
      None.
    """
    body = line.strip().removeprefix("|")
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def _inventory_row_problems(file_cell: str, symbol_cell: str, base: pathlib.Path, where: str) -> list[str]:
    """What is wrong with one inventory row, if anything: its File cell, then its Symbol cell.

    Four File-cell forms are read, each found in the inventory rather than assumed. A code span is
    a file, or a directory when it ends in ``/`` (the "moved to" rows); a cell may carry several
    however they are separated, since only the spans are read. ``(same folder)`` and ``*.tsx``
    stand for each symbol in the row in a file of its own name, so the Symbol cell supplies the
    names, and ``(same folder)`` is honoured beside other names in the cell rather than only
    alone. And a span followed by "is **gone**" records a deletion, which is checked the other way
    round: the tombstone is false once the file is back. Anything else is refused rather than
    skipped, because a cell this check cannot read is a row it has quietly stopped checking.

    Then each name the Symbol cell claims (``_inventory_names``) must be exported
    (``_exported_names``) by a file the row names: a source file span, any source file directly in
    a directory span, or, under ``(same folder)`` and ``*.tsx``, the name's own file. ONE of them is
    enough, since a row of several files puts each symbol in one, so a symbol moving between two
    files of the same row is not caught. A file outside ``SOURCE_SUFFIXES`` exports nothing, so a
    name filed only in one is refused as such. A name with no file to read — every span a
    tombstone, or one not there, which is reported above — is not checked. And a row that names
    source must name a symbol, or neither the derived forms nor residency has anything to read:
    that is also what catches a table whose ``Symbol`` column was renamed, whose every row would
    otherwise pass.

    Args:
      file_cell: The row's File cell, stripped.
      symbol_cell: The row's Symbol cell, stripped; empty when the table has none.
      base: The directory the page declares for this row.
      where: ``base`` as a message names it.

    Returns:
      One message per claim that does not hold, empty when the row holds.

    Raises:
      None.
    """
    gone = set(INVENTORY_GONE_RE.findall(file_cell))
    spans = CODE_SPAN_RE.findall(file_cell)
    derived: list[tuple[str, tuple[str, ...]]] = []
    if "(same folder)" in file_cell:
        derived.append(("(same folder)", (".tsx", ".ts")))
    elif not spans:
        return [(f"the File cell {file_cell!r} names nothing in backticks, so nothing about it can be "
                 "checked — write the file as a code span, or `(same folder)` for symbols each in a "
                 "file of their own name")]
    names, problems = _inventory_names(symbol_cell)
    homes: list[tuple[str, list[pathlib.Path]]] = []
    foreign: list[str] = []
    for span in spans:
        glob = INVENTORY_GLOB_RE.match(span)
        if glob:
            derived.append((f"`{span}`", (glob.group(1),)))
            continue
        if not INVENTORY_NAME_RE.match(span):
            problems.append(f"`{span}` in the File column is neither a file nor a directory name, so "
                            "nothing about it can be checked — write one path per code span, with no "
                            "`.` or `..` segment, and end a directory with `/`")
            continue
        paths = _inventory_paths(span, base)
        if span in gone:
            if paths:
                problems.append(f"`{span}` is recorded as gone, but it exists — the tombstone is false")
        elif not paths:
            nested = "/" in span.rstrip("/")
            above = " or any directory above it" if nested else ""
            scope = "" if nested else " (a name with no slash inside it is read in that directory only)"
            problems.append(f"`{span}` is not in {where}{above} — the row has outlived its file: "
                            f"delete it, point it at where the symbol lives now{scope}, or record a "
                            f"deliberate deletion as `{span}` is **gone**")
        elif span.endswith("/"):
            homes.append((f"any source file directly in `{span}`",
                          sorted(p for d in paths for p in d.iterdir() if p.is_file())))
        elif span.endswith(SOURCE_SUFFIXES):
            homes.append((f"`{span}`", paths))
        else:
            foreign.append(f"`{span}`")
    names_source = derived or any(span.endswith("/") or span.endswith(SOURCE_SUFFIXES)
                                  for span in spans if span not in gone)
    if names_source and not names:
        problems.append(f"the Symbol cell {symbol_cell!r} names no symbol this check can read, so nothing "
                        "the row points at can be checked — write each symbol as `name`, `name(args)` "
                        "or `<Name prop>`, one per code span, in a column headed `Symbol`")
    for name in names:
        own: list[tuple[str, list[pathlib.Path]]] = []
        for form, suffixes in derived:
            found = [(f"`{name + suffix}`", own_paths) for suffix in suffixes
                     if (own_paths := _inventory_paths(name + suffix, base))]
            if not found:
                files = " or ".join(name + suffix for suffix in suffixes)
                problems.append(f"`{name}` is filed as {form}, but {files} is not in {where}")
            own += found
        places = homes + own
        if places and not any(name in _exported_names(p) for _, found_paths in places for p in found_paths):
            problems.append(f"`{name}` is not exported from {' or '.join(label for label, _ in places)}. "
                            "If it is a symbol, the row has outlived it: delete the name, or point the "
                            "row at the file that exports it now. If it is not, write it where no name "
                            "is read: a prop inside `<Name prop>`, a return after `→`, a value outside "
                            "a code span")
        elif not places and foreign:
            problems.append(f"`{name}` is filed only in {' or '.join(foreign)}, which is not source and "
                            "exports nothing — point the row at the source file that exports it")
    return problems


def check_inventory_files() -> list[str]:
    """Refuse a component-inventory row whose File column names a file that is not there, or
    whose Symbol column names something that file does not export.

    The inventory is where a session looks for what to reuse, so a row for a deleted file sends
    it after code that does not exist. One for a floating upload panel outlived its file by
    months, because nothing read the column against the tree. A row whose symbol moved to a
    sibling file does the same while its file is still there, which is why the Symbol column is
    read against the file's exports too.

    Every page but the router declares the directory it covers in its H1, as ``# Title
    (`apps/portal/src/<dir>/`)``, and a deeper heading in the same form re-bases the tables under
    it (``INVENTORY_BASE_RE``). A page that declares nothing is read against its own folder: that
    is where the router's File column of sibling-page links resolves, and where any other page
    that lost its declaration would fail loudly rather than pass. Tables are found by their
    delimiter row (``INVENTORY_DELIMITER_RE``), and how a cell is read is
    ``_inventory_row_problems``.

    Three positive controls, because a table this parser stops reading passes exactly like a table
    with nothing wrong in it: the directory must yield pages, every table must have a ``File``
    column, and every page must yield at least one row. The per-table control is the one with
    teeth. One good table satisfies the per-page control, and before the per-table control existed
    two tables that named their files only in a heading went unread without a word. The Symbol
    column's control is per row, in ``_inventory_row_problems``: a row that names source must name
    a symbol, which is also what a table whose ``Symbol`` column was renamed fails.

    Args:
      None.

    Returns:
      One message per claim that does not hold, per declared directory that is not there, per
      table without a ``File`` column, and per page the check read nothing from.

    Raises:
      None.
    """
    directory = ROOT / INVENTORY_DIR
    pages = sorted(directory.rglob("*.md")) if directory.is_dir() else []
    if not pages:
        return [(f"{INVENTORY_DIR}/ holds no pages — this check read nothing, and a check that read "
                 "nothing reads exactly like a clean one. If the inventory moved, move INVENTORY_DIR "
                 "with it.")]
    errors = []
    for page in pages:
        rel = page.relative_to(ROOT)
        lines = page.read_text().splitlines()
        bases = {0: page.parent}
        columns: list[str] | None = None
        rows = 0
        for index, line in enumerate(lines):
            number = index + 1
            heading = re.match(r"(#{1,6}) ", line)
            if heading:
                level = len(heading.group(1))
                bases = {k: v for k, v in bases.items() if k < level}
                declared = INVENTORY_BASE_RE.match(line)
                if declared:
                    bases[level] = ROOT / declared.group(2)
                    if not _spelled_exactly(bases[level], directory=True):
                        errors.append(f"{rel}:{number}: declares `{declared.group(2)}`, which is not a "
                                      "directory in this repository, so no row under it can be checked")
                columns = None
                continue
            if columns is not None and line.strip():
                if "File" not in columns:
                    continue
                rows += 1
                base = bases[max(bases)]
                if not _spelled_exactly(base, directory=True):
                    continue
                where = f"`{base.relative_to(ROOT).as_posix()}/`"
                if max(bases) == 0:
                    where += (" (no heading above the row declares a directory in the form "
                              "`# Title (`dir/`)`, so the row is read against the page's own folder)")
                cells = _table_cells(line)
                file_index = columns.index("File")
                file_cell = cells[file_index] if file_index < len(cells) else ""
                symbol_index = columns.index("Symbol") if "Symbol" in columns else len(cells)
                symbol_cell = cells[symbol_index] if symbol_index < len(cells) else ""
                errors.extend(f"{rel}:{number}: {problem}"
                              for problem in _inventory_row_problems(file_cell, symbol_cell, base, where))
                continue
            columns = None
            if index and lines[index - 1].strip() and INVENTORY_DELIMITER_RE.match(line):
                columns = _table_cells(lines[index - 1])
                if "File" not in columns:
                    errors.append(f"{rel}:{index}: a table headed {' | '.join(columns)!r} has no `File` "
                                  "column, so none of its rows can be checked. An inventory table is "
                                  "headed | Symbol | File | Purpose |.")
        if not rows:
            errors.append(f"{rel}: no row read from a table with a `File` column — this check cannot "
                          "see the page, and a page it cannot see passes. An inventory table is "
                          "headed | Symbol | File | Purpose |.")
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
    each decision's fence, which carries the pointers the digest carried when it lived in CLAUDE.md
    — the identity fences point at the API plane page, for one. A pointer is only a cut worth
    making while it resolves, and nothing else here reads it — ``check_links`` matches
    ``[text](target)`` markdown links, and ``check_doc_paths_everywhere`` walks code suffixes, so
    a bare ``@`` pointer in a ``.md`` file falls between them. Verified by planting a broken one,
    which passed the whole suite.

    Args:
      None.

    Returns:
      One message per ``@`` pointer in an always-loaded file or a fence that names a
      ``.md`` file under ``DOC_TREES`` and does not resolve. Deliberately narrow, and the gaps are
      real: a pointer to a DIRECTORY (``@docs/testing/``), to a tree outside ``DOC_TREES``
      (``@scripts/…``), or with the tree itself misspelt (``@doc/process/INDEX.md``) is invisible
      to this, and CLAUDE.md carries live pointers of the first kind. Widening it needs the glob
      placeholder (``@docs/specs/SPEC-XXX-*.md``) handled deliberately rather than by accident of
      this character class.

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
    for _, path in _register_files():
        fence = read_frontmatter(path).keys.get("description")
        if fence:
            sources.append((f"{path.relative_to(ROOT).as_posix()} (fence)", fence))
    errors = [
        f"{name}: points at a missing doc -> @{target}"
        for name, text in sources
        for target in sorted(set(pattern.findall(text)))
        if not (ROOT / target).exists()
    ]
    errors.extend(
        f"{name}: imports @{target} bare, which loads the whole index every session — write the pointer in backticks"
        for name, text in sources
        for target in sorted(set(re.findall(r"(?<!`)@(docs/(?:specs|decisions)/index\.yaml)", text)))
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
    "Files matching these paths are governed by the **{area}** decisions in `docs/decisions/{slug}/`.\n"
    "Read the area's fences in `docs/decisions/index.yaml` first — they are not loaded with CLAUDE.md.\n"
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
    """Require one path-scoped pointer rule per area that governs code, and nothing else in it.

    ``.claude/rules/decisions-<slug>.md`` is Claude Code's mechanism for loading a file only when a
    matching source file is read. Here each rule is a backstop that points a session touching an
    area's code at that area's fences; the fence itself has one home, in the register. So a rule
    is held to being exactly that: named for the area, a ``paths`` list at byte 0 equal to what the
    area's concept declares in ``governs``, whose every glob matches something in the tree, and a
    body that IS the rendered ``RULE_BODY`` and nothing more, because a committed rule
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
      One message per governing area without a rule, per rule for no area or for an area that
      governs nothing, per glob ``governs`` and ``paths`` disagree on, and per rule breaking the shape.

    Raises:
      None.
    """
    rules_dir = ROOT / ".claude" / "rules"
    expected = {}
    for area, slug in decision_table():
        concept = ROOT / "docs" / "decisions" / slug / f"{slug}.md"
        governs = read_frontmatter(concept).lists.get("governs") if concept.exists() else None
        expected[f"decisions-{slug}"] = (area, slug, governs)
    found = {p.stem: p for p in rules_dir.glob("*.md")} if rules_dir.is_dir() else {}
    errors = [
        f".claude/rules/{stem}.md is missing — every area that governs a tree has one pointer rule"
        for stem, (_, _, governs) in expected.items()
        if stem not in found and governs
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
            errors.append(f"{rel}: names no Key Decisions area — a rule is a pointer to an area's fences, nothing else")
            continue
        area, slug, governs = expected[stem]
        if governs == []:
            errors.append(f"{rel}: its area governs nothing (`governs: []`), and an area that governs no tree has no rule")
            continue
        text = path.read_text()
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            errors.append(f"{rel}: does not open with a ----fenced frontmatter block — Claude Code would load it every session")
            continue
        frontmatter, body = text[4:].split("\n---\n", 1)
        extra_keys = re.findall(r"^[^\s:]+:", frontmatter, re.MULTILINE)
        if extra_keys != ["paths:"] and extra_keys and extra_keys[0] == "paths:":
            errors.append(f"{rel}: its frontmatter holds {extra_keys[1:]} as well as `paths:` — a rule is a path scope and nothing else")
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
        if governs is not None:
            errors.extend(f"{rel}: lists {glob!r}, which the area's `governs` does not" for glob in globs if glob not in governs)
            errors.extend(f"{rel}: does not list {glob!r}, which the area's `governs` does" for glob in governs if glob not in globs)
        if body.strip() != RULE_BODY.format(area=area, slug=slug).strip():
            errors.append(f"{rel}: body is not the rendered RULE_BODY for '{area}' — a rule is a pointer to the area's fences and nothing else")
    return errors


FOOTNOTE_RE = re.compile(r"\[\^([^\]\s]+)\]")


def _rulebook_problems(path: pathlib.Path, now: datetime.datetime) -> list[str]:
    """What is wrong with one rulebook: its keys, its sources, its date and its citations.

    A rulebook states rules an agent follows without checking them, so a rule resting on a
    version-specific fact says where the fact came from, by a footnote whose label is the source's
    id. Code spans and fenced blocks are skipped, so a regex such as ``[^a-z]`` written in a rule
    is not read as a footnote.

    Args:
      path: The rulebook.
      now: The current instant, UTC.

    Returns:
      One message per problem; a rulebook inside its warning window yields one ``WARNING`` message.

    Raises:
      None.
    """
    rel = path.relative_to(ROOT).as_posix()
    fields = read_frontmatter(path)
    if fields.errors:
        return _refusals(rel, fields)
    errors = _listed_scalars(rel, fields, ())
    keys = fields.keys
    if keys.get("type") != "Rulebook":
        errors.append(f"{rel}: type is {keys.get('type')!r}, not 'Rulebook'")
    errors.extend(f"{rel}: frontmatter has no `{key}`" for key in ("title", "description", "stale_after") if not keys.get(key, "").strip())
    if not fields.sources:
        errors.append(f"{rel}: frontmatter has no `sources` — a rulebook says where its version-specific facts came from")
    ids: list[str] = []
    by_id: dict[str, dict[str, str]] = {}
    for number, source in sorted(fields.sources.items()):
        errors.extend(f"{rel}: source {number} has no `{key}`" for key in ("id", "resource", "title") if not source.get(key))
        if source.get("id") in ids:
            errors.append(f"{rel}: source id {source['id']!r} is used twice")
        if source.get("id"):
            ids.append(source["id"])
            by_id[source["id"]] = source
        if source.get("resource") and not re.fullmatch(r"https?://\S+", source["resource"]):
            errors.append(f"{rel}: source {number}'s resource {source['resource']!r} is not a URL")
    stale_after = keys.get("stale_after", "")
    if stale_after:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stale_after):
                raise ValueError(stale_after)
            when = datetime.datetime.strptime(stale_after, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)
        except ValueError:
            errors.append(f"{rel}: stale_after {stale_after!r} is not a real YYYY-MM-DDTHH:MM:SSZ instant")
        else:
            if now >= when:
                errors.append(f"{rel}: is stale since {stale_after}: re-fetch every source it cites, correct any rule a source no longer supports, and move stale_after forward about a year")
            elif now >= when - datetime.timedelta(days=STALE_WARNING_DAYS):
                errors.append(f"{WARNING}{rel}: goes stale at {stale_after}, and this gate fails from then on: re-fetch every source it cites, correct any rule a source no longer supports, and move stale_after forward about a year")
    prose = _body_prose(path, fields.body_line)
    defined: set[str] = set()
    cited: set[str] = set()
    for number, line in prose:
        definition = re.match(r"^\[\^([^\]\s]+)\]:", line)
        if definition:
            name = definition.group(1)
            if name in defined:
                errors.append(f"{rel}:{number}: footnote [^{name}] is defined twice")
            defined.add(name)
            line = line[definition.end():]
            if name not in ids:
                errors.append(f"{rel}:{number}: footnote [^{name}] names no source in the frontmatter")
            elif by_id[name].get("resource", "") not in line or by_id[name].get("title", "") not in line:
                errors.append(f"{rel}:{number}: footnote [^{name}]'s definition does not give its source's title and URL")
        for reference in FOOTNOTE_RE.findall(ANY_CODE_SPAN_RE.sub("", line)):
            cited.add(reference)
            if reference not in ids:
                errors.append(f"{rel}:{number}: footnote [^{reference}] names no source in the frontmatter")
    errors.extend(f"{rel}: footnote [^{name}] is cited and never defined" for name in sorted(cited - defined))
    errors.extend(f"{rel}: source {name!r} is cited nowhere — a source that supports no version-specific rule is cited once, in the opening paragraph" for name in ids if name not in cited)
    return errors


def check_rulebooks() -> list[str]:
    """Hold every rulebook to its frontmatter and its sources, and to the date they must be re-read by.

    Reads the clock as well as the tree, the one check here that does: the same commit passes before
    the instant and fails after it. ``STALE_WARNING_DAYS`` says why this gate warns first, where the
    template does not. There is no "now" override, which would be a bypass; the corpus uses dates
    far in the past and future, and one computed from today for the window.

    Args:
      None.

    Returns:
      One message per problem, and one when no rulebook was found at all, since a check that read
      nothing reads exactly like a clean one.

    Raises:
      None.
    """
    now = datetime.datetime.now(datetime.UTC)
    books = [path for tree in RULEBOOK_TREES if (ROOT / tree).is_dir() for path in _docs_in(tree) if path.name != "INDEX.md"]
    if not books:
        return [f"no rulebook found under {', '.join(RULEBOOK_TREES)} — this check read nothing. If they moved, move RULEBOOK_TREES with them."]
    return [problem for path in books for problem in _rulebook_problems(path, now)]


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
        check_indexes,
        check_rules,
        check_rulebooks,
        check_process_router,
        check_arcs,
        check_spec_frontmatter,
        check_spec_status,
        check_spec_shape,
        check_spec_size,
        check_delivery_size,
        check_source_citations,
        check_test_citations,
        check_workflow_table,
        check_links,
        check_inventory_files,
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
