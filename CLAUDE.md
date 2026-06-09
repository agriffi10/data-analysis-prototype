# S3 File Portal — Project Memory

This file is loaded by Claude Code at the start of every session.
Keep it lean. Deep documentation lives in `docs/` — reference with `@docs/filename.md` when needed.

---

## Project Overview

A web portal that allows authenticated users to upload and download files to/from their designated S3 bucket. Authentication is handled by AWS Cognito federated to an external Active Directory.

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
│   ├── main.tf (or *.tf)
│   ├── variables.tf
│   ├── outputs.tf
│   └── ...
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
| AWS SDK | `@aws-sdk/client-s3` (v3, modular) |
| Auth | AWS Cognito + Amplify (`aws-amplify` v6) — deferred, not yet implemented |
| State | React Context (no Redux unless complexity demands it) |
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
| Deploy App to AWS (GitHub Actions) | `@docs/specs/SPEC-004-deploy-app-to-aws.md` | Draft |

Add new specs to this table as they are created.

---

## Key Decisions Log

> Use this section to capture architectural decisions so Claude doesn't re-debate them.

- **Amplify v6 for Cognito**: Chosen over manual Cognito SDK calls for easier token refresh handling. Auth is deferred — not yet implemented.
- **No Redux**: State complexity doesn't warrant it at this stage. Revisit if cross-feature state becomes a problem.
- **S3 SDK direct from browser**: Acceptable for this use case. Session tag scoping will enforce per-user isolation once auth is added. No backend proxy needed.
- **Monorepo — npm workspaces**: SPA (`apps/portal/`) and IaC (`infra/`) co-located in one repo. `packages/` reserved for future shared packages. npm workspaces chosen for simplicity — no Turborepo or pnpm needed at current scale.
- **OpenTofu for IaC**: Open-source Terraform fork. HCL syntax, AWS provider, S3 remote state backend. Chosen over CDK/Pulumi/SST.
- **No Cognito Identity Pool**: Web Identity federation is performed directly via STS `AssumeRoleWithWebIdentity` using the User Pool JWT. Per-user S3 isolation via IAM session tags.
- **IaC scope — hosting layer only (SPEC-003)**: The current IaC provisions only the hosting infrastructure: static assets S3 bucket, CloudFront distribution, and the GitHub Actions OIDC deployment role. Data infrastructure (Cognito User Pool, shared IAM portal role, personal S3 bucket, shared S3 bucket) was out of scope for SPEC-003 and will be added to the IaC in a future spec. Do not assume these resources exist in AWS until that spec is complete.
- **Bucket 2 access model redesigned**: The original design used a daily Terraform-managed IAM policy pipeline to grant/revoke prefix access. This has been replaced by a user-managed access key model — users will create keys and grant/revoke access to other users themselves. A backend service or cloud process will likely be required. This model is not yet designed or specced. Do not build anything referencing the old daily-IAM-pipeline model.
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
4. Read the completed specs under [`@docs/spec-delivery/<spec>.md`]
5. Confirm the phase to implement before writing any code.
6. After completing a phase, stop and summarize what was built and what the checkpoint test is.
7. When a spec is completed, update this document and the spec. Use the template at [`@docs/templates/spec-completion-template`] to create a file at [`@docs/spec-delivery/SPEC-<XXX>-<spec>.md`] for the completed spec.
