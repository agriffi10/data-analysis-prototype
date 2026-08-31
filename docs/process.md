# The Spec-Driven Development Process

How work gets done in this repo. CLAUDE.md carries the terse, always-loaded rules; this doc is the
fuller **method** they point to, and it is the contract CLAUDE.md only summarises. **Read it at the
start of every session, before any other doc** — CLAUDE.md's Session Workflow says the same, and this
file used to say the opposite.

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
| | `apps/portal/info/runtime-configuration.md` | the `/config.json` contract and the six places a key is wired |
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

**These two reviews are the gates, and they are the only ones that need answering.** Once the plan
and the grouping have each been reviewed, the build runs to completion without checking in. The user
confirmed the work when they set the spec going; a per-phase check-in re-asks a question already
answered, and on a twelve-phase spec it asks it twelve times.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- **The diff review runs BEFORE the push, not before the merge.** Commit locally, run the gates, send
  the diff to a fresh-context reviewer, fix or explicitly reject every finding — *then* push and open
  the PR. Pushing first and reviewing after inverts the gate: the branch is already public, the fixes
  arrive as follow-up commits, and the review reads as commentary on something that has already
  happened rather than as the thing that decides whether it should. Rotating the frame (below) happens
  in the same window. A push is the point of no return for the review, the same way the merge is the
  point of no return for CI.
- Before pushing, run the project's **formatter, linter, unit tests and `npm run build`** locally
  and get them green. These quality gates are a pre-push step — don't push red and leave CI to discover
  it. **`build` (`tsc -b`) is the only one that typechecks** — the test run does not, and
  `tsc -p tsconfig.json` silently checks nothing (see §6).
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
expensive of the two, because the code that follows will faithfully implement it.

- **The gate is blocking, and what it asks for is an answer, not a filing.** A spec is not
  Draft-ready, a plan does not start code, and a branch does not reach the remote, until every
  finding has been either **fixed** or **flagged** — said out loud, so the call is visible and can be
  argued with. A finding silently dropped is a finding that was not reviewed; a finding rejected in
  one sentence is a finding that was. **Write a rejection down only when it carries a lesson worth
  keeping** — then it belongs in the register or the spec, as reasoning, not as a paper trail.
- **The reviewer gets the artifact and its sources, never the author's reasoning.** For a spec: the
  spec file, its arc entry in `ARCS.md`, the `decisions/` entries it claims to follow, and the specs
  it depends on. For a plan: the plan, the spec, and the
  `apps/portal/info/component-inventory/<area>.md` files the spec touches. For a diff: the diff, the
  spec's acceptance criteria, and the `best-practices/` rules for the domains it touches (route via
  their INDEX). Handing over the authoring rationale tells the reviewer what to conclude.
- **What each review is for.** A **spec** review asks: is every FR testable and binary; does any
  acceptance criterion pass vacuously; is anything in Out of Scope actually required by an FR; does
  it contradict a settled `decisions/` entry or silently supersede one without saying so; are there
  Open Questions wearing declarative clothes. A **plan** review asks: does every FR and acceptance
  criterion have a phase that delivers it; is existing reuse used rather than re-built; has
  out-of-scope work crept in; is a phase resting on a premise nobody has checked. A **diff** review
  checks the change against the acceptance criteria and the rulebooks — not "does it look fine."
- **A reviewer finding is not an instruction.** The author decides. Rejecting one is ordinary and
  costs a sentence; the thing to avoid is deciding silently, because then nobody can tell a
  considered rejection from a finding that was never read. A fixed finding that was wrong is a
  silent regression, which is the same failure in the other direction.

**Rotating the frame, and knowing when to stop**

Review rounds converge on the frame they are given, not on correctness. Measured on a sibling repo
(`log-forge`, 2026-08-07): **eight** rounds of independent review — two on the spec, three on its
revisions, three on the code — after which the merged result still carried two defects, one of which
was a regression of a guarantee an earlier spec had shipped. Rounds 1–3 found design defects; rounds
4–8 increasingly found wording. The *first* differently-framed pass afterwards found ~25 defects,
several of them years old.

- **Cap same-frame review at two rounds, then switch frame rather than iterate.** For a spec: a
  reviewer briefed only on the *dependencies* it claims, or one asked to build the thing from the
  spec alone and report what it could not determine. For a plan: one asked to find the phase that
  will be discovered impossible. For code: adversarial *execution*, whole-feature fresh eyes, a11y,
  security, or concurrency.
- **At least one pass must start from the feature, not the diff.** Every diff-scoped review is
  structurally blind to a defect that predates the diff — and to the states the diff is never
  exercised in: SPEC-140's CSP was reviewed and verified *signed in*, and the `connect-src` host it
  omitted broke **fresh sign-in** for a day.
- **A review SAMPLES; when the risk is ABSENCE, enumerate instead.** Review is the right instrument
  for "is this new code correct" and a weak one for "what did we stop checking" — a reviewer reads
  what is there, and a deletion leaves nothing to read. Measured on the 2026-08-28 suite reduction:
  three fresh frames returned **4, then 7, then 17** findings, diverging rather than converging,
  because each sampled a population of hundreds. The mechanical sweep that answered it completely —
  reason codes raised vs reason codes asserted — ran in seconds. **Before reviewing a change whose
  risk is what it removed, write the sweep that lists the whole population.**
