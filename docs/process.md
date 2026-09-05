# The Spec-Driven Development Process

How work gets done in this repo. CLAUDE.md carries the terse, always-loaded rules; this doc is the
fuller **method** they point to, and it is the contract CLAUDE.md only summarises. **Read it at the
start of every session, before any other doc** — CLAUDE.md's Session Workflow says the same.

Goal: each feature is **specified before it's built**, built in **reviewable phases**, landed as a
**single PR on green CI**, and recorded in **lean, layered docs** so the next session starts cheap.

---

## 1. Where truth lives (and why it's layered)

Two axes, and they answer different questions. **How often is it loaded** decides what may go in it:
the always-loaded tier was cut down from much larger versions and must not regrow, and the fix each
time is a pointer to a deeper tier, never a longer paragraph. **Which tree does it describe** decides
where it lives: documentation sits beside the code it is about, and `docs/` carries what spans trees
or belongs to no tree at all.

### Loaded every session

| File | Authoritative for |
|---|---|
| `CLAUDE.md` | conventions, the Key Decisions digest, the session workflow |
| `docs/process.md` (this file) | how we work — the method behind that summary |

### Pulled on demand, by tree

| Tree | Entry point | Holds |
|---|---|---|
| The app | `apps/portal/info/component-inventory/INDEX.md` | a **router** to per-area inventories of what already exists — read the area(s) your spec touches, never all |
| | `apps/portal/info/best-practices/` | the React and accessibility rulebooks |
| | `apps/portal/info/runtime-configuration.md` | the `/config.json` contract and the five places a key is wired |
| The lambdas | `lambdas/info/INDEX.md` | every function, grouped by control plane — a lookup, not a description |
| | `lambdas/info/planes/<plane>.md` | one page per plane: its machine, what it accepts, its fences, its layer, and the evidence behind its caps |
| | `lambdas/info/shared-layer.md` | `cpcommon`'s module map and the long-form *why* behind it |
| | `lambdas/info/deployment.md` | the code/infra split, and the traps that only bite on deploy |
| | `lambdas/info/best-practices/` | the Lambda-shape and Python rulebooks |
| The infrastructure | `infra/info/INDEX.md` | the module index and the shape every control plane shares |
| | `infra/info/deploy-role-iam.md` | the trap list for adding a new AWS resource type |
| | `infra/modules/<name>/README.md` | one README per module, beside its `.tf` |

`docs/best-practices/INDEX.md` is a **cross-tree router** — it names which rulebook lives in which
tree, and holds no rules of its own.

### Pulled on demand, spanning trees

| File(s) | Loaded | Authoritative for |
|---|---|---|
| `docs/specs/INDEX.md` + each spec header | on demand | spec **status**, one row per spec |
| `docs/specs/SPEC-XXX-*.md` | the one you're building | requirements + phases |
| `docs/specs/ARCS.md` | the arc you're in | why an arc exists, how its specs compose |
| `docs/architecture.md` | whole, when you need orientation | **how the system works** — the pieces, how a request travels, and the ADR table indexing the decisions that shaped it. Short by design; it holds no rules and no trap lists |
| `docs/decisions/INDEX.md` → one area file | the *entry* for your area | settled decisions in full and the "do NOT build" fences, **one file per area, matching CLAUDE.md's digest** |
| `docs/spec-delivery/SPEC-XXX-*.md` | when a dependency points to one | what a past spec shipped |
| `docs/testing/e2e.md` + `owed.md` + `sessions.md` | when running live checks | how to validate the deployed app, what is still owed, and what has actually been run |
| `docs/reviewer-contract.md` | when you are about to spend a reviewer | how many reviewers and where they run, briefing one, rotating the frame, and when to stop — the method behind §3's gate |
| `docs/templates/` | when authoring a spec or closing one | the spec and completion templates §4 and §5 start from |
| `docs/security-baseline.md` | before touching a scanner or a suppression | every shipped scanner finding and its written disposition |
| `docs/transition_plan.md` | before auth, provisioning or LF work | the client-environment transition |
| `docs/design/` | before changing visual language | the design system and the breakpoint reference |

