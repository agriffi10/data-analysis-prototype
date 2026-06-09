# S3 File Portal — Project Memory

This file is loaded by Claude Code at the start of every session.
Keep it lean. Deep documentation lives in `docs/` — reference with `@docs/filename.md` when needed.

---

## Project Overview

A web portal that allows authenticated users to upload and download files to/from their designated S3 bucket. Authentication is handled by AWS Cognito federated to an external Active Directory.

**Status:** Greenfield — early development.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite |
| Language | TypeScript (strict mode) |
| Styling | TailwindCSS |
| AWS SDK | `@aws-sdk/client-s3` (v3, modular) |
| Auth | AWS Cognito + Amplify (`aws-amplify` v6) |
| State | React Context (no Redux unless complexity demands it) |
| Testing | Vitest + React Testing Library |
| Linting | ESLint + Prettier |

Do not introduce new dependencies without noting them here first.

---

## Repo Structure

```
/
├── CLAUDE.md                  ← you are here
├── docs/
│   ├── architecture.md        ← system design decisions
│   └── spec-delivery/
│       └── *.md               ← what's been delivered per spec so far
│   └── specs/
│       └── *.md               ← feature specs (reference with @docs/specs/SPEC_NAME.md)
├── src/
│   ├── components/            ← shared UI components
│   ├── features/              ← feature-scoped folders (see conventions below)
│   ├── hooks/                 ← shared custom hooks
│   ├── lib/                   ← AWS SDK clients, utility functions
│   ├── types/                 ← shared TypeScript types and interfaces
│   └── main.tsx
├── .env.example               ← required env vars (no secrets committed)
└── vite.config.ts
```

---

## Code Conventions

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
Each feature lives in `src/features/<feature-name>/` with this shape:
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
- Instantiate clients once in `src/lib/s3Client.ts` — do not create clients inside components.
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

Prefix all Vite env vars with `VITE_`. Document every new variable in `.env.example`.

---

## Common Commands

```bash
npm run dev          # start Vite dev server
npm run build        # production build
npm run preview      # preview production build locally
npm run test         # run Vitest
npm run test:ui      # Vitest UI mode
npm run lint         # ESLint check
npm run format       # Prettier format
```

---

## Active Specs

| Spec | File | Status |
|---|---|---|
| S3 File Listing | `@docs/specs/SPEC-001-s3-file-listing.md` | Completed |
| Browse Prefixes (Authenticated File Browser) | `@docs/specs/SPEC-002-browse-prefixes.md` | Completed |
| Project IaC (OpenTofu) | `@docs/specs/SPEC-003-project-iac.md` | Completed |
| Deploy App to AWS (GitHub Actions) | `@docs/specs/SPEC-004-deploy-app-to-aws.md` | Draft |

Add new specs to this table as they are created.

---

## Key Decisions Log

> Use this section to capture architectural decisions so Claude doesn't re-debate them.

- **Amplify v6 for Cognito**: Chosen over manual Cognito SDK calls for easier token refresh handling.
- **No Redux**: State complexity doesn't warrant it at this stage. Revisit if cross-feature state becomes a problem.
- **S3 SDK direct from browser**: Acceptable for this use case. Cognito Identity Pool will scope permissions per-user. No backend proxy needed.

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
7. When a spec is completed, update this document and the spec. Use the template at [`@docs/templates/spec-completion-template`] to create a file at [`@docs/spec-delivery/SPEC-<XXX>-<spec>.md] for the completed spec.
