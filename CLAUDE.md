# S3 File Portal — Project Memory

This file is loaded by Claude Code at the start of every session.
Keep it lean. Deep documentation lives in `docs/` — reference with `@docs/filename.md` when needed.

---

## Project Overview

A web portal that allows authenticated users to upload and download files to/from their designated S3 bucket. Authentication is handled by AWS Cognito (standalone User Pool — no external IdP).

**Status:** Greenfield — early development.

---

## Monorepo Structure

This is an npm workspaces monorepo. The React SPA lives in `apps/portal/`. Infrastructure (OpenTofu) lives in `infra/`. A `packages/` directory is reserved for future shared packages but is currently empty.

**All app code paths are relative to `apps/portal/` unless stated otherwise.**
**All IaC paths are relative to `infra/`.**

```
/
├── CLAUDE.md                  ← you are here
├── package.json               ← workspace root (npm workspaces: apps/*, packages/*)
├── docs/
│   ├── architecture.md        ← system design decisions
│   ├── spec-delivery/
│   │   └── *.md               ← what's been delivered per spec so far
│   ├── specs/
│   │   └── *.md               ← feature specs (reference with @docs/specs/SPEC_NAME.md)
│   └── templates/
│       ├── spec-template.md
│       └── spec-completion-template.md
├── apps/
│   └── portal/                ← React SPA (all app code lives here)
│       ├── src/
│       │   ├── components/    ← shared UI components
│       │   ├── features/      ← feature-scoped folders (see conventions below)
│       │   ├── hooks/         ← shared custom hooks
│       │   ├── lib/           ← AWS SDK clients, utility functions
│       │   ├── types/         ← shared TypeScript types and interfaces
│       │   └── main.tsx
│       ├── .env.example       ← required env vars (no secrets committed)
│       ├── package.json       ← app package
│       ├── vite.config.ts
│       └── tsconfig*.json
├── infra/                     ← OpenTofu IaC (SPEC-003)
│   ├── bootstrap/
│   ├── main.tf                ← module composition (bounded-context modules)
│   ├── moved.tf               ← state migrations from the flat→module refactor
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── app/               ← SPA hosting: static bucket, CloudFront, OAC
│       └── base/              ← OIDC provider + deploy role (policies/ = .tftpl templates)
└── packages/                  ← reserved for future shared packages (currently empty)
```

> **Migration complete:** The app code was at the repo root through SPEC-002. It has been migrated to `apps/portal/` and the root `package.json` converted to an npm workspace root. All subsequent work happens under `apps/portal/`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite |
| Language | TypeScript (strict mode) |
| Styling | TailwindCSS |
| AWS SDK | `@aws-sdk/client-s3` (v3, modular). No STS SDK — scoped credentials come from Amplify via the Identity Pool (SPEC-011). `@aws-sdk/s3-request-presigner` for presigned downloads (SPEC-015); `@aws-sdk/lib-storage` for managed/multipart uploads (SPEC-016) |
| Auth | AWS Cognito + Amplify (`aws-amplify` v6) — IaC + login/signup specced in SPEC-006–009 |
| Routing | `react-router-dom` v7 (library mode) — introduced by SPEC-008 |
| Server state | TanStack Query (`@tanstack/react-query`) for S3 reads/writes — caching, refetch, invalidation (introduced by SPEC-015) |
| UI state | React Context + `useReducer` (selection, upload queue). No Redux — TanStack Query owns server state, so a global client store isn't needed |
| Testing | Vitest + React Testing Library |
| Linting | ESLint + Prettier |
| Monorepo | npm workspaces |

Do not introduce new dependencies without noting them here first.

---

## Code Conventions

All conventions below apply to code under `apps/portal/`. Paths are relative to `apps/portal/`.

### General

- TypeScript strict mode. No `any` — use `unknown` and narrow it.
- Named exports only. No default exports except for page-level route components.
- Async/await only. No `.then()` / `.catch()` chains.
- All errors must be caught and surfaced — never swallow silently.

### File naming

- Components: `PascalCase.tsx`
- Hooks: `useCamelCase.ts`
- Utilities/lib: `camelCase.ts`
- Types: `camelCase.types.ts`