**Context discipline (session-start token cost is a standing concern):**
- Read **only the current spec** in full.
- **Never** read a `decisions/` area file, `ARCS.md`, a plane page or a delivery doc whole — pull the
  one entry you need. Each is built so that is possible. `architecture.md` is the exception: it is
  sized to be read whole, and it is the cheapest way into a part of the system you have not touched.
- The inventories and the Lambda index are **routers**: read the row, then the one file it names.
- Delegate a *dependency's* delivery-doc reading to an Explore/subagent brief rather than loading it
  into the main loop.

---

## 2. The spec lifecycle

Specs move **Draft → In Progress → Completed** (the status in each spec's header is authoritative; the
`INDEX.md` row mirrors it).

- **Draft** — written, **reviewed by a fresh-context reviewer (§3, *The reviewer contract*)** and
  refined, but **do not build until told.** The user authors spec files incrementally, sometimes well
  ahead of implementation. A Draft spec being in the repo is not a signal to start it. A spec that has
  not been through the gate is not Draft-ready, whatever its header says.
- **In Progress** — exactly one spec at a time is in flight. Set when you branch to build it.
- **Completed** — merged on green CI, delivery doc written (see §5).
- **Cancelled** — the work is not being done, or not here. The file stays (every link to it stays
  live) and the row stays in `INDEX.md`. A spec cancelled because its work **can only be done in
  another environment** is reduced to a tombstone: why it was cancelled, where the design went, and
  what validating it against the built code found. Successor-account work belongs in
  [`transition_plan.md`](transition_plan.md), not in a spec — a spec nobody can build is a spec
  whose claims drift with no test to catch them (SPEC-204, 2026-09-01). `validate_docs.py` skips a
  Cancelled spec in the FR-count ratchet for that reason, and only a Cancelled one.

**Arcs.** Related specs are grouped into *arcs* (file-operations, analytics, query-editor UX,
shared-connections, notifications) with an explicit **build order** documented in
`docs/specs/ARCS.md`. Build in that order; arcs can have non-obvious dependencies (e.g. 056 before
051). Grouping is a choice; recording the order of a **size split** (§4) is not — a spec cut for
size always leaves an arc entry behind. An arc is also what an over-scoped spec *becomes*: a spec
that runs past the size ceiling in §4 is cured by a second spec beside it and an arc entry holding
the order, rather than by a longer spec.

---

## 3. The session rhythm

