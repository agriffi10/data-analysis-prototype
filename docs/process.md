# The Spec-Driven Development Process

How work gets done in this repo. CLAUDE.md carries the terse, always-loaded rules; this doc is the
fuller **method** they point to — read it once to understand the rhythm, then let CLAUDE.md's Session
Workflow be your in-session checklist. It is read on demand, not every session.

Goal: each feature is **specified before it's built**, built in **reviewable phases**, landed as a
**single PR on green CI**, and recorded in **lean, layered docs** so the next session starts cheap.

---

## 1. Where truth lives (and why it's layered)

The docs are tiered by how often they're loaded. Keep each tier in its lane — the always-loaded tier
(`CLAUDE.md`, and `architecture.md` behind it) was deliberately cut down from much larger versions,
must be kept lean, and **must not regrow**.
It regrew once and was cut again: the fix each time is a pointer to a deeper tier, never a longer
paragraph in the always-loaded file.

| Tier | File(s) | Loaded | Authoritative for |
|---|---|---|---|
| Always | `CLAUDE.md` | every session | conventions, key decisions, session workflow |
| Status | `docs/specs/INDEX.md` + each spec header | on demand | spec **status** (one row per spec) |
| The work | `docs/specs/SPEC-XXX-*.md` | the one you're building | requirements + phases |
| Why | `docs/architecture.md` | the *section* you need | design rationale + Known Constraints |
| Decisions | `docs/decisions.md` | the *entry* for your area | settled decisions in full + "do NOT build" fences |
| Arcs | `docs/specs/ARCS.md` | the arc you're in | why an arc exists, how its specs compose |
| Reuse | `docs/component-inventory.md` → `component-inventory/<area>.md` | the area(s) you need | services/hooks/components already built |
| Rulebooks | `docs/best-practices/INDEX.md` → domain doc | the section(s) you need | domain coding rules (React, a11y, …) |
| History | `docs/spec-delivery/SPEC-XXX-*.md` | when a dependency points to one | what a past spec shipped |
| Method | `docs/process.md` (this file) | once | how we work |

**Context discipline (the user cares about session-start token cost):**
- Read **only the current spec** in full.
- **Never** read `architecture.md`, `decisions.md`, `ARCS.md`, or delivery docs whole — pull the one
  section/entry you need.
- The component inventory is a **router**: read `component-inventory/<area>.md` for the areas the spec
  touches, never all of them.
- Delegate *dependency* delivery-doc reading to an Explore/subagent brief rather than loading it into
  the main loop.

---

## 2. The spec lifecycle

Specs move **Draft → In Progress → Completed** (the status in each spec's header is authoritative; the
`INDEX.md` row mirrors it).

- **Draft** — written and refined, but **do not build until told.** The user authors spec files
  incrementally, sometimes well ahead of implementation. A Draft spec being in the repo is not a
  signal to start it.
- **In Progress** — exactly one spec at a time is in flight. Set when you branch to build it.
- **Completed** — merged on green CI, delivery doc written (see §5).

**Arcs.** Related specs are grouped into *arcs* (file-operations, analytics, query-editor UX,
shared-connections, notifications) with an explicit **build order** documented in
`docs/specs/ARCS.md`. Build in that order; arcs can have non-obvious dependencies (e.g. 056 before 051).

---

## 3. The session rhythm

This is the operating loop, start to finish. CLAUDE.md's *Session Workflow* is the condensed version.
**If this section and CLAUDE.md ever disagree, CLAUDE.md wins** — fix the drift here in the same
session you notice it (two hand-synced copies of one procedure is how numbering bugs happen).

**Start of session**
1. Read CLAUDE.md, then the **current** spec in full. Don't infer scope from a prior conversation —
   read the spec file as it exists now.
2. For reuse, read the `component-inventory/<area>.md` file(s) the spec touches; pull only the
   `architecture.md` section / `decisions.md` entry / dependency delivery-doc you actually need.
3. Confirm CI is green: `gh run list --branch main --limit 5`. Investigate failures before building.
4. **Branch from fresh `main`:** `git fetch && git switch -c <branch> origin/main`.
5. **Generate and validate a plan before writing code.** Turn the spec's Implementation Phases into a
   concrete implementation plan, then validate it against the spec (every FR + acceptance criterion is
   covered, reuse from the component inventory is used, no out-of-scope work crept in). Confirm the
   plan before building. The plan — not per-phase checkpoints baked into the spec — is what gates the
   work.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- Before opening a PR, run the project's **formatter, linter, and unit tests** locally and get them
  green. These quality gates are a pre-PR step — don't push red and leave CI to discover it.
