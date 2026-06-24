# The Spec-Driven Development Process

How work gets done in this repo. CLAUDE.md carries the terse, always-loaded rules; this doc is the
fuller **method** they point to — read it once to understand the rhythm, then let CLAUDE.md's Session
Workflow be your in-session checklist. It is read on demand, not every session.

Goal: each feature is **specified before it's built**, built in **reviewable phases**, landed as a
**single PR on green CI**, and recorded in **lean, layered docs** so the next session starts cheap.

---

## 1. Where truth lives (and why it's layered)

The docs are tiered by how often they're loaded. Keep each tier in its lane — the always-loaded tier
was deliberately shrunk (CLAUDE.md 265→~90 lines, architecture.md 696→~130) and **must not regrow**.

| Tier | File(s) | Loaded | Authoritative for |
|---|---|---|---|
| Always | `CLAUDE.md` | every session | conventions, key decisions, session workflow |
| Status | `docs/specs/INDEX.md` + each spec header | on demand | spec **status** (one row per spec) |
| The work | `docs/specs/SPEC-XXX-*.md` | the one you're building | requirements + phases |
| Why | `docs/architecture.md` | the *section* you need | design rationale + Known Constraints |
| Reuse | `docs/component-inventory.md` | skim for reuse | services/hooks/components already built |
| History | `docs/spec-delivery/SPEC-XXX-*.md` | when a dependency points to one | what a past spec shipped |
| Method | `docs/process.md` (this file) | once | how we work |

**Context discipline (the user cares about session-start token cost):**
- Read **only the current spec** in full.
- **Never** read `architecture.md` or delivery docs whole — pull the one section you need.
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
shared-connections, notifications) with an explicit **build order** documented in `INDEX.md` →
*Arcs*. Build in that order; arcs can have non-obvious dependencies (e.g. 056 before 051).

---

## 3. The session rhythm

This is the operating loop, start to finish. CLAUDE.md's *Session Workflow* is the condensed version.

**Start of session**
1. Read CLAUDE.md, then the **current** spec in full. Don't infer scope from a prior conversation —
   read the spec file as it exists now.
2. Skim `component-inventory.md` for reuse; pull only the `architecture.md` section / dependency
   delivery-doc you actually need.
3. Confirm CI is green: `gh run list --branch main --limit 5`. Investigate failures before building.
4. **Branch from fresh `main`:** `git fetch && git switch -c <branch> origin/main`.
5. **Confirm the phase before writing code.**

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- Work the spec's **Implementation Phases** in order. After each phase, **stop and summarize** what was
  built and state the **checkpoint test** for the user to verify before you continue.
- If a later phase surfaces an unresolved Open Question, **stop and ask** rather than assume.

**Landing the spec — one in flight at a time**
- A spec's PR is **merged only after green CI**.
- **Re-verify `main` is green** before starting the next spec (user directive: land before starting
  the next).
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
- **Implementation Phases** — each phase is one session's worth of work and **ends in a Checkpoint**: a
  specific, human-verifiable test (name the test file, the command, or the thing to click).
- **Open Questions** — decisions to resolve before/during build; unresolved ones in later phases are a
  signal to stop and ask.

---

## 5. Completion ritual (keep the always-loaded tier lean)

When a spec is done, in the same pass:
1. Set the spec file header `Status: Completed`.
2. Update its one-line row in `docs/specs/INDEX.md` (**status only** — no prose).
3. Write a **short** delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from
   `docs/templates/spec-completion-template.md` — *what shipped + what changed*, under ~40 lines, **no
   code/JSON pasted** (the code + component-inventory are the source of truth for reuse).
4. If reusable services/hooks/components were added, add a **one-line** row to
   `docs/component-inventory.md`.
5. A *new architectural decision* gets **one line** in CLAUDE.md's Key Decisions (+ a pointer) — never a
   paragraph. Reasoning lives in the spec/delivery doc.

**Anti-regrowth.** If a memory or doc disagrees with the code, fix or delete it — don't let stale state
accumulate. Don't add prose to the always-loaded tier.

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