This is the operating loop, start to finish. CLAUDE.md's *Session Workflow* carries the entry
sequence and the gates whose specifics live nowhere else, and **points here for the rest rather
than restating it** — the second hand-synced copy is how the two drifted before (#595).
**If they ever disagree, CLAUDE.md wins** — fix the drift here in the same session you notice it.

**Start of session**
1. Read CLAUDE.md, then the **current** spec in full. Don't infer scope from a prior conversation —
   read the spec file as it exists now.
2. For reuse, read the `apps/portal/info/component-inventory/<area>.md` file(s) the spec touches, and
   the `lambdas/info/planes/<plane>.md` page for any plane it changes; pull only the
   `architecture.md` section / `decisions/` entry / dependency delivery-doc you actually need.
3. Confirm CI is green: `gh run list --branch main --limit 5`. Investigate failures before building.
4. **Branch from fresh `main`:** `git fetch && git switch -c <branch> origin/main`.
5. **Generate and validate a plan before writing code.** Turn the spec's Implementation Phases into a
   concrete implementation plan, then validate it against the spec (every FR + acceptance criterion is
   covered, reuse from the component inventory is used, no out-of-scope work crept in). The plan —
   not per-phase checkpoints baked into the spec — is what gates the work.
6. **Put the plan through the reviewer gate before the first line of code** (*The reviewer contract*,
   below). A plan is reviewed for the same reason a PR is: the author cannot see what they assumed.
7. **Put the PR grouping through the same gate**, before the first push. Group consecutive phases
   into as few PRs as the dependencies allow — a phase is a unit of work, not a unit of PR, and the
   useful boundaries are inert-vs-live, either side of a switchover, a deletion following its last
   caller, and infra that must apply before a live check.

**These two reviews are the only ones that gate the START of the build.** Once the plan and the
grouping have each been reviewed, the build runs to completion without checking in. This does
**not** retire the diff reviews — those gate the push, at the other end, and they are blocking
too. Four reviews stand between a spec going In Progress and its PR merging: one on the plan
before the first line of code, one on the PR grouping, and two on the diff — all four before the
first push. The user
confirmed the work when they set the spec going; a per-phase check-in re-asks a question already
answered, and on a twelve-phase spec it asks it twelve times.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- **An acceptance criterion that cannot settle before the push does not pass the pre-push review —
  it is recorded as owed on the PR.** A criterion that closes "against a green CI run" is
  undecidable while the branch is still local, and the failure mode is a reviewer ticking it
  vacuously. Name it in the PR body's **Owed** list, settle it on the green run, and do not merge
  until it is settled. This is a different ledger from `docs/testing/owed.md`, which holds live
  checks that cannot be run from a signed-in session at all; a criterion that merely needs CI to
  go green belongs on the PR and is discharged there.
- **The diff reviews run BEFORE the push, not before the merge — and there are two of them.** Commit
  locally, run the gates, send the diff to **two** fresh-context reviewers in **different frames**
  (*The reviewer contract*, below), fix or explicitly reject every finding — *then* push and open
  the PR. Pushing first and reviewing after inverts the gate: the branch is already public, the fixes
  arrive as follow-up commits, and the review reads as commentary on something that has already
  happened rather than as the thing that decides whether it should. Rotating the frame
  (`docs/reviewer-contract.md`) happens in the same window. A push is the point of no return for the review, the same way the merge is the
  point of no return for CI.
- Before pushing, run the **formatter, both linters, both suites, mypy and `npm run build`**
  locally, green by **exit code**. **CI runs the build and the validators, nothing else**, so this
  is the ONLY place the rest run: skip one and it reaches `main` behind a green PR. Traps: §6.
- Work the **reviewed** plan's phases in order, **straight through to completion**. Summarize a phase
  in passing where it is worth saying, but do not end the turn on it — a summary that ends the turn
  *is* a request for approval, whatever its wording says. Re-review the plan only if the phase
  changed it — a phase that revises the plan has produced a new artifact, and it goes through the
  gate as one.
- **Stop only for a question that genuinely needs an answer:** a product-changing or ambiguous call,
  a finding that changes scope, a phase discovering the plan was wrong. Reporting is not the same act
  as asking, and doing the first while intending the second is how the build stalls.
- Before writing code in a domain that has a rulebook (React, accessibility, Lambda shape, Python),
  route through `docs/best-practices/INDEX.md` — which names the tree each rulebook lives in — and
  load only the relevant section(s). Apply the rules as you write;
  flag (don't silently break) any that conflict with existing code.
- **When a finding is an instance of a RULE, re-audit the rule — not the line.** Fixing the one
  reported site leaves every other instance shipped, so enumerate the whole population first: that
  is the difference between a registry with a walking test and a hand-maintained checklist, and a
  hand-maintained list rots. Long form: `docs/reviewer-contract.md`.
- **Spot-check a negative claim before acting on it, and again before writing it down.** "No test
  covers this", "nothing imports this file", "it is only documented on page X" — each asserts an
  absence, which is what a search proves worst. Verify it yourself whether a reviewer said it or
  you did. A wrong claim entering **code** has tests to catch it later; one entering a spec, a
  register entry, a docstring or a commit message has nothing, and the next session reads it as
  settled. Long form, with the two that shipped as source comments and were believed for weeks:
  `docs/reviewer-contract.md`.
- **A mechanical sweep REPORTS before it applies.** Print what it would change, read the list, then
  re-run with `--apply`, and check the result by diffing **test names collected from the runner**
  — never a pass count, and never a source grep, which cannot see an `it.each` row. Parse rather
  than regex where a parser exists. Long form: `docs/reviewer-contract.md`.
- Specs ship with **no Open Questions** — they're resolved during authoring (§4). An issue that emerges
  mid-build is triaged by *kind*, not parked:
  - **Reversible / technical** (naming, file layout, which helper to reuse, an obvious bug fix): just
    decide in-session and keep moving. If it changes scope or contradicts the spec, **update the spec**
    rather than leaving the divergence implicit.
  - **Product-changing / ambiguous** (anything that alters behavior the user would notice, or a call
    with no clearly-right answer): **stop and escalate to the human.** Don't silently pick — surface the
    options with a recommendation. Auto-deciding these is how an autonomous run drifts away from what
    was actually wanted.

**The reviewer contract — three artifacts, one gate**

A **spec**, an implementation **plan** and a **diff** each go to a reviewer in a **fresh context** —
a new session or a subagent, never the context that produced them. A spec is not Draft-ready, a plan
does not start code, and **a branch does not reach the remote**, until every finding is either
**fixed** or **flagged**. The spec and the plan get one reviewer each; the diff gets two, in
different frames. A rejection costs a sentence out loud, and only goes in writing when it carries a
lesson worth keeping.

Cap same-frame rounds at two, then rotate. Exit on the **trajectory** of the findings — stop when a
fresh frame's worst finding is one that would not change the built result, and say which finding
that was — never on a round count, and never by waiting for an empty round.

**The method is `docs/reviewer-contract.md`** — how many reviewers and where they run, briefing one
(the four lines that change what comes back), rotating the frame, when a review changes a *rule*
rather than a line, and the worked evidence behind each. Read it when you are about to spend a
reviewer; it is not session-start material, which is why it is not in this file.

**An Open Question can wear a declarative sentence**

`CLAUDE.md` forbids a spec carrying Open Questions, and the check is easy to pass while failing.
SPEC-205 shipped the sentence *"either the exception moves to a shared location or `save_members`
returns a refusal the caller raises. The spec states which"* — and then did not. A sentence that
**promises a decision** is an Open Question with a declarative shape; so is an acceptance criterion
demanding a **computed** bound while supplying none of its inputs. Both were caught by an implementer
who had to pick, and neither by a reader.

**Landing the spec — watch PRs and watch `main`**
- **A branch reaches the remote already reviewed.** The gate above is the precondition for the push,
  so a PR opens carrying work whose findings are already fixed or answered. If a review
  round happens after a push anyway — a late finding, a rotated frame, a reviewer that ran long — its
  fixes are committed and reviewed locally before the next push, rather than each one going up as it
  lands.
- **Every PR is watched to completion and merged as soon as CI is green** — don't open a PR and walk
  away. A spec's PR merges only on green.
- **`main` is always watched.** After any merge, confirm `main`'s build went green. If `main` fails,
  **diagnose immediately and fix it with a new PR** — a red `main` is the top priority and blocks
  starting the next spec.
- **Re-verify `main` is green** before starting the next spec (land before starting the next).
- Then run the completion ritual (§5).

---

## 4. Authoring a spec

Specs are written from `docs/templates/spec-template.md`. **A spec touching lifecycle, IAM or
concurrency is planned with an execution harness rather than a review** — an import-time `_require`
in a shared layer fails at cold start only, and a concurrent-refresh race is a property of two
overlapping executions; neither is findable by reading (`docs/reviewer-contract.md`). What makes a
spec *buildable*:

- **Overview** — user/business intent, no implementation detail. Understandable cold.
- **Scope: In / Out** — explicitly list what's *excluded*, especially anything a reader would
  reasonably assume is included.
- **Functional Requirements** — one FR per discrete, testable behavior, with binary pass/fail
  **Acceptance Criteria** covering happy path, error path, and edges. Sequential IDs so a prompt can
  say "implement FR-001 through FR-003 only."
- **Size: aim for 3–6 FRs, and split above 8.** A spec is one coherent slice of behavior, not a
  feature's whole surface, and a spec past eight is not a big spec — it is a spec that should have
  been two. (Measured once, when this rule landed on 2026-08-31: the median spec carried 6 FRs and
  four in five carried 8 or fewer. A dated observation, not a standing claim about the corpus — §5
  forbids a rule resting on a number that rots.) The 3–6 aim sits at or below that median
  deliberately: it is where the method is going, not where it already is. Growing one spec is the
  wrong repair; the right one is a second spec beside it, with the pair's build order recorded in
  `ARCS.md` as an **arc** (§2). Splitting keeps paying off past the first cut — a three-spec arc
  reads better than one fourteen-FR spec, and each piece earns its own reviewed plan, its own
  review gate and its own delivery doc. Cut along a seam the system already has — a plane, a
  surface, a switchover, the point where something inert goes live — never at "FR-009, because that
  is where the count ran out." **The second spec restarts at FR-001**: IDs are spec-local, which is
  why a dependency cites them as "SPEC-111 FR-001" and never as a number on its own.
- **The ceiling is a ratchet, not a per-spec fail.** `validate_docs.py` holds the *number of specs*
  above 8 at the level it was measured at, in the same shape as every other budget in that file: a
  new over-size spec fails CI, the ones that predate the rule do not, and splitting one lowers the
  constant in the same PR. The number lives in `SPEC_OVERSIZE_MAX` and is deliberately not repeated
  here — two hand-synced copies of one number is how they drift (§3). A genuinely indivisible spec
  can still sit above the line, but it is paid for out of the ratchet, which means **raising
  `SPEC_OVERSIZE_MAX` by one in the same PR**, the way `CLAUDE_MAX_BYTES` was raised: a deliberate,
  argued edit rather than a reflex. Say why in one line under *Scope → In Scope*, and it is the
  reviewer's call to accept or reject — "it is all one feature" is the claim to be most skeptical
  of, because it is what every over-scoped spec says about itself.
- **Data Model / Interface Contract** — TypeScript shapes, not prose. Explicit types produce
  better-typed output. Note the target path (`src/types/…`).
- **Implementation Phases** — each phase is one session's worth of work and maps to a discrete,
  reviewable unit. Phases are the input to the implementation plan generated at build time (§3); don't
  bake per-phase checkpoints into the spec.
- **No Open Questions.** Resolve every decision while authoring — a spec doesn't move to Draft-ready
  with unanswered questions. Issues that only surface during the build are handled in-session (§3),
  not parked in the spec.
- **Then the reviewer gate** (§3, *The reviewer contract*). A freshly-authored spec goes to a
  fresh-context reviewer before it is Draft-ready, and its findings are fixed or answered.
  The commonest thing this catches is not a wrong requirement — it is an acceptance criterion that
  cannot fail, and an Out of Scope bullet that an FR quietly needs.

---

## 5. Completion ritual (keep the always-loaded tier lean)

When a spec is done, in the same pass:
1. Set the spec file header `Status: Completed`.
2. Update its one-line row in `docs/specs/INDEX.md` (**status only** — no prose).
3. Write a **short** delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from
   `docs/templates/spec-completion-template.md` — *what shipped + what changed*, typically under a
   page (~40–100 lines), with **no code/JSON pasted** (the code + component-inventory are the
   source of truth for reuse).
4. If reusable services/hooks/components were added, add a **one-line** row to the
   `apps/portal/info/component-inventory/<area>.md` **matching the component's path** — a `features/query/` row
   belongs in the query area file, nowhere else (the router only changes if a whole new area appeared).
5. A *new architectural decision* gets its full entry in the matching `docs/decisions/<area>.md`
   **first** — one `##` heading, listed in that file's Contents — then **one line** in CLAUDE.md's
   Key Decisions. The digest line is **never the only home of a fact**, and never a paragraph.
   **Add a clause, or replace one your decision supersedes**; do not add a line per spec, which is
   what took that section to 105 one-per-spec lines and drove the file into its byte ceiling
   before it was grouped by area. A decision that **supersedes an earlier one** has three
   dispositions, one per artifact. The superseded **digest clause is replaced**, not left
   standing beside its reversal. The old **register entry is updated in place**. Every
   **other** doc site still stating the old claim gets an in-place superseded marker — a short
   blockquote naming what changed, which spec, and where the full entry lives — meaning arc
   narratives in `ARCS.md` and `architecture.md` sections. The new entry alone is not enough; an
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
7. **Prune CLAUDE.md's `## Specs` → Current work** of whatever the closed spec made stale. It carries
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
> carrying more than 8 FRs to a ratchet at the measured level (§4); `CLAUDE.md` to a
> byte budget and each
> Key Decisions line to a length; **`docs/process.md` — this file — to a byte budget of its own,**
> since CLAUDE.md's first instruction is to read it and it therefore costs every session what
> CLAUDE.md costs; the `docs/decisions/` register to one file per digest area, each
> routed by its `INDEX.md`, with one heading level per entry and a Contents that reaches every one
> of them; every `ARCS.md` arc to a status-free heading that is in the arc list; every spec
> header to agreeing with its `INDEX.md` row and every Completed spec to having a delivery doc;
> every delivery doc to a line cap; and every relative markdown link to resolving. **The budgets
> are ratchets at the measured level** (SPEC-150's convention for the coverage floors) — raising
> one so a growing doc passes is the failure mode the gate exists to catch. Move the detail down a
> tier instead. **One exception carries deliberate headroom.** `CLAUDE_MAX_BYTES` is 50,000
> (user decision, 2026-08-27) because the
> completion ritual *mandates* growth — every closing spec that settles an architectural decision
> folds a clause into Key Decisions, so a ratchet there makes each completion a forced prune of
> some other area's fences, which is the gate causing the damage it exists to prevent.
> `PROCESS_MAX_BYTES` sits just above this file's measured size like every other budget here, and
> is **not** a second exception: nothing mandates appending to this file, so when an addition does
> not fit, the answer is the one `CLAUDE_MAX_BYTES`'s entry already settled — **defer the
> addition**, which is always available for an addition, or move a section down a tier. The shape rules are what bind that file: group by area, no per-spec line, and
> a per-bullet length cap. Every rule it holds existed in prose first and was violated anyway; that is why it
> is a gate.


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
  it is not, since it is the only home of the rejected alternatives and the fences. The digest and
  the register **group by the same areas**, so a reader who finds an area in one finds it in the other.
- **When a doc moves, the pointers that rot unseen are in SOURCE files** — `.py` docstrings, `.tf`
  comments, `.yml` steps. `validate_docs.py` walks those for exactly this reason; a markdown-only
  sweep reports the tree clean. Grep the path, not the filename, and fix the Draft specs too: a
  Draft is an unbuilt instruction, and pointing one at a deleted file sends the next builder nowhere.
- **A doc's own statement of when to read it must agree with CLAUDE.md's.** This file told readers it
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
  cannot fail. Why `CLAUDE_MAX_BYTES` is deliberately not at the measured level is in
  `validate_docs.py`'s docstring, where a person changing it reads it.
- **A rule practice consistently violates gets reconciled or deleted.** A dead rule trains agents to
  ignore the live ones.
- **Routers carry only what self-describes.** Hand-maintained metadata (symbol counts, "§1–§N" ranges)
  rots silently; drop it or let the structure carry the information.
- **Any doc pulled entry-by-entry gets one heading per entry plus a TOC**, and pointer phrases in
  other docs must match a greppable heading — "read the entry for your area" must be a jump, not a
  full-file read.
- **Live findings and obligations never live in historical or cancelled narrative** — rehome them to
  an active register (`security-baseline.md`, Current work) and leave a pointer behind.

---

## 6. Operational traps that only bite in CI / on deploy

These pass locally and fail later — check them as part of the work, not as an afterthought.

- **Six steps now fail NOWHERE but your machine** — lint, both suites and mypy are commented out in
  `ci.yml`, whose header names all six and carries the restore rule, so a green PR is no evidence
  any ran. `tsc -b` (via `npm run build`) is the only check CI still makes; `npm run test` never
  typechecks and `tsc -p tsconfig.json` checks nothing. The Python linter is `ruff check lambdas/
  scripts/ .github/scripts/` — **all three trees**; `pytest` never sees it. All, by exit code.
- **A fresh worktree borrows the parent's `node_modules`, so the JS gates pass wrongly. `npm ci`
  first** — a guard refuses them until you do.
- **Never hand-roll a CI watch.** `gh pr checks --watch` can exit clean against the **previous**
  commit's checks, and a hand-written shell condition inverted and printed "settled" while two
  deploys were still running — both reported a green that was not there. Use
  `python3 scripts/watch_ci.py --pr <n>` (or `--branch main` after a merge): every query is keyed to
  one resolved sha, so a stale-sha report is not expressible, and the "are we done" and "did it pass"
  decisions are unit-tested in `lambdas/test_watch_ci.py`. Exit 0 means settled **and** green, so it
  composes with `&&`; anything unfinished, unknown or absent exits non-zero.
- **Vitest needs the Vite config for jsdom.** Running vitest with an explicit file path *from the repo
  root* uses no Vite config → `document is not defined`. Run from `apps/portal` or via
  `npm run test -w apps/portal`.
- **`import.meta.env.VITE_*` read at module top level** is captured at import — `vi.stubEnv` in
  `beforeEach` is too late and CI has no `.env`. Stub at top level **and dynamic-import** the module.
- **A new configuration key is wired in FIVE places, and none of them is a build env.** Production
  reads a runtime `/config.json`; a `VITE_*` value is the **dev
  fallback only**, and `npm run check:bundle` asserts the production bundle carries no `VITE_` names
  at all. Wiring the build env and stopping there ships a key that exists nowhere the browser can
  see it. The list — including the render step and the container entrypoint's
  own `KEYS`/`REQUIRED`, which is what decides whether the container starts — is
  [`apps/portal/info/runtime-configuration.md`](../apps/portal/info/runtime-configuration.md).
  **The third site is no longer "a repository variable":** a value Terraform computes is read from
  state through `.github/config-outputs.json`, and only a genuine **input** — one Terraform is given
  rather than derives — is still a variable. Putting a derived value back in the settings page
  reinstates the failure the resolver exists to prevent, and it fails quietly, because an unset
  variable interpolates to the empty string, which satisfies a required Terraform variable and
  overrides its default.
- **`lambdas/` has a second local-only gate beside ruff: `mypy` is BLOCKING** at zero errors over
  the shared layers, the API and the contract generator. The list is `pyproject.toml`'s
  `[tool.mypy]` `files` block and nowhere else — a **new shared layer joins the ratchet with the
  spec that creates it**: added later it is a baseline to argue about, added now it is free.
- **Never `tofu apply` from a laptop.** The deploy role is GitHub-OIDC-only and the local CLI
  identity is an IAM *user* that is on no data bucket's policy allowlist, so tofu reads those
  buckets as **absent** and plans to destroy and recreate them (measured: `25 to add, 3 to change,
  13 to destroy`). The same isolation is why `get-object` on the user-space bucket returns
  `AccessDenied` from a laptop — that is the model working, not a fault.
- **Adding a new AWS resource type to `infra/`** trips a recurring set of deploy-role IAM traps
  (self-grant propagation, non-scopable actions, refresh deadlocks, unknown-ARN-in-list). Read
  [`infra/info/deploy-role-iam.md`](../infra/info/deploy-role-iam.md) **first**, and treat the IAM
  expansion as in-scope work for the spec.
- **Adding or rewiring a Lambda** has its own split — Terraform owns the function, CI owns the code
  and which image it runs — and its own deploy-time traps:
  [`lambdas/info/deployment.md`](../lambdas/info/deployment.md).

---

## 7. Project ground rules that shape the process

- **Greenfield, no production users yet** — low blast radius for auth/infra changes; don't
  over-engineer migration/rollback for users who don't exist.
- **There IS a backend now, and it is two shapes.** "No backend" was true through the first
  hundred-odd specs and is not any more: an **HTTP API** verifies bearer tokens and serves routes,
  and **seven control planes** run privileged async work. What survives of the old rule is the
  boundary — a feature does not get its own service. The browser's direct AWS surface is now
  presigned S3 bytes, Cognito, and the control-plane `sqs:SendMessage` enqueues; the object surface
  and the catalog went behind the API. The two live rules are **no second API** and **no new
  browser-side AWS SDK call on a path an API route already serves**.
- **Don't add dependencies** without first noting them in CLAUDE.md's Tech Stack.
