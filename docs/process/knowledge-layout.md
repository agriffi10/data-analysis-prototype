# The knowledge layout

Specs, decisions and rulebooks carry YAML frontmatter in the shape of the Open Knowledge Format
(OKF v0.2): a `type`, a `title`, a one-sentence `description`, and the keys each kind needs. The
frontmatter is the **one home** of what it states — a spec's status, a decision's fence, a
rulebook's sources — and the indexes are generated from it, never written by hand. The layout is the
spec-driven template's; this file states it as this repo holds it, where the one gate is
`scripts/validate_docs.py`, in CI, rather than the template's `spec-lint.sh` and `docs-lint.sh`.

The governed files conform to OKF on their own; the trees that hold them are not claimed as OKF
bundles (`docs/specs/ARCS.md` and each `best-practices/INDEX.md` are routers with no frontmatter). The
process parts, the templates and `architecture.md` carry no frontmatter, and nothing records a
`generated` or `verified` claim: a review is recorded by its PR, and a self-attestation no check can
confirm is not a record.

## Frontmatter

The governed files are `docs/specs/SPEC-*.md`, every `.md` under `docs/decisions/<area>/`, and every
`.md` but `INDEX.md` under `apps/portal/info/best-practices/`, `lambdas/info/best-practices/` and
`docs/best-practices/`. (A `.claude/rules/` file's frontmatter is Claude Code's format, held by
`check_rules`, not by this.)

One reader, `scripts/frontmatter.awk`, reads them for `validate_docs.py` and `gen-index.sh` alike, so
an index is never generated from one reading of a file and linted against another. It and the generator
are taken whole from the template, so a later take-down replaces two files rather than re-porting them.
It is not a YAML parser. It holds frontmatter to the subset below, and **a line that is not one of
these forms FAILs, naming its line and the rule it broke — it is never skipped**: a reader that skips
what it does not understand reports a file it never read as one that passed.

| Form | Rule |
|---|---|
| line 1 is `---` | nothing comes before it — not a heading, a blank line or a byte-order mark |
| a later line that is exactly `---` | closes the frontmatter; the body starts on the next line |
| `key: value` | a lowercase key (letters, digits, `_`) at column 0 and exactly one space after the colon. A plain value may not start with ``- ? : , [ ] { } # & * ! \| > ' " % @ ` ``, hold `: ` or ` #`, or end in `:` — double-quote such a value |
| `key: "value"` | on one line; `\"` and `\\` are the only escapes, and nothing follows the closing quote |
| `key: [a, b]` or `key: []` | a flow list on one line; each element a plain word holding no bracket, brace, quote, `:` or `?` |
| `sources:` | the one block list. `  - field: value` (two spaces, a dash, a space) opens an item and `    field: value` (four spaces) continues it; each field is a plain or double-quoted value |

Refused by name: a duplicate key (YAML keeps the last copy, so the two disagree silently), a blank
line, a comment, a tab, a control character, any other indentation, a block scalar, a flow map, a
single-quoted value, an anchor, alias or tag, a value continued onto a second line, and a bare `key:`
other than `sources:`. Each is a place where YAML errors or, worse, reads something other than what
was written. CRLF line endings are read.

**Known limitation**, stated so nobody mistakes it for a check: a plain value YAML would read as a
boolean, a null or a number (`No`, `null`, `1.0`) is read here as text. Double-quote it when text is
meant. **Write `title` and `description` always double-quoted**, escaping `\` as `\\` and `"` as `\"`,
and no character in them can collide with the subset.

### A spec's keys

| Key | Holds |
|---|---|
| `type` | `Spec` |
| `id` | `SPEC-<number>`, equal to the filename's prefix |
| `title` | the feature's name — the spec carries no `#` title line; this is its one home |
| `description` | one sentence: what it delivers, and for whom |
| `spec_status` | `Draft`, `In Progress`, `Completed`, `Cancelled` or `Superseded` (`spec-lifecycle.md`) |
| `depends_on` | a flow list of spec ids, `[]` for none |
| `arc`, `arc_order` | both or neither: the arc's slug and the spec's place in it, a positive integer |
| `superseded_by` | a spec id, on a `Superseded` spec |

