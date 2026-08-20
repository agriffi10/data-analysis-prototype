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
| Validation | `docs/testing/e2e.md` + `owed.md` | when running live checks | how to validate the deployed app, and what is still owed |
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

- **Draft** — written, **reviewed by a fresh-context reviewer (§3, *The reviewer contract*)** and
  refined, but **do not build until told.** The user authors spec files incrementally, sometimes well
  ahead of implementation. A Draft spec being in the repo is not a signal to start it. A spec that has
  not been through the gate is not Draft-ready, whatever its header says.
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
   covered, reuse from the component inventory is used, no out-of-scope work crept in). The plan —
   not per-phase checkpoints baked into the spec — is what gates the work.
6. **Put the plan through the reviewer gate before the first line of code** (*The reviewer contract*,
   below). A plan is reviewed for the same reason a PR is: the author cannot see what they assumed.
   Confirm the reviewed plan with the user, then build.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- Before opening a PR, run the project's **formatter, linter, unit tests and `npm run build`** locally
  and get them green. These quality gates are a pre-PR step — don't push red and leave CI to discover
  it. **`build` (`tsc -b`) is the only one that typechecks** — the test run does not, and
  `tsc -p tsconfig.json` silently checks nothing (see §6).
- Work the **reviewed** plan's phases in order. After each phase, **stop and summarize** what was
  built and how it maps back to the plan before continuing. Re-review the plan only if the phase
  changed it — a phase that revises the plan has produced a new artifact, and it goes through the
  gate as one.
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

**The reviewer contract — three artifacts, one gate**

Nothing reaches the next stage on its author's own judgement. A **spec**, an **implementation plan**
and a **diff** each go to a reviewer in a **fresh context** — a subagent or a new session, never the
context that produced the artifact. An author reviewing their own work assumes its output was
intended and rubber-stamps it; that is as true of a plan as of code, and a wrong plan is the more
expensive of the two because the code that follows will faithfully implement it.

- **The gate is blocking.** A spec is not Draft-ready, and a plan does not start code, until it has
  been through a review round and every finding is either **fixed** or **explicitly rejected in
  writing** — in the spec/plan itself, or in the session summary, saying which finding and why. A
  finding that is silently dropped is a finding that was not reviewed.
- **The reviewer gets the artifact and its sources, never the author's reasoning.** For a spec: the
  spec file, its arc entry in `ARCS.md`, the `decisions.md` entries it claims to follow, and the
  specs it depends on. For a plan: the plan, the spec, and the `component-inventory/<area>.md` files
  the spec touches. Handing over the authoring rationale tells the reviewer what to conclude.
- **What each review is for.** A **spec** review asks: is every FR testable and binary; does any
  acceptance criterion pass vacuously; is anything in Out of Scope actually required by an FR; does
  it contradict a settled `decisions.md` entry or silently supersede one without saying so; are there
  Open Questions wearing declarative clothes. A **plan** review asks: does every FR and acceptance
  criterion have a phase that delivers it; is existing reuse used rather than re-built; has
  out-of-scope work crept in; is a phase resting on a premise nobody has checked. A **diff** review is
  the rules below.
- **Cap same-frame rounds at two, then rotate the frame** — the rule the next block earns, and it
  applies to specs and plans as much as to code. A second round of the same reviewer on the same
  artifact converges on wording. Rotate instead: for a spec, a reviewer briefed only on the
  *dependencies* it claims, or one asked to build the thing from the spec alone and report what it
  could not determine; for a plan, one asked to find the phase that will be discovered impossible.
- **Exit on a new frame finding nothing**, never on a round count.
- **A reviewer finding is not an instruction.** The author decides; the record of the decision is
  what the gate requires. A rejected finding that turns out right is a cheap lesson with a written
  trail; a fixed finding that was wrong is a silent regression.

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

**Briefing the reviewer — four lines that change what comes back**

Measured over four rounds on one spec (SPEC-205, 2026-08-18: two adversarial-audit rounds, then two
implementer rounds). The frame decides the *class* of finding; the briefing decides whether the
answer is honest.

- **Say that "this is sound" is a valid verdict.** A reviewer that infers it is expected to produce
  findings will produce them. The round that returned the most useful report was the one told
  explicitly that a short "implementable as written, here is what I built" was a valuable outcome —
  and it still returned real defects, so the line costs nothing.
- **Require it to cite where it looked** before declaring something missing — the spec line it read
  before concluding the spec is silent. That separates a genuine gap from a miss, and it is the
  cheapest way to keep a long report's false-positive rate down.
- **Tell round N+1 what round N fixed, and forbid re-auditing it.** Otherwise the second pass
  re-derives the first pass's findings and never reaches the new work.
- **Withhold the history from a frame that is testing self-sufficiency.** The opposite of the line
  above, and both are right: a pass asking *"is this spec buildable by someone who wasn't here"* must
  be given it cold.

**A rewrite under review pressure is the highest-risk artifact in the loop**

Adjacent to *scope added mid-review restarts the clock*, and stronger. When a finding causes a
substantial **replacement** rather than a widening, the replacement is written quickly, confidently,
and with nobody having reviewed it. On SPEC-205 the second round found **four blockers, all of them
inside machinery the first round's fixes introduced** — two of which independently broke a path the
spec had a requirement to preserve. Budget a round for the fix, aimed at the fix.

