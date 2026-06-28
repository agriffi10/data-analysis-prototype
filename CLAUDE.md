# S3 File Portal — Project Memory

Loaded every session — keep it lean. Deep docs live in `docs/` and are pulled **on demand**:
- `@docs/process.md` — how we work: spec lifecycle, session rhythm, completion ritual (read once)
- `@docs/architecture.md` — system design decisions + Known Constraints (read the section you need)
- `@docs/specs/INDEX.md` — the spec index + status (one row per spec)
- `@docs/specs/SPEC-XXX-*.md` — the spec you're implementing
- `@docs/component-inventory.md` — reusable services/hooks/components already built
- `@docs/spec-delivery/SPEC-XXX-*.md` — what a past spec delivered (pull only when a dependency points to one)
- `@docs/best-practices/INDEX.md` — domain coding rulebooks (React, accessibility, …); route here, then load only the section(s) you need

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
| Testing / lint | Vitest + React Testing Library; `vitest-axe` (axe-core a11y assertions, SPEC-045); ESLint + Prettier |
| IaC | OpenTofu (HCL, S3 remote state) |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS SDK: v3 modular only; instantiate clients in `src/lib/` (never in components); all S3 ops go through service files.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Vite env vars: prefix `VITE_`; document each in `apps/portal/.env.example`.
- When writing/refactoring code in a domain with a rulebook (React, accessibility, …), consult `@docs/best-practices/INDEX.md` first and load only the relevant section(s) — don't reinvent or guess the rules.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
npm run format|format:check -w apps/portal   # Prettier (prettier.config.js); format:check gates CI before tests
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
```

## Specs

Index + status: `@docs/specs/INDEX.md`. Each spec file's header carries its own `Status`.
**Current work:** SPEC-001→058 are complete & deployed (the shared-connections arc 050+056→055 + 057 is fully done; **058 notifications write pipeline is shipped & live-verified**). **Next up in the Notifications arc: 059 → 060 → 061, all Draft** — 059 data layer + 60s poll, 060 header-bell-link + `/notifications` page, 061 shared-workspace producer (seven events).

---

## Key Decisions (settled — don't re-litigate; detail in the linked spec/architecture)

- **Auth:** Cognito User Pool → Identity Pool (ABAC) stamps the `username` principal tag from the verified token claim **server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)
- **Hosted UI = Managed Login v2:** the domain runs Cognito **Managed Login** (`managed_login_version = 2`); the classic Hosted UI didn't complete the OAuth redirect after self-service signup confirmation (user landed confirmed-but-signed-out). Sign-in and signup both route through Amplify `signInWithRedirect`. The branding resource is provider-6.x-only (repo pins `~> 5.0`), so CI ensures Cognito's default branding post-apply (`deploy-infra.yml`); revisit when the provider is bumped.
- **No backend:** browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).
- **State:** TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)
- **File ops = filesystem UX:** download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md Known Constraints.
- **Analytics (SPEC-032→036):** in-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.
- **Usernames** are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.
- **Query workspace target DB:** one **workspace-global** active database for all tabs (not per-tab), chosen in the schema rail via the `useConnections` seam (personal-only today; shared-spaces extends it). (SPEC-047)
- **Bucket 2 (shared-space):** user-created shared connections via a privileged async control plane (FIFO SQS → EventBridge Pipe → Standard Step Function) — reverses "no backend" for shared-space mutations only; access = a membership principal tag (SPEC-056). The Step Function **orchestrates single-task verb Lambdas** (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave | delete-space`), each with its own least-privilege role + shared common code — **not** one monolithic provisioner (SPEC-062 refactor; the 050→054 monolith is decomposed). **Create is creator-only** (members added later via add-members from the Connections tab). Decision record: `docs/shared-spaces-architecture.md`; Lambda rules: `docs/best-practices/lambdas/lambdas.md`. Do NOT build the old daily-IAM-pipeline / user-managed-keys models.
- **IaC:** OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.
- **Dev-unauth path:** `VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).
- **Notifications (SPEC-058→061):** per-user inbox at `{username}/user_settings/notifications.json` (array of `{id,message,read,timestamp}`). **Single-writer:** all mutations (system `create` + user `markRead`/`markAllRead` — **no delete**) go through a **dedicated FIFO SQS queue that triggers the writer Lambda directly** (SQS event-source mapping, batch size 1 — **no Pipe, no Step Function**); per-user ordering via `MessageGroupId` = username. The browser only **reads** the file (+ a **60s background poll** for the unread icon) and enqueues (`sqs:SendMessage`). Anti-spoofing = user-action messages carry the Cognito **ID token**, writer derives `username` from the verified claim (`create` = trusted-producer-only). UI = header bell **linking to a `/notifications` page** (not a drawer, not a tab), **10/page**, mark-read/mark-all only. First `create` producer = the **shared-workspace control plane** (SPEC-061; seven lifecycle events, incl. delete fanning out to all members), granted `sqs:SendMessage` on the queue. (**058 write pipeline shipped** — `infra/modules/notifications/` + `lambdas/notifications-writer/`; 059–061 Draft.)

## Out of Scope (don't build)

No backend/API layer · no in-browser file preview · no admin UI · no multi-bucket support (initial).

---

## Session Workflow

**Start:** (1) this file; (2) the spec you're implementing (`@docs/specs/SPEC-XXX`); (3) for context, skim `@docs/component-inventory.md` and pull only the architecture.md section / dependency delivery-doc you actually need — don't read architecture.md or delivery docs in full. (4) Confirm `gh run list --branch main --limit 5` is green (esp. Deploy Infrastructure / Lambdas / App); investigate failures before building. (5) Branch from fresh `main` (`git fetch && git switch -c <branch> origin/main`). (6) Generate an implementation plan from the spec's phases, validate it against the spec (FRs + acceptance criteria covered, reuse used, nothing out of scope), and confirm it before writing code.

**During:** after a phase, stop and summarize what was built and how it maps to the plan. Specs carry no Open Questions — triage emergent issues by kind: **reversible/technical** ones you decide in-session (update the spec if scope changes); **product-changing or ambiguous** ones you stop and escalate to the human with options + a recommendation, never silently decide.

**Review:** code review and verification run in a **fresh context** (new session or subagent), never the session that wrote the code — check the diff against the spec's acceptance criteria, not just "looks fine."

**PRs & main:** before opening a PR, get the formatter, linter, and unit tests green locally. Watch every PR to completion and merge it as soon as CI is green — never open-and-abandon. `main` is always watched: after any merge confirm it went green, and if `main` fails, diagnose immediately and fix it with a new PR before anything else.

**Infra rule:** any spec that provisions new infra must expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) as in-scope work — not an afterthought. Adding a *new resource type* trips recurring IAM/propagation traps (self-grant timing, non-scopable actions, refresh deadlocks, unknown-ARN-in-list) and Lambda code/infra split — read architecture.md → *Deploy-role IAM — adding a new resource type* + *Lambda code/infra split* first.

**On spec completion — keep the always-loaded files lean:**
1. Set the spec file's `Status: Completed`.
2. Update the one-line row in `@docs/specs/INDEX.md` (status only — don't add prose).
3. Write a delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from the template — **short** (what shipped + what changed; reuse lives in code + component-inventory, not prose).
4. If it added reusable services/hooks/components, add a one-line row to `@docs/component-inventory.md`.
5. A *new architectural decision* gets **one line** in Key Decisions above (+ a pointer) — never a paragraph. Reasoning belongs in the spec/delivery doc, not here.
