# S3 File Portal — Project Memory

Loaded every session — keep it lean. Deep docs live in `docs/` and are pulled **on demand**:
- `@docs/architecture.md` — system design decisions + Known Constraints (read the section you need)
- `@docs/specs/INDEX.md` — the spec index + status (one row per spec)
- `@docs/specs/SPEC-XXX-*.md` — the spec you're implementing
- `@docs/component-inventory.md` — reusable services/hooks/components already built
- `@docs/spec-delivery/SPEC-XXX-*.md` — what a past spec delivered (pull only when a dependency points to one)

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
| Frontend | React 18 + Vite, TypeScript (strict), TailwindCSS |
| AWS | `@aws-sdk/client-s3` v3 (modular), `s3-request-presigner`, `lib-storage`; `aws-amplify` v6 for Cognito; `@aws-sdk/client-athena` + `@aws-sdk/client-glue` (analytics, SPEC-034) |
| Editor | `@monaco-editor/react` + `monaco-editor` (self-hosted workers; lazy-loaded on the Query route only, SPEC-035) |
| Routing / state | `react-router-dom` v7; TanStack Query (server state) + Context/`useReducer` (UI state); no Redux |
| Testing / lint | Vitest + React Testing Library; ESLint + Prettier |
| IaC | OpenTofu (HCL, S3 remote state) |

Don't add dependencies without noting them here first.

## Code Conventions (apps/portal/)

- TS strict; no `any` (use `unknown` + narrow). Named exports only (default only for page-level route components). Async/await only. Never swallow errors.
- Naming: `PascalCase.tsx` components, `useCamelCase.ts` hooks, `camelCase.ts` utils, `camelCase.types.ts` types.
- Features in `src/features/<name>/`: `index.ts` barrel, `Component.tsx` (+ co-located `.test.tsx`), `useFeature.ts`, `feature.types.ts`, `feature.service.ts`.
- AWS SDK: v3 modular only; instantiate clients in `src/lib/` (never in components); all S3 ops go through service files.
- Services never throw — return `ServiceResult<T>` (`{success:true,data} | {success:false,error:{message,code?}}`).
- Vite env vars: prefix `VITE_`; document each in `apps/portal/.env.example`.

## Common Commands

```bash
npm run dev|build|test|lint -w apps/portal   # from repo root (or omit -w inside apps/portal/)
tofu -chdir=infra validate|plan|apply        # init: tofu -chdir=infra init -backend-config=backend.conf
```

## Specs

Index + status: `@docs/specs/INDEX.md`. Each spec file's header carries its own `Status`.
**Current work:** analytics arc SPEC-032→036 (in-app Athena query workspace) is **complete**; next is pagination/copy (037–039).

---

## Key Decisions (settled — don't re-litigate; detail in the linked spec/architecture)

- **Auth:** Cognito User Pool → Identity Pool (ABAC) stamps the `username` principal tag from the verified token claim **server-side** (unspoofable; never client-asserted). One shared IAM role for all users; per-user isolation via `${aws:PrincipalTag/username}`. (SPEC-011; reversed the earlier "no Identity Pool".)
- **No backend:** browser → AWS direct. Cognito **trigger Lambdas** are allowed (service config, not an API).
- **State:** TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)
- **File ops = filesystem UX:** download/upload/folder/metadata/delete/move/rename/copy. S3 has no move/rename → `CopyObject`+`DeleteObject` (folder ops recursive + non-atomic). Collisions = warn-and-confirm (versioning is off). Detail: architecture.md Known Constraints.
- **Analytics (SPEC-032→036):** in-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.
- **Usernames** are the S3 prefix = principal tag = Glue DB name → validated at signup by the pre-signup Lambda; SPEC-033 tightens to catalog-safe `^[a-z][a-z0-9_]{2,62}$`.
- **Bucket 2 (shared-space):** access model = user-managed keys, **not yet designed/built**. Do NOT build the old daily-IAM-pipeline model.
- **IaC:** OpenTofu (over CDK/Pulumi/SST); `infra/modules/` are bounded-context (app/base/auth/data/analytics); IAM policies are `.tftpl` templates under each module's `policies/`, rendered with `templatefile()`.
- **Dev-unauth path:** `VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

## Out of Scope (don't build)

No backend/API layer · no in-browser file preview · no admin UI · no multi-bucket support (initial).

---

## Session Workflow

**Start:** (1) this file; (2) the spec you're implementing (`@docs/specs/SPEC-XXX`); (3) for context, skim `@docs/component-inventory.md` and pull only the architecture.md section / dependency delivery-doc you actually need — don't read architecture.md or delivery docs in full. (4) Confirm `gh run list --branch main --limit 5` is green (esp. Deploy Infrastructure / Lambdas / App); investigate failures before building. (5) Branch from fresh `main` (`git fetch && git switch -c <branch> origin/main`). (6) Confirm the phase before writing code.

**During:** after a phase, stop and summarize what was built + the checkpoint test.

**Infra rule:** any spec that provisions new infra must expand the deploy role's IAM (`.tftpl` under `infra/modules/base/policies/`) as in-scope work — not an afterthought.

**On spec completion — keep the always-loaded files lean:**
1. Set the spec file's `Status: Completed`.
2. Update the one-line row in `@docs/specs/INDEX.md` (status only — don't add prose).
3. Write a delivery doc at `docs/spec-delivery/SPEC-XXX-<name>.md` from the template — **short** (what shipped + what changed; reuse lives in code + component-inventory, not prose).
4. If it added reusable services/hooks/components, add a one-line row to `@docs/component-inventory.md`.
5. A *new architectural decision* gets **one line** in Key Decisions above (+ a pointer) — never a paragraph. Reasoning belongs in the spec/delivery doc, not here.