And **when the same area is wrong twice, the signal is about the area, not the draft.** Both SPEC-205
drafts were wrong about the same thing — what protects a space from teardown. A repeat in one place
is where to spend the next frame, ahead of anything the reviewer ranked higher.

**The implementer frame must actually build, and every frame must run the gates**

*The build-it-from-the-spec rotation named above, made concrete — it earns its own block because it
yields a different class of finding than any reading-based frame.*

- **Have it write real code, off-repo, and run the suites.** What it found by running that no reader
  found: nine existing tests that invert (a list the spec claimed was four, including one in a
  *different* suite from the one the spec's list implied), fixtures across two validator suites that
  silently become the new failure case, a hard-coded verb count in an unrelated plane's coverage
  test, and a fake whose signature diverges from the real client.
- **Its output class is contradictions, unspecified shapes and sequencing** — two requirements that
  cannot both hold; a return type nobody named; a phase boundary that leaves `main` exposed. An
  adversarial reader finds defects and does not find these; the implementer finds these and is worse
  at defects. Run both, not one twice.
- **Every reviewer runs the repo's gates against the branch.** Four rounds reviewed SPEC-205 and
  none ran `scripts/validate_docs.py`; the branch was red on it throughout, for a reason unrelated to
  the spec, and it took an agent that *built* the change to notice. A review of a change touching
  gated files runs the gates.

**Exit on the trajectory of the findings, not on an empty round**

*Refines "exit on a new frame finding nothing".* In practice a fresh frame rarely finds literally
nothing — it finds something smaller. The honest signal is the **class** changing round over round:
on SPEC-205, blockers → machinery introduced by the fixes → sequencing and contradictions →
coin-flips no test would catch. Stop when a new frame's worst finding is one that would not change
the built result, and say which finding that was.

**An Open Question can wear a declarative sentence**

`CLAUDE.md` forbids a spec carrying Open Questions, and the check is easy to pass while failing.
SPEC-205 shipped the sentence *"either the exception moves to a shared location or `save_members`
returns a refusal the caller raises. The spec states which"* — and then did not. A sentence that
**promises a decision** is an Open Question with a declarative shape; so is an acceptance criterion
demanding a **computed** bound while supplying none of its inputs. Both were caught by an implementer
who had to pick, and neither by a reader.

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
- **Then the reviewer gate** (§3, *The reviewer contract*). A freshly-authored spec goes to a
  fresh-context reviewer before it is Draft-ready, and its findings are fixed or rejected in writing.
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

**Anti-regrowth & doc hygiene** (each rule below was earned by a defect the 2026-08-03 doc sweep found).

> **`scripts/validate_docs.py` enforces the structural half of these rules and runs on every PR**
> (`ci.yml` → *Validate the documentation layout*). It holds: `docs/testing/` to the guide, the
> ledger, the log and at most **one** in-flight arc script; `docs/testing/fixtures/` to
> plane-named scripts within a ratchet, refusing a spec-numbered one outright; `CLAUDE.md` to a
> byte budget and each
> Key Decisions line to a length; every `decisions.md` entry to one heading level and a resolving
> Contents entry; every `ARCS.md` arc to a status-free heading that is in the arc list; every spec
> header to agreeing with its `INDEX.md` row and every Completed spec to having a delivery doc;
> every delivery doc to a line cap; and every relative markdown link to resolving. **The budgets
> are ratchets at the measured level** (SPEC-150's convention for the coverage floors) — raising
> one so a growing doc passes is the failure mode the gate exists to catch. Move the detail down a
> tier instead. Every rule it holds existed in prose first and was violated anyway; that is why it
> is a gate.


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

- **Two gates have no local counterpart in Common Commands, so they only fail in CI unless you run
  them by hand.** `tsc -b` (via `npm run build`) is the only typecheck — `npm run test` never
  typechecks and `tsc -p tsconfig.json` silently checks nothing. `ruff check lambdas/` is the Python
  linter — `pytest` never sees it. Run both before pushing.
- **Vitest needs the Vite config for jsdom.** Running vitest with an explicit file path *from the repo
  root* uses no Vite config → `document is not defined`. Run from `apps/portal` or via
  `npm run test -w apps/portal`.
- **`import.meta.env.VITE_*` read at module top level** is captured at import — `vi.stubEnv` in
  `beforeEach` is too late and CI has no `.env`. Stub at top level **and dynamic-import** the module.
- **New `VITE_*` vars need deploy wiring.** Any var the app reads must be added to `deploy-app.yml`'s
  build env **and** set as a GitHub Actions repo variable, or production ships it `undefined` (IAM
  being correct won't save you).
- **`lambdas/` has a second CI-only gate beside ruff: `mypy` is BLOCKING** over the five shared
  layers at zero errors. The ratchet path — which package widens next, and at what strictness — is
  recorded in `pyproject.toml`'s `[tool.mypy]` block and nowhere else.
- **A `rate()` EventBridge rule fires on creation**, so a new singleton Lambda's first scheduled
  invocation can hit the placeholder zip before `Deploy Lambdas` lands. The async retry fixes it —
  **a red first invocation is expected, not a defect.**
- **Never `tofu apply` from a laptop.** The deploy role is GitHub-OIDC-only and the local CLI
  identity is an IAM *user* that is on no data bucket's policy allowlist, so tofu reads those
  buckets as **absent** and plans to destroy and recreate them (measured: `25 to add, 3 to change,
  13 to destroy`). The same isolation is why `get-object` on the user-space bucket returns
  `AccessDenied` from a laptop — that is the model working, not a fault.
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