- Work the validated plan's phases in order. After each phase, **stop and summarize** what was built
  and how it maps back to the plan before continuing.
- Before writing code in a domain that has a rulebook (React, accessibility, …), route through
  `docs/best-practices/INDEX.md` and load only the relevant section(s). Apply the rules as you write;
  flag (don't silently break) any that conflict with existing code.
- Specs ship with **no Open Questions** — they're resolved during authoring (§4). An issue that emerges
  mid-build is triaged by *kind*, not parked:
  - **Reversible / technical** (naming, file layout, which helper to reuse, an obvious bug fix): just
    decide in-session and keep moving. If it changes scope or contradicts the spec, **update the spec**
    rather than leaving the divergence implicit.
  - **Product-changing / ambiguous** (anything that alters behavior the user would notice, or a call
    with no clearly-right answer): **stop and escalate to the human.** Don't silently pick — surface the
    options with a recommendation. Auto-deciding these is how an autonomous run drifts away from what
    was actually wanted.

**Reviewing the work — in a fresh context**
- Code review and verification run in a **fresh context** (a new session or a subagent), **never the
  session that wrote the code.** A self-reviewing agent assumes its own output was intended and rubber-
  stamps it; a clean reviewer catches what the author can't see. The reviewer checks the diff against
  the spec's acceptance criteria **and the relevant `best-practices/` rules** (route via its INDEX),
  not just "does it look fine."

**Rotating the frame — why round count is the wrong exit criterion**

Review rounds converge on the frame they are given, not on correctness. Measured on a sibling repo
(`log-forge`, 2026-08-07): **eight** rounds of independent review — two on the spec, three on its
revisions, three on the code — after which the merged result still carried two defects, one of which
was a regression of a guarantee an earlier spec had shipped. Rounds 1–3 found design defects; rounds
4–8 increasingly found wording. The *first* differently-framed pass afterwards found ~25 defects,
several of them years old.

So the loop rotates the frame instead of adding rounds:

- **Cap same-frame review at two rounds.** After the second, switch frame rather than iterate:
  adversarial *execution*, whole-feature fresh eyes (not the diff), a11y, security, or concurrency.
- **Exit on a new frame finding nothing**, not on the current frame converging. "The reviewer found
  nothing" means "nothing within the frame I gave it."
- **At least one pass must start from the feature, not the diff.** Every diff-scoped review is
  structurally blind to a defect that predates the diff — and to the states the diff is never
  exercised in: SPEC-140's CSP was reviewed and verified *signed in*, and the `connect-src` host it
  omitted broke **fresh sign-in** for a day.
- **Reasoning finds wording; execution finds defects.** Require a reproduction, not an argument —
  a run in the browser or against real AWS. SPEC-137's instrumented code passed review, unit tests
  and `update-function-code`, then raised `ModuleNotFoundError` at every cold start and broke sign-up
  for nine days; every gate was blind because none of them ran the deployed artifact.
- **A spec touching lifecycle, IAM or concurrency gets an execution harness, not a review.** An
  import-time `_require` in a shared layer fails at **cold start** only (PR #196), and the
  concurrent-refresh race is a property of two overlapping executions — neither is findable by
  reading.

**When a review changes a rule, re-audit the rule — not the line**

A review finding is usually reported as an instance ("this call site uses the wrong predicate").
Fixing the cited line and moving on is how the same defect survives repeated review: on `log-forge`'s
SPEC-033, three separate reviewers reported the same rule against three *different* call sites, each
was fixed, and a fourth site shipped broken.

- When a finding is an instance of a **rule**, the fix is a test or lint rule that enumerates
  **every** site of that rule and asserts each one — the discipline SPEC-152's fleet test (every
  state machine carries `NotifyFailure`), SPEC-155's `components/`-may-not-import-`features/` ESLint
  rule and `lambdas/test_deploy_matrix.py` already use, and for the same reason: a hand-maintained
  list rots and a derived one does not.
- **Scope added mid-review restarts the clock.** Widening a spec in response to a finding is often
  right, but the widening arrives late, gets the least scrutiny, and inherits confidence it has not
  earned.

**Landing the spec — watch PRs and watch `main`**
- **Every PR is watched to completion and merged as soon as CI is green** — don't open a PR and walk
  away. A spec's PR merges only on green.
- **`main` is always watched.** After any merge, confirm `main`'s build went green. If `main` fails,
  **diagnose immediately and fix it with a new PR** — a red `main` is the top priority and blocks
  starting the next spec.
- **Re-verify `main` is green** before starting the next spec (land before starting the next).
- Then run the completion ritual (§5).

---

## 4. Authoring a spec

Specs are written from `docs/templates/spec-template.md`. What makes a spec *buildable*:

- **Overview** — user/business intent, no implementation detail. Understandable cold.
- **Scope: In / Out** — explicitly list what's *excluded*, especially anything a reader would
  reasonably assume is included.
- **Functional Requirements** — one FR per discrete, testable behavior, with binary pass/fail
  **Acceptance Criteria** covering happy path, error path, and edges. Sequential IDs so a prompt can
  say "implement FR-001 through FR-003 only."
- **Data Model / Interface Contract** — TypeScript shapes, not prose. Explicit types produce
  better-typed output. Note the target path (`src/types/…`).
- **Implementation Phases** — each phase is one session's worth of work and maps to a discrete,
  reviewable unit. Phases are the input to the implementation plan generated at build time (§3); don't
  bake per-phase checkpoints into the spec.
- **No Open Questions.** Resolve every decision while authoring — a spec doesn't move to Draft-ready
  with unanswered questions. Issues that only surface during the build are handled in-session (§3),
  not parked in the spec.

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
   `docs/component-inventory/<area>.md` **matching the component's path** — a `features/query/` row
   belongs in the query area file, nowhere else (the router only changes if a whole new area appeared).
5. A *new architectural decision* gets its full entry in `docs/decisions.md` **first**, then **one
   line** in CLAUDE.md's Key Decisions — the digest line is **never the only home of a fact**, and
   never a paragraph. If the decision **supersedes an earlier one**, update the old register entry in
   place and add a superseded marker (short blockquote: what changed, which spec, where the full entry
   lives) at every doc site that still states the old claim — arc narratives in `ARCS.md`,
   architecture.md sections. The new entry alone is not enough; an agent reading only the old site
   must see the reversal. Reasoning lives in the spec/delivery doc.
6. **Prune CLAUDE.md's `## Specs` → Current work** of whatever the closed spec made stale. It carries
   only what is live and undocumented elsewhere — never append a changelog.
7. **User-facing docs sweep.** If the spec added, changed, or removed a capability a user can see, update the
   surfaces that describe it — first and foremost the in-app **Help & guides** content
   (`apps/portal/src/features/help/helpContent.ts`, SPEC-074), plus any README / onboarding copy. New shipped
   feature → add/adjust its guide; changed flow/labels → fix the steps; removed feature → delete its guide.
   The help module is code-grounded by contract (SPEC-074 FR-005), so **only document what's shipped and wired
   end-to-end** — a Draft or infra-less feature stays out until it ships. If nothing user-facing changed, say so
   and move on. (This step exists because help content silently drifts as features land; SPEC-073's join status
   and the table-builder arc, for instance, shipped after SPEC-074 was authored and had to be folded in.)

**Anti-regrowth & doc hygiene** (each rule below was earned by a defect the 2026-08-03 doc sweep found):

- If a memory or doc disagrees with the code, fix or delete it — don't let stale state accumulate.
  Don't add prose to the always-loaded tier.
- **Standing rules never cite volatile numbers** (line counts, row counts, section ranges) — state the
  principle. The numbers rot, and a rule resting on false evidence teaches readers to distrust it.
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

- **Vitest needs the Vite config for jsdom.** Running vitest with an explicit file path *from the repo
  root* uses no Vite config → `document is not defined`. Run from `apps/portal` or via
  `npm run test -w apps/portal`.
- **`import.meta.env.VITE_*` read at module top level** is captured at import — `vi.stubEnv` in
  `beforeEach` is too late and CI has no `.env`. Stub at top level **and dynamic-import** the module.
- **New `VITE_*` vars need deploy wiring.** Any var the app reads must be added to `deploy-app.yml`'s
  build env **and** set as a GitHub Actions repo variable, or production ships it `undefined` (IAM
  being correct won't save you).
- **Adding a new AWS resource type to `infra/`** trips a recurring set of deploy-role IAM traps
  (self-grant propagation, non-scopable actions, refresh deadlocks, unknown-ARN-in-list). Read
  `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split*
  **first**. Treat the IAM expansion as in-scope work for the spec.

---

## 7. Project ground rules that shape the process

- **Greenfield, no production users yet** — low blast radius for auth/infra changes; don't
  over-engineer migration/rollback for users who don't exist.
- **No backend** (browser → AWS direct) except where a decision record explicitly reverses it
  (shared-space mutations, notifications — both async pipelines, see CLAUDE.md Key Decisions).
- **Don't add dependencies** without first noting them in CLAUDE.md's Tech Stack.