### Feature folder structure
Each feature lives in `src/features/<feature-name>/` (i.e. `apps/portal/src/features/<feature-name>/`) with this shape:
```
src/features/file-browser/
  index.ts              ← public barrel export
  FileBrowser.tsx       ← top-level component
  FileBrowser.test.tsx  ← co-located tests
  useFileBrowser.ts     ← feature hook (business logic)
  fileBrowser.types.ts  ← feature-scoped types
  fileBrowser.service.ts← direct AWS SDK calls
```

### AWS SDK

- Always use the v3 modular SDK (`@aws-sdk/client-s3`), not v2.
- Instantiate clients in `src/lib/s3Client.ts` — do not create clients inside components.
- All S3 operations go through service files, not directly in components or hooks.

### Error handling

All errors returned from services should use this shape:
```ts
type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; error: { message: string; code?: string } };
```
Never throw from service functions — return the error shape instead.

### Environment variables

Prefix all Vite env vars with `VITE_`. Document every new variable in `apps/portal/.env.example`.

---

## Common Commands

App commands run from `apps/portal/` (or from repo root using the `-w` workspace flag):

```bash
# From apps/portal/
npm run dev          # start Vite dev server
npm run build        # production build (output: apps/portal/dist/)
npm run preview      # preview production build locally
npm run test         # run Vitest
npm run test:ui      # Vitest UI mode
npm run lint         # ESLint check
npm run format       # Prettier format

# From repo root (workspace flag)
npm run dev -w apps/portal
npm run build -w apps/portal
npm run test -w apps/portal

# Workspace install (from repo root)
npm install          # installs all workspace dependencies
```

IaC commands run from `infra/`:
```bash
tofu init -backend-config=backend.conf   # backend.conf is gitignored — see infra/bootstrap/backend.conf.example
tofu validate        # validate configuration
tofu plan            # preview changes
tofu apply           # apply changes
tofu output          # view output values (use to populate .env.local)
```

---

## Active Specs

| Spec | File | Status |
|---|---|---|
| S3 File Listing | `@docs/specs/SPEC-001-s3-file-listing.md` | Completed |
| Browse Prefixes (Public Bucket File Browser) | `@docs/specs/SPEC-002-browse-prefixes.md` | Completed |
| Project IaC (OpenTofu) | `@docs/specs/SPEC-003-project-iac.md` | Completed |
| GitHub Actions CI (test + build) | `@docs/specs/SPEC-004-github-actions-ci.md` | Completed |
| Deploy App to AWS (GitHub Actions + OpenTofu) | `@docs/specs/SPEC-005-deploy-app-to-aws.md` | Completed |
| Cognito User Pool IaC (`auth` module) | `@docs/specs/SPEC-006-cognito-iac.md` | Completed |
| Login Flow (Hosted UI + Amplify) | `@docs/specs/SPEC-007-login-flow.md` | Completed |
| Auth-Gated Layout (react-router) | `@docs/specs/SPEC-008-auth-gated-layout.md` | Completed |
| Sign-Up End to End | `@docs/specs/SPEC-009-signup-end-to-end.md` | Completed |
| User-Space Bucket IaC (`data` module) | `@docs/specs/SPEC-010-user-space-bucket-iac.md` | Completed |
| Scoped Credentials (Identity Pool ABAC + Portal Role) | `@docs/specs/SPEC-011-portal-iam-role.md` | Completed |
| Pre-Signup Username Validation (Lambda) | `@docs/specs/SPEC-012-pre-signup-validation.md` | Completed |
| Prefix-Scoped S3 Access + Browser Switchover | `@docs/specs/SPEC-013-prefix-scoped-access.md` | Completed |
| User Prefix Marker (DO_NOT_DELETE.txt) | `@docs/specs/SPEC-014-user-prefix-marker.md` | Completed |
| File Download + Data Foundation (TanStack Query) | `@docs/specs/SPEC-015-file-download-and-data-foundation.md` | Completed |
| File Upload (managed, auto-multipart + progress) + Create Folder | `@docs/specs/SPEC-016-file-upload-and-create-folder.md` | Completed |
| File Metadata Panel | `@docs/specs/SPEC-017-file-metadata-panel.md` | Completed |
| Delete Files and Folders (recursive) | `@docs/specs/SPEC-018-delete-files-and-folders.md` | Completed |
| Move & Rename (files and folders) | `@docs/specs/SPEC-019-move-and-rename.md` | Draft |
| Upload Queue (multi-file, concurrency, cancel) | `@docs/specs/SPEC-020-multipart-upload.md` | Draft |

