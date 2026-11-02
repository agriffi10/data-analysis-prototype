# Completion ritual


When a spec is done, in the same pass:
1. Set `spec_status: Completed` in the spec's frontmatter.
2. Run `sh scripts/gen-index.sh` and commit what it writes (the status has one home, the frontmatter;
   `docs/specs/index.yaml` is generated). Run it again after step 5 if that step added a decision.
3. Write a **short** delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from
   `docs/templates/spec-completion-template.md` — *what shipped + what changed*, typically under a
   page (~40–100 lines), with **no code/JSON pasted** (the code + component-inventory are the
   source of truth for reuse).
4. If reusable services/hooks/components were added, add a **one-line** row to the
   `apps/portal/info/component-inventory/<area>.md` **matching the component's path** — a `features/query/` row
   belongs in the query area file, nowhere else (the router only changes if a whole new area appeared).
5. A *new decision* gets its own file in the matching `docs/decisions/<area>/` — its entry in the
   body, its **fence** in the `description`, and a `## History` saying when it settled
   (`knowledge-layout.md` → *The decision register*). A fence is **never the only home of a fact**, and
   never the reasoning. CLAUDE.md's own Key Decisions section is a table of the areas, and a close
   touches it only when the set of areas changes. A decision that **supersedes an earlier one** has
   two dispositions. The old **decision's file is rewritten in place** — title, fence, entry — with a
   dated History entry at the top saying what changed and why, not left standing beside its reversal.
   Every **other** doc site still stating the old claim gets an in-place superseded marker — a short
   blockquote naming what changed, which spec, and where the decision lives — meaning arc
   narratives in `ARCS.md` and `architecture.md` sections. The rewrite alone is not enough; an
   agent reading only the old site must see the reversal. Reasoning lives in the spec/delivery
   doc.
6. **If the decision changed the SHAPE of the system** — a new piece, a piece removed, a boundary
   moved, a mechanism swapped — add a row to `docs/architecture.md` → *Architecture Decision Record*
   **and** update the prose section it contradicts. The row is an index entry: number, title,
   one-line context, a short note, linking to the register entry. Rows are **append-only and never
   renumbered**; a superseded decision keeps its row and gains a note naming the row that replaced
   it. Most decisions do **not** qualify — a rule, a fence or a per-feature choice is a register
   entry and nothing more, and a table that grows a row per spec has stopped being an orientation
   aid.
7. **Prune CLAUDE.md's `## Specs`** of whatever the closed spec made stale. It carries
   only what is live and undocumented elsewhere — never append a changelog.
8. **Live checks fold into the one guide.** A spec that owes a live check adds its steps to the
   matching feature section of `docs/testing/e2e.md` — **not** a new per-spec or per-arc file, which is
   how that directory grew to sixteen. A spec whose check cannot be run from a signed-in browser
   session adds a row to `docs/testing/owed.md` saying why and what it would take. An arc still in
   flight may keep one temporary script of its own (`docs/testing/<arc>-e2e.md`); it is folded into
   `e2e.md` and deleted when the arc closes.

   **A CLI script in `docs/testing/fixtures/` is named for the PLANE, never for a spec.** Four
   specs build one control plane, and a script each is four files sharing a token read, a queue
   URL, a group digest and an envelope builder — four copies of one digest, of which one is
   eventually wrong. A spec that owes a CLI check adds a **section** to its plane's script and
   points its `owed.md` row at that section. The count is a ratchet: a second plane needing one is
   a deliberate edit to `validate_docs.py`, not a directory that grew a spec at a time.

9. **User-facing docs sweep.** If the spec added, changed, or removed a capability a user can see, update the
   surfaces that describe it — first and foremost the in-app **Help & guides** content
   (`apps/portal/src/features/help/helpContent.ts`, SPEC-074), plus any README / onboarding copy. New shipped
   feature → add/adjust its guide; changed flow/labels → fix the steps; removed feature → delete its guide.
   The help module is code-grounded by contract (SPEC-074 FR-005), so **only document what's shipped and wired
   end-to-end** — a Draft or infra-less feature stays out until it ships. If nothing user-facing changed, say so
   and move on. (This step exists because help content silently drifts as features land; SPEC-073's join status
   and the table-builder arc, for instance, shipped after SPEC-074 was authored and had to be folded in.)

**Anti-regrowth & doc hygiene** (each rule below was earned by a defect the 2026-08-03 doc sweep found).