`spec_status`, not OKF's `status`: OKF's `status` is about trust (`draft` means unreviewed), and a
reader who knows OKF would take our Draft — reviewed, not started — for unreviewed work. There is no
*Last Updated*: it was hand-kept and unverifiable, and `git log` is the record. For a new spec,
`depends_on` is the build order and nothing looser: a spec that merely mentions another says so in prose.
A migrated spec's list is its old *Depends On* line read literally, which is looser in places, a precedent
or a rule it inverts among them, and its notes say which. A
**`**Dependency notes:**`** line in a spec's body is where the migration kept what the old *Depends On*
said about each dependency; it is optional, and a new spec writes it only when there is something to
say.

`check_spec_frontmatter` holds every one of these: the reader's refusals, the required keys, `type`,
`id` against the filename, the status vocabulary, that every `depends_on` names a spec in the
directory and not itself, that no dependency leads back to the spec, the arc keys, that no two specs
share an arc place, that no spec depends on one later in its own arc, that no two files share a
number, and that neither a bold header line (`**Status:** …` and kin) nor a `# ` title line survives
in the body as a second copy of the frontmatter. `ARCS.md` keeps the **why** of an arc; the order is
in the frontmatter.

## Generated indexes

`docs/specs/index.yaml` and `docs/decisions/index.yaml` are views of the frontmatter, written by
`sh scripts/gen-index.sh` and **never edited by hand** — the first line of each says so. Run it after
any frontmatter change and commit what it writes. `check_indexes` regenerates each one and fails the
committed copy when the bytes differ or it is missing; the generator is deterministic (no timestamps,
fixed sorts, every string double-quoted) so that comparison is exact. A merge conflict in an index is
resolved by regenerating on the merged frontmatter, never by hand.

The generator **refuses** a tree — writes nothing for it and leaves the committed index as it was —
when any file in it cannot be read or lacks a key the index lists, and the gate reports the refusal.
(The generator is the template's, so its message names the template's linters; here the check that
names the line is in `validate_docs.py`, printed beside it.)
Specs are listed by number, then every arc by name with its specs in `arc_order`; areas by directory
name, and each area's decisions by file name.

They are YAML and lowercase because OKF reserves `index.md` for a frontmatter-free markdown listing.
The pointers to them are written in backticks, never as bare `@` imports: the decisions index is far
too large to load every session. **Read one area's block, not the file.**

## The decision register

The settled decisions, in full: **one file per decision, in one directory per area** —
`docs/decisions/<area>/`. `CLAUDE.md`'s Key Decisions table names the areas, and the index lists every
area's fences. Read your area's block before working in it, and open a decision's file only when you
need its reasoning. **Don't re-litigate these.**

| File | Frontmatter | Body |
|---|---|---|
| `<area>/<area>.md` — the area concept | `type: Decision Area`; `title`, the area name the `CLAUDE.md` row repeats; `governs`, a flow list of globs (`[]` for none) | what the area settles, and its settled shape |
| `<area>/<decision>.md` — one decision | `type: Decision`; `title`, its label; `description`, its **fence** — the claim and its constraint; `status`, optional: `stable` or `deprecated` (absent means stable) | its **entry** — what was decided and why, what was rejected, the do-NOT-build lines — then `## History` |

The words stay the register's own: a decision's **fence** is its `description`, its **entry** is its
body. **An entry belongs to the area a reader would look in, not to the arc that produced it.** Rules
that keep the register useful (each earned by a real failure in a project run this way):

- **A fence is never the only home of a fact.** The body above History says what was decided and why;
  the gate fails a decision with no entry, and caps a fence at `FENCE_MAX_BYTES` — past that it has
  become the reasoning. Every decision has a fence, including a per-feature choice: write it short, so
  the area's block stays readable, and keep the longest fences for what applies green and fails later.
  A fence is read in the index, so it holds no markdown link (the gate refuses one): name a file in
  backticks. A fence states its own decision's constraint first, and a trap whose reasoning is in another
  file belongs on that file's fence.
- **A new decision never touches `CLAUDE.md`.** It is a new file in its area. Only a new *area* is a
  new row there: a new directory, its area concept, its rule, and the row — in slug order, the order
  the index lists areas. A decision that fits no area means the table needs a new row, not a loose file.