Add new specs to this table as they are created.

> **File-operations arc (SPEC-015→020):** turns the read-only browser into a filesystem-like experience (download, upload, create folder, metadata, delete, move, rename, large-file upload). All depend on SPEC-013 (browser on the authenticated user-space bucket). Move/rename are presented as first-class actions but implemented as copy-then-delete; folder operations are recursive and non-atomic. See `docs/architecture.md` Known Constraints.

---

## Key Decisions Log

> Use this section to capture architectural decisions so Claude doesn't re-debate them.

- **Amplify v6 for Cognito**: Chosen over manual Cognito SDK calls for easier token refresh handling. Auth is deferred — not yet implemented.
- **State management — TanStack Query + Context (decided 2026-06-11, supersedes "No Redux")**: The original "No Redux; React Context only" call held through the auth specs. The file-operations arc (SPEC-015→020) adds listing caches, refetch-after-mutation, and optimistic updates against S3 — classic async *server* state. `@tanstack/react-query` owns that (caching, invalidation, retry); React Context + `useReducer` owns *UI* state (multi-select, upload queue). Redux is still not used and not needed — Query removes the cross-feature server-state problem that would have motivated it.
- **File operations are presented as a filesystem, regardless of S3 semantics (decided 2026-06-11)**: Users get download, upload, create-folder, metadata, delete, move, and rename. S3 has no move/rename — both are implemented as `CopyObject` + `DeleteObject` (rename = move within the same parent). Folders are zero-byte `{name}/` marker objects; folder move/rename/delete are *recursive* over every contained key and *non-atomic* (a per-key copy failure never deletes that source and never aborts the rest). Name collisions are handled by warn-and-confirm (HEAD-check → Overwrite or Rename), because versioning is off (SPEC-010) and a blind overwrite would be silent data loss. Downloads use short-lived presigned URLs (`@aws-sdk/s3-request-presigner`); uploads use the managed `@aws-sdk/lib-storage` `Upload` (single request below a 5 MiB part-size threshold, automatic multipart above it) with live progress. Single-object CRUD + copy are already covered by SPEC-013's IAM grants; multipart needs added IAM actions + an abort-incomplete lifecycle rule, both delivered in **SPEC-016** (SPEC-020 adds only the multi-file queue + cancel on top).
- **S3 SDK direct from browser**: Acceptable for this use case. Session tag scoping will enforce per-user isolation once auth is added. No backend proxy needed.
- **Monorepo — npm workspaces**: SPA (`apps/portal/`) and IaC (`infra/`) co-located in one repo. `packages/` reserved for future shared packages. npm workspaces chosen for simplicity — no Turborepo or pnpm needed at current scale.
- **OpenTofu for IaC**: Open-source Terraform fork. HCL syntax, AWS provider, S3 remote state backend. Chosen over CDK/Pulumi/SST.
- **Cognito Identity Pool with ABAC (reversed 2026-06-10 — was "No Identity Pool")**: The original direct-STS design required the browser to pass session tags, which is spoofable, and the Lambda-claim alternative required the Cognito Essentials V2 trigger. A Cognito Identity Pool with *attributes for access control* maps the username claim to the `username` principal tag server-side — unspoofable, free, no Lambdas, native Amplify v6 support (`fetchAuthSession()` returns scoped credentials). Still one shared IAM role for all users; per-user S3 isolation via `${aws:PrincipalTag/username}` (SPEC-011).
- **IaC scope — hosting layer only (SPEC-003)**: The current IaC provisions only the hosting infrastructure: static assets S3 bucket, CloudFront distribution, and the GitHub Actions OIDC deployment role. Data infrastructure (Cognito User Pool, shared IAM portal role, user-space S3 bucket, shared-space S3 bucket) was out of scope for SPEC-003 and will be added to the IaC in a future spec. Do not assume these resources exist in AWS until that spec is complete.
- **Bucket 2 access model redesigned**: The original design used a daily Terraform-managed IAM policy pipeline to grant/revoke prefix access. This has been replaced by a user-managed access key model — users will create keys and grant/revoke access to other users themselves. A backend service or cloud process will likely be required. This model is not yet designed or specced. Do not build anything referencing the old daily-IAM-pipeline model.
- **IaC organized as bounded-context modules**: `infra/modules/app/` (hosting) and `infra/modules/base/` (OIDC + deploy role). New infrastructure domains get their own module (e.g. `auth/` for Cognito, `data/` for personal/shared buckets) — do not group resources by AWS service type into shared files. IAM policies live as `.tftpl` JSON templates under the owning module's `policies/` folder, rendered with `templatefile()`.
- **Session tags are asserted server-side, never by the client**: The browser never passes `Tags` or any self-asserted identity to STS — client-supplied tags are spoofable. The Identity Pool's principal tag mapping stamps `username` from the verified token claim (SPEC-011). The earlier pre-token-generation-Lambda and `custom:portal_role_arn` designs are superseded and must not be built.
- **Cognito trigger Lambdas are permitted**: The "no server-side backend" decision means no API layer the SPA calls. Cognito lifecycle triggers (e.g. the SPEC-012 pre-signup username validator) are configuration of the auth service, not a backend, and are allowed.
- **Usernames are validated at signup**: A pre-signup Lambda enforces `^[a-zA-Z0-9._@-]{3,64}$` (SPEC-012) and the User Pool is case-insensitive (SPEC-006), because the username becomes the user's S3 prefix and IAM principal tag.
- **Infra specs must account for deploy role permissions**: The GitHub Actions deploy role (`infra/modules/base/`) applies all IaC via `deploy-infra.yml`. Any spec that provisions new infrastructure must include expanding the deploy role's IAM permissions to manage those new resource types (update the `.tftpl` policies under `infra/modules/base/policies/`) as in-scope work — not an afterthought or open question.
- **Current dev working state**: Until auth is implemented, the app targets a single publicly accessible or statically credentialed test bucket. `VITE_AWS_ACCESS_KEY_ID` being absent causes the S3 client to fall back to anonymous (unsigned) requests (SPEC-002). Authentication, user prefix scoping, and multi-bucket support are all deferred.

