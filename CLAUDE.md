# S3 File Portal — Project Memory

Loaded every session — keep it lean. Deep docs live in `docs/` and are pulled **on demand**:
- `@docs/process.md` — how we work: spec lifecycle, session rhythm, completion ritual (read once)
- `@docs/architecture.md` — system design + Known Constraints (read the section you need, never in full)
- `@docs/decisions.md` — the Key Decisions register in full (the digest below is one line each)
- `@docs/specs/INDEX.md` — the spec index + status (one row per spec)
- `@docs/specs/ARCS.md` — why an arc exists / how its specs compose (only for the arc you're in)
- `@docs/specs/SPEC-XXX-*.md` — the spec you're implementing
- `@docs/component-inventory.md` — **router** to the per-area inventories; read only the area(s) you need
- `@docs/spec-delivery/SPEC-XXX-*.md` — what a past spec delivered (pull only when a dependency points to one)
- `@docs/best-practices/INDEX.md` — domain coding rulebooks (React, accessibility, …); route here, then load only the section(s) you need

**Context discipline:** these are pointers, not a reading list. Pull a doc when a task needs it.

---

## Project Overview

A web portal where authenticated users upload/download files to/from their own S3 prefix.
Auth is AWS Cognito (standalone User Pool + Identity Pool). **No backend** — the SPA calls
AWS directly with scoped credentials. Status: greenfield, no production users yet.

## Monorepo (npm workspaces)

- `apps/portal/` — React SPA (**all app code lives here**; paths below are relative to it)
- `infra/` — OpenTofu IaC (**all IaC paths relative to here**); bounded-context modules under `infra/modules/`
- `packages/` — reserved, currently empty
- `docs/` — architecture, specs, spec-delivery, templates

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite, TypeScript (strict), TailwindCSS; `focus-trap-react` (focus trapping for Modal/Drawer) |
| AWS | `@aws-sdk/client-s3` v3 (modular), `s3-request-presigner`, `lib-storage`; `aws-amplify` v6 for Cognito; `@aws-sdk/client-athena` + `@aws-sdk/client-glue` (analytics, SPEC-034); `@aws-sdk/client-sqs` (shared-space control plane, SPEC-051) |
| Editor | `@monaco-editor/react` + `monaco-editor` (self-hosted workers; lazy-loaded on the Query route only, SPEC-035) |
| Routing / state | `react-router-dom` v7; TanStack Query (server state) + Context/`useReducer` (UI state); no Redux |
| Testing / lint | Vitest + React Testing Library + `@testing-library/user-event`; `@vitest/coverage-v8` (`npm run test:coverage`); `vitest-axe` (axe-core a11y assertions, SPEC-045); ESLint + Prettier. Tests are **integration-style** — render real hooks/children, mock only the AWS service boundary; shared harness `src/test/renderWithProviders.tsx`. Rules: `best-practices/react/react.md` §21 |
| IaC | OpenTofu (HCL, S3 remote state) |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS SDK: v3 modular only; instantiate clients in `src/lib/` (never in components); all S3 ops go through service files.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Vite env vars: prefix `VITE_`; document each in `apps/portal/.env.example`.
- **No verbose comments in `.ts`/`.tsx`/`.py` files.** JSDoc (TS/React) and docstrings (Python) are the primary source of context — expand those over adding narrative inline comments; comments are reserved for the non-obvious *why*, kept short. Detail: `best-practices/react/react.md` §19, `best-practices/python/python.md` §14.
- When writing/refactoring code in a domain with a rulebook (React, accessibility, …), consult `@docs/best-practices/INDEX.md` first and load only the relevant section(s) — don't reinvent or guess the rules.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
npm run format|format:check -w apps/portal   # Prettier (prettier.config.js); format:check gates CI before tests
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
```

## Specs

Status is authoritative in `@docs/specs/INDEX.md` (each spec file's header carries its own `Status`);
arc narrative is in `@docs/specs/ARCS.md`. **Keep the note below to what's live and not yet written
down elsewhere — when a spec closes, prune it rather than appending.**

**Current work — data-quality arc.** 108→114 + 123/124 + 125/126 complete. **No spec is open.**
- **LIVE VERIFICATION IS OWED — 124 is now built, so the arc is due its one smoke pass** (user
  decision 2026-07-21). 114, 123 and 124 are merged and deployed **unproven against real
  SQS/SFN/Cognito/S3** — scenarios are in each spec's Phase 2. Three changes most deserve it: 114's
  `reportKey` Pass-state seeding (the SPEC-108 smoke test has caught that class before), 123's
  **conditional-put CAS** (unit tests can only check it against a hand-written *model* of S3), and
  124's dashboard enqueue, whose whole path to SQS has only ever run against a mock. **126 owes its
  own live check too** — hand-place a malformed body on the data-quality DLQ with a valid token and
  confirm one "couldn't be started" notification arrives naming no path from the body.
- **SPEC-125 owes a shared-space smoke run** (create → add-member → leave → delete). It attached the
  `cpcommon` layer to all 8 verbs, and a shared layer's import-time `_require` fails at **cold
  start** — the one failure mode no unit test can reach (PR #196). Check the 8 functions' first
  invoke after deploy before trusting the arc.
- **Known bug (114/112):** on a folder whose files disagree about columns, the ragged-row count
  includes every line of the minority file **plus every header** — the check compares against the
  *union* column count, and `report.py`'s "a header is never ragged" assumption only holds when files
  agree. Two findings double-reporting one cause.

---

## Key Decisions (settled — don't re-litigate)

One line each. **Full reasoning + the "do NOT build" fences: `@docs/decisions.md`** — read the entry
before working in that area; the line here is a reminder, not the spec.

- **Auth:** Cognito User Pool → Identity Pool (ABAC); `username` principal tag stamped server-side from the verified claim (unspoofable). One shared role; isolation via `${aws:PrincipalTag/username}`. (SPEC-011)
- **Hosted UI = Managed Login v2** (`managed_login_version = 2`); classic Hosted UI broke the post-signup redirect. CI re-ensures default branding post-apply.
- **No backend:** browser → AWS direct. Cognito trigger Lambdas allowed (service config, not an API).
- **State:** TanStack Query = server state; Context+`useReducer` = UI state. No Redux. (SPEC-015)
- **File ops = filesystem UX;** S3 has no move/rename → `CopyObject`+`DeleteObject`, folder ops recursive + non-atomic, collisions warn-and-confirm. (architecture.md Known Constraints)
- **Analytics (032→036):** in-app Athena/Glue/LF workspace; isolation = `username` principal tag on the Glue DB ARN (DB name = username), **not** LF-Tags.
- **Usernames** = S3 prefix = principal tag = Glue DB name; catalog-safe `^[a-z][a-z0-9_]{2,62}$` (SPEC-033).
- **Query workspace has NO active database** (SPEC-077, supersedes 047/076): every base table is fully-qualified `database.table`; rail is browse-only.
- **Multi-statement scripts (078):** client-side `;` split, sequential stop-on-first-failure, 3 run scopes (⌘⏎ / ⌘⇧⏎ / ⌘⌥⏎). No transactions.
- **Bucket 2 (shared-space):** privileged async control plane (FIFO SQS → Pipe → SFN → single-task verb Lambdas + `cpcommon` **and** a domain-only `shared-space-common` layer since SPEC-125, one shared `orchestrator` role). Create is creator-only. Record: `docs/shared-spaces-architecture.md`.
- **Member join status (073):** 7th verb `acknowledge-membership` flips pending→active; display/bookkeeping only, access granted at add time.
- **Member roster (075):** reverses 053 — every member sees a read-only roster; `cache.write_roster_to_all` fans out on add/remove/leave.
- **Table Builder (066→072):** dedicated control plane (5 linear verbs, one role, `tbcommon` + `polars` layers). Partition keys are **user-declared** + Athena partition projection. CSV all-string. Record: `docs/table-builder-architecture.md`.
- **Table Share (088→094):** dedicated control plane w/ recipient `Map`; **clone** the source Glue table def, never re-infer; push (no consent). Record: `docs/table-share-architecture.md`.
- **Data-quality report view (113):** `/data-quality/:space/:requestId` — space is **in the route, not derived**; own username wins; unreachable space renders denied and issues **no S3 request** (no existence oracle).
- **Data-quality runs index (123):** the `/data-quality` list is backed by a per-space `index.json` appended under **ETag CAS** (S3 lists lexicographically, so a UUID key gives no chronology); capped at 200, every failure swallowed — report → notification → index, most durable to least. No new IAM.
- **Data-quality notifications (114):** the notification **is** the completion channel and must carry the report link (the reports folder is hidden); the link builder mirrors 113's precedence and mints **nothing** where the view would resolve wrong. One dedup token per *outcome*, not per verb. `TerminalError` gained `tokens` (user-facing; `detail` stays operator-only). FR-005's alarms were **removed** → **SPEC-126**.
- **Control-plane DLQ drain (126):** one shared Lambda on all four request DLQs turns a dead-lettered request into a user notification — recipient from the **verified token** (expiry relaxed via a separately-named `cpcommon.auth` entry point), **nothing from the untrusted body** in the message, every path total (a throw would loop invisibly). The **notifications DLQ stays undrained** (circular). No redrive, no alarms.
- **Control-plane table creation = TBAC (070/111 correction):** LF **admin does NOT grant `CREATE_TABLE`**. A `portal-managed` LF-Tag on every DB + one tag-policy grant per execution role + static per-bucket `DATA_LOCATION_ACCESS`. (Distinct from the per-user isolation tag.)
- **No ASL state decodes an error Cause (#252, control-plane-wide):** `States.StringToJson($.error.Cause)` raises `States.Runtime`, **uncatchable anywhere**. Carry raw `$.error`; decode via `cpcommon.errors.failure_reason`.
- **IaC:** OpenTofu; `infra/modules/` bounded-context; IAM policies are `.tftpl` rendered with `templatefile()`.
- **Dev-unauth path:** `VITE_S3_DEV_UNAUTH=true` = read-only test bucket, local only.
- **Notifications (058→061):** per-user inbox JSON; **single-writer** FIFO SQS → writer Lambda (no Pipe/SFN); browser only reads + enqueues; anti-spoof via verified ID-token claim. Optional `link` gated by `isSafeInAppPath`.
- **Responsive (095):** mobile-first, only `tablet:` (≥900) / `desktop:` (≥1300) compile; reflow on **one** tree (a `*Mobile`/`*Desktop` twin is a smell); `useIsMobile` for mount-gating only, never styling.
- **Help & guides (074):** `/help` page from static code-grounded `helpContent.ts`; document only shipped, wired-end-to-end behavior.
- **User-facing error messaging (106):** raw AWS/Cognito/Athena text is **never** shown; `lib/errorMessages.ts` `toUserMessage` is the single source of wording — never render `error.message`.

## Out of Scope (don't build)

No backend/API layer · no in-browser file preview · no admin UI · no multi-bucket support (initial).

---

## Session Workflow

**Start:** (1) this file; (2) the spec you're implementing (`@docs/specs/SPEC-XXX`); (3) for context, pull **only** what the spec touches — the matching `component-inventory/` area file(s), the one architecture.md section, the `decisions.md` entry for the area, a dependency's delivery doc. Never read architecture.md, the inventory, or delivery docs in full. (4) Confirm `gh run list --branch main --limit 5` is green (esp. Deploy Infrastructure / Lambdas / App); investigate failures before building. (5) Branch from fresh `main` (`git fetch && git switch -c <branch> origin/main`). (6) Generate an implementation plan from the spec's phases, validate it against the spec (FRs + acceptance criteria covered, reuse used, nothing out of scope), and confirm it before writing code.

**During:** after a phase, stop and summarize what was built and how it maps to the plan. Specs carry no Open Questions — triage emergent issues by kind: **reversible/technical** ones you decide in-session (update the spec if scope changes); **product-changing or ambiguous** ones you stop and escalate to the human with options + a recommendation, never silently decide.

**Review:** code review and verification run in a **fresh context** (new session or subagent), never the session that wrote the code — check the diff against the spec's acceptance criteria, not just "looks fine."

**PRs & main:** before opening a PR, get the formatter, linter, and unit tests green locally. Watch every PR to completion and merge it as soon as CI is green — never open-and-abandon. `main` is always watched: after any merge confirm it went green, and if `main` fails, diagnose immediately and fix it with a new PR before anything else.

**Infra rule:** any spec that provisions new infra must expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) as in-scope work — not an afterthought. Adding a *new resource type* trips recurring IAM/propagation traps (self-grant timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) and Lambda code/infra split — read architecture.md → *Deploy-role IAM — adding a new resource type* + *Lambda code/infra split* first.

**On spec completion — keep the always-loaded files lean:**
1. Set the spec file's `Status: Completed`.
2. Update the one-line row in `@docs/specs/INDEX.md` (status only — don't add prose).
3. Write a delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from the template — **short** (what shipped + what changed; reuse lives in code + component-inventory, not prose).
4. If it added reusable services/hooks/components, add a one-line row to the matching `docs/component-inventory/<area>.md` (the router only gains a row if a whole new area appeared).
5. A *new architectural decision* gets the full entry in `@docs/decisions.md` and **one line** in Key Decisions above — never a paragraph in `CLAUDE.md`. Reasoning belongs in the spec/delivery doc.
6. **Prune `## Specs` → Current work:** delete what the closed spec made stale. It tracks *only* what is live and undocumented elsewhere — never append a changelog; INDEX.md has status and `ARCS.md` has narrative.
7. **User-facing docs sweep:** if the spec changed anything a user can see, update the in-app **Help & guides** content (`apps/portal/src/features/help/helpContent.ts`, SPEC-074) and any onboarding copy — add a guide for a newly-shipped feature, fix steps/labels for a changed flow, delete a removed one. Document only what's shipped + wired end-to-end (SPEC-074 FR-005). If nothing user-facing changed, note that and skip.

**Doc-size guardrail:** `CLAUDE.md` is the always-loaded file — if an edit pushes a section past a
few lines, the detail belongs in a `docs/` file behind a pointer. Same for `INDEX.md` (status rows
only) and the inventory router.