- **Spot-check a negative claim before acting on it, and again before writing it down.** "Only
  documented on page X", "no test covers this", "nothing imports this file", "there is no scrubber"
  — each is a claim about an absence, and an absence is what a search proves badly. Verify it
  yourself whether a reviewer said it or you did. The asymmetry that makes this worth a rule: a
  wrong claim entering **code** has tests to catch it later, while one entering a spec, a register
  entry, a docstring or a commit message has nothing, and the next session reads it as settled. Two
  in this repo shipped as source comments and were believed for weeks — a "registry guard" the
  router advertised and did not have, and a credential "scrub" a config module named as the thing
  keeping tokens out of logs. Both were found by writing the test that assumed them.
- **A mechanical sweep REPORTS before it applies.** Print what it would change, read the list, then
  re-run with `--apply`, and check the result by diffing **test names** rather than a pass count. A
  classifier that looks right is routinely wrong at its edges: a sweep for unused module-level
  helpers classified pytest's `Test*` classes as dead and would have deleted every test inside
  them — caught only because it printed first. A regex over source is the same hazard one level
  down; parse instead where a parser exists.
- **A finding should carry a reproducing mutation, and the fix is verified by re-planting it.**
  Then fix-verification is mechanical and needs no second reviewer — which is what stops a review
  round spawning a review of its fixes. A frame only finds what its mutations probe, so a fix that
  satisfies a weak mutation can still be wrong: the same reduction had a `watch_ci` guard restored
  against one frame's probe and broken under the next frame's.
- **Reasoning finds wording; execution finds defects.** Require a reproduction, not an argument — a
  run in the browser or against real AWS. SPEC-137's instrumented code passed review, unit tests and
  `update-function-code`, then raised `ModuleNotFoundError` at every cold start and broke sign-up for
  nine days; every gate was blind because none of them ran the deployed artifact.
- **A spec touching lifecycle, IAM or concurrency gets an execution harness, not a review.** An
  import-time `_require` in a shared layer fails at **cold start** only, and a concurrent-refresh
  race is a property of two overlapping executions — neither is findable by reading.
- **Exit on the trajectory of the findings, not on a round count and not on an empty round.** A fresh
  frame rarely finds literally nothing; it finds something smaller. The honest signal is the **class**
  changing round over round: on SPEC-205, blockers → machinery introduced by the fixes → sequencing
  and contradictions → coin-flips no test would catch. Stop when a new frame's worst finding is one
  that would not change the built result, **and say which finding that was.** "The reviewer found
  nothing" only ever means "nothing within the frame I gave it."

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
5. A *new architectural decision* gets its full entry in the matching
   `docs/decisions/<area>.md` **first** — one `##` heading, listed in that file's Contents — then
   **one line** in CLAUDE.md's Key Decisions. The digest line is **never the only home of a fact**,
   and never a paragraph. If the decision **supersedes an earlier one**, update the old register
   entry in place and add a superseded marker (short blockquote: what changed, which spec, where the
   full entry lives) at every doc site that still states the old claim — arc narratives in
   `ARCS.md`, `architecture.md` sections. The new entry alone is not enough; an agent reading only
   the old site must see the reversal. Reasoning lives in the spec/delivery doc.
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
> plane-named scripts within a ratchet, refusing a spec-numbered one outright; `CLAUDE.md` to a
> byte budget and each
> Key Decisions line to a length; the `docs/decisions/` register to one file per digest area, each
> routed by its `INDEX.md`, with one heading level per entry and a Contents that reaches every one
> of them; every `ARCS.md` arc to a status-free heading that is in the arc list; every spec
> header to agreeing with its `INDEX.md` row and every Completed spec to having a delivery doc;
> every delivery doc to a line cap; and every relative markdown link to resolving. **The budgets
> are ratchets at the measured level** (SPEC-150's convention for the coverage floors) — raising
> one so a growing doc passes is the failure mode the gate exists to catch. Move the detail down a
> tier instead. **One exception, taken deliberately (user decision, 2026-08-27):**
> `CLAUDE_MAX_BYTES` is 50,000 rather than the measured level, because the completion ritual
> requires every closing spec to fold a clause into Key Decisions — so a ratchet there makes each
> completion a forced prune of some other area's fences, which is the gate causing the damage it
> exists to prevent. The shape rules are what bind that file: group by area, no per-spec line, and
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
  typechecks and `tsc -p tsconfig.json` silently checks nothing. The Python linter is
  `ruff check lambdas/ scripts/ .github/scripts/` — **all three trees**, since `scripts/` holds the
  doc gate every reviewer is told to run — and `pytest` never sees it. Run both before pushing.
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
- **A new configuration key is wired in SIX places, and `deploy-app.yml`'s build env is not the one
  that reaches production.** Production reads a runtime `/config.json`; a `VITE_*` value is the **dev
  fallback only**, and `npm run check:bundle` asserts the production bundle carries no `VITE_` names
  at all. Wiring the build env and the repo variable and stopping there ships a key that exists
  nowhere the browser can see it. The list — including the render step and the container entrypoint's
  own `KEYS`/`REQUIRED`, which is what decides whether the container starts — is
  [`apps/portal/info/runtime-configuration.md`](../apps/portal/info/runtime-configuration.md).
- **`lambdas/` has a second CI-only gate beside ruff: `mypy` is BLOCKING** at zero errors over every
  shared layer, plus the API and the contract generator. The list is `pyproject.toml`'s `[tool.mypy]`
  `files` block and nowhere else — a **new shared layer joins the ratchet with the spec that creates
  it**, because added later it is a baseline of existing errors to argue about and added now it is
  free.
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
  and every layer attachment — and its own deploy-time traps:
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