---

## Out of Scope (Do Not Build)

- No server-side backend / API layer (direct browser → AWS architecture)
- No file preview rendering (PDF, image, etc.) in initial version
- No admin UI for managing users or buckets
- No multi-bucket support in initial version

---

## What to Do at the Start of Each Session

1. Read this file.
2. Read the file at [`@docs/architecture.md`]
3. Read the spec for the feature being worked on (`@docs/specs/<spec>.md`).
4. **Do not eagerly read every delivery doc** — they grow one-per-spec and bloat context, and reuse knowledge lives in the code, not the doc prose. Instead: (a) skim [`@docs/component-inventory.md`] for reusable services/hooks/components already available; (b) `grep`/Explore the code area you'll touch for existing functions to reuse; (c) delegate the *current spec's dependency* delivery docs (named in its `Depends On:` line) + `@docs/architecture.md` to a subagent whose brief must answer "what already exists that I can reuse, and where." Pull a specific full delivery doc on demand only when the brief or code points to one.
5. Before starting any spec, check that the most recent GitHub Actions workflow runs on `main` succeeded (`gh run list --branch main --limit 10`) — confirm the prior spec's deploy ran smoothly. If any run failed (especially `Deploy Infrastructure` / `Deploy Lambdas` / `Deploy App`), investigate (`gh run view <id> --log-failed`) and resolve it before building on top of a broken `main`.
6. Before writing code for a new spec, start from an up-to-date `main` and branch from there: `git checkout main && git pull` (or `git fetch origin && git switch -c <branch> origin/main`), then create the feature branch (e.g. `feature-<short-name>`). This avoids branching off a stale `main` that's missing a just-merged spec's work. If you already have a branch that predates a recently merged spec, recreate or rebase it onto the latest `main`.
7. Confirm the phase to implement before writing any code.
8. After completing a phase, stop and summarize what was built and what the checkpoint test is.
9. When a spec is completed: (a) set its **Status** field to `Completed`, (b) update the Active Specs table in this file, (c) use the template at [`@docs/templates/spec-completion-template`] to create a delivery doc at [`@docs/spec-delivery/SPEC-<XXX>-<spec>.md`], (d) if the spec added reusable services/hooks/components/types/utilities, add them to [`@docs/component-inventory.md`] so they stay discoverable without re-reading delivery docs.