> **`scripts/validate_docs.py` enforces the structural half of these rules and runs on every PR**
> (`ci.yml` → *Validate the documentation layout*). It holds: `docs/testing/` to the guide, the
> ledger, the log and at most **one** in-flight arc script; `docs/testing/fixtures/` to
> plane-named scripts within a ratchet, refusing a spec-numbered one outright; the number of specs
> carrying more than 8 FRs to a ratchet at the measured level (`authoring-a-spec.md`); `CLAUDE.md`
> to a byte budget; **the two always-loaded process files — `INDEX.md` and `session-rhythm.md` in
> this directory — to a byte budget of their own,** since CLAUDE.md's first instruction is to read
> them and they therefore cost every session what CLAUDE.md costs; the `docs/decisions/` register
> to one directory per row of CLAUDE.md's Key Decisions table in slug order, each decision a file with
> a capped fence, an entry and a dated History; both generated indexes to being byte-fresh; one pointer
> rule per governing area under `.claude/rules/`, path-scoped, holding its area's `governs` and nothing
> but the rendered pointer; every rulebook to its sources, its footnotes and its `stale_after`; every
> `ARCS.md` arc to a status-free heading that is in the arc list; every spec's frontmatter to its keys
> and every Completed spec to having a delivery doc; every delivery doc to a line cap; and every
> relative markdown link to resolving (`knowledge-layout.md` is the prose of the frontmatter half). **The budgets are
> ratchets just above the measured level** (SPEC-150's convention for the coverage floors) —
> raising one so a growing doc passes is the failure mode the gate exists to catch. Move the detail
> down a tier instead, or **defer the addition**, which is always available for an addition. How
> much room each ratchet leaves, and for what, is in `validate_docs.py`'s constants docstring,
> where a person changing one reads it. The shape rules are what bind the fences: group by area,
> one fence per decision, and a length cap on each. Every rule it holds existed in prose first and was
> violated anyway; that is why it is a gate.


- **Documentation lives beside the code it describes.** A page named for a source file, a module or
  a directory belongs in that tree's `info/`, not in `docs/`; `docs/` carries what spans trees or
  belongs to no tree. The test is where a reader is standing when they need it — someone changing a
  verb is in `lambdas/`, and a doc they must leave the tree to find is a doc they will not open. A
  606-line `docs/lambda-rationale.md` whose every entry was named for a Lambda source file is how
  this rule was learned.
- **One organising axis per subject, and one doc that owns it.** If a subject is documented per-plane,
  exactly one place is per-plane. `architecture.md` and `lambdas/info/planes/` both carried a section
  per control plane; 58% of `architecture.md` was the duplicate half, and the two had already
  diverged. A second doc on the same axis is not redundancy, it is a fork with no merge.
- **A register is grouped by AREA; ordering it by spec number turns it into a changelog.** The
  question a reader arrives with is "what has been settled about X", never "what did SPEC-143
  decide". `decisions/` sat in spec order for 195 entries and read as something disposable — which
  it is not, since it is the only home of the rejected alternatives and the fences. The index and
  the register **group by the same areas**, so a reader who finds an area in one finds it in the other.
- **When a doc moves, the pointers that rot unseen are in SOURCE files** — `.py` docstrings, `.tf`
  comments, `.yml` steps. `validate_docs.py` walks those for exactly this reason; a markdown-only
  sweep reports the tree clean. Grep the path, not the filename, and fix the Draft specs too: a
  Draft is an unbuilt instruction, and pointing one at a deleted file sends the next builder nowhere.
- **A doc's own statement of when to read it must agree with CLAUDE.md's.** `process.md`, before it was split into this directory, told readers it
  was read once and on demand while CLAUDE.md told them to read it first, every session. Both are
  cheap to write and neither is checked, so they drift silently and the reader follows the wrong one.
- **A rebase resolves code hunks; it does not resolve CLAIMS.** Two branches editing the same
  docstring merge clean when their paragraphs sit at different offsets — no conflict marker — and the
  survivor asserts a thing and its opposite. A verb's docstring named the other members' membership
  slots as deliberately left uncleared; the change landing on top cleared them, and git took the two
  paragraphs as independent insertions because one sat above the shared sentence and one below.
  Nothing catches it: the suite is green either way, and `validate_docs.py` checks layout, links and
  citations rather than truth. After rebasing onto a branch that touched the same function, diff the
  **prose** against the upstream blob (`git show <upstream>:<path>`) and read the merged docstring
  end to end. Where your change falsifies a claim someone else just wrote, **delete their sentence** —
  merging alongside it is how the contradiction ships.
- **Status never appears in a heading**, anywhere. It rots the day the next spec lands, which is why
  `ARCS.md`'s headings are gated for it.
- **A heading in a doc read by SUBJECT names the subject, not the spec that produced it** — this is
  `architecture.md` and the tree `info/` pages, where a reader arrives asking "how does the archive
  plane work", never "what did SPEC-168 decide". The scope is deliberate and stops there: an entry in
  `decisions/` IS a record of what one spec settled, and its number is part of its identity when
  you are coming from a delivery doc or a superseded marker, so those headings keep theirs. A rule
  stated more broadly than that would be violated by 121 of that register's 195 headings on the day
  it was written, and a rule practice contradicts at scale trains readers to ignore the ones that
  hold.
- If a memory or doc disagrees with the code, fix or delete it — don't let stale state accumulate.
  Don't add prose to the always-loaded tier.
- **Standing rules never cite volatile numbers** (line counts, row counts, section ranges) — state the
  principle. The numbers rot, and a rule resting on false evidence teaches readers to distrust it.
  **Dating the measurement does not save it**, which is the tempting half-fix: a dated number
  still reads as current to anyone not checking the date against the calendar. Anchor both ends
  of the evidence to a commit a reader can re-measure from, or state the principle and drop the
  number — `validate_docs.py`'s budget history is the shape to copy.
- **After a structural cut, RE-DERIVE every threshold rather than re-checking it.** A cap can be
  invalidated by its own success: the cut shrinks everything below it, and it can never fire again
  while still being advertised here as a fence. A check that passes proves nothing about a cap that
  cannot fail. The split of the always-loaded tier into routed files re-derived all three of its
  budgets for exactly this reason; how much room each leaves is in `validate_docs.py`'s constants
  docstring, where a person changing one reads it.
- **A rule practice consistently violates gets reconciled or deleted.** A dead rule trains agents to
  ignore the live ones.
- **Routers carry only what self-describes.** Hand-maintained metadata (symbol counts, "§1–§N" ranges)
  rots silently; drop it or let the structure carry the information.
- **Any doc pulled entry-by-entry gets one heading per entry plus a TOC**, and pointer phrases in
  other docs must match a greppable heading — "read the entry for your area" must be a jump, not a
  full-file read.
- **Live findings and obligations never live in historical or cancelled narrative** — rehome them to
  an active register (`security-baseline.md`, Current work) and leave a pointer behind.