- **A decision's file name is chosen once and never changes** — conventionally the slug of its first
  title. A reversal rewrites the title in place; renaming would break every link to it and split its
  history across two files.
- **A decision's file is its whole thread.** When a decision is reversed or refined, rewrite its
  current statement — title, fence, entry — in place, and add a dated History entry at the top saying
  what changed and why. `status: deprecated` is only for a decision retired with no replacement, and
  **deprecating one is a reversal too**: the gate fails a deprecated decision whose newest History
  entry does not say so. The file is never deleted. Every *other* doc site still stating the old claim
  — an `ARCS.md` arc, an `architecture.md` section — gets a superseded marker (a short blockquote: what
  changed, which spec changed it, where the decision lives): a reader who lands only there must see the
  reversal.
- **A decision that changes the SHAPE of the system also gets a row** in `docs/architecture.md` →
  *Architecture Decision Record*. That row is an index entry and points back at the decision's file.
- **History is last, dated and newest first.** `## History` closes the body: one `### YYYY-MM-DD`
  heading per date, newest first, at least one — the first is when the decision was settled — with the
  entries as bullets.
- **No `#` title line in the body.** The title has one home, the frontmatter.
- **`status` is `stable` or `deprecated`, never `draft`.** A register holds settled decisions; an
  unsettled one belongs in its spec until it settles.
- **Declare what an area governs.** `governs` lists the code trees the area's fences apply to, or `[]`.
  An area that governs a tree has a path-scoped rule at `.claude/rules/decisions-<area>.md`, with
  exactly those globs and the body `RULE_BODY` renders, so its fences fire when a matching file is
  opened with Read; an area that governs none has no rule.

`check_decisions_register` holds the shape: the table's rows name the area directories by their titles,
in slug order, every row a directory and every directory a row; every area has its concept; every file
reads through the shared reader and carries the keys for its kind; a decision has a fence, an entry
above its History — a line that says something, not a lone heading or comment — a well-formed History
with no date after today, a `status` in the vocabulary, and a deprecation recorded in the newest History
entry; no title line in a body; nothing flat under `docs/decisions/` or a level below an area, and no
decision named `index.md` or `log.md`, which OKF reserves. `check_always_loaded_pointers` holds the
pointers in each fence, and `check_rules` holds the rules to `governs` both ways.

## Rulebooks

A rulebook (`<tree>/info/best-practices/<domain>/<domain>.md`) states rules an agent follows without
checking them, so where a rule rests on a **version-specific fact** — a WCAG level, a React release,
a PEP — it says where the fact came from. The frontmatter carries `type: Rulebook`, `title`,
`description`, `sources` and `stale_after`; each `sources` item carries `id`, `resource` (the URL)
and `title`. The rule cites its source with a markdown footnote whose label **is** the source id —
`…is AA in WCAG 2.2.[^wcag22]` — and the definition at the foot of the file gives the title and URL.
Footnoting every rule is not the aim; a source that supports no version-specific rule is cited once,
in the rulebook's opening paragraph, on the claim it does support.

**A source is fetched and read before it is cited, and it must support the sentence that cites it.**
A fabricated or unread citation is the defect this layer exists to prevent; when a fetched source
contradicts the rule, the rule is corrected, not the citation dropped. A reviewer re-fetches every
source in the diff.

`stale_after` is the date by which the sources must be read again: an ISO 8601 instant in UTC,
`YYYY-MM-DDTHH:MM:SSZ`. Set it about a year out. **This is the one check that reads the clock as well
as the tree**, and here it differs from the template, which fails on the date and keeps that check out
of CI because a clock-driven red lands on unrelated work. This repo's gate is CI, so
`STALE_WARNING_DAYS` before the date it **warns on every run**, and from the date it **fails**. The
remedy is the message's own text: re-fetch every source, correct any rule a source no longer supports,
move `stale_after` forward. A re-read is one short PR, so a warning is the moment to do it. There is no
"now" override, which would be a bypass.

`check_rulebooks` holds the reader's refusals, `type: Rulebook`, the four keys, each source's three
fields, unique ids, the `stale_after` form and date, every footnote reference defined and naming a
source, and every source cited at least once. Code spans and fenced blocks are skipped, so a regex such
as `[^a-z]` written in a rule is not read as a footnote.
