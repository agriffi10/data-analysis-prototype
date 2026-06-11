# Spec: Auth-Gated Layout — Protect the S3 Interface

**ID:** SPEC-008
**Status:** Draft
**Last Updated:** 2026-06-10
**Depends On:** SPEC-007 (auth state must exist)

## Overview

Restrict the S3 file browser to authenticated users. This spec introduces client-side routing (react-router) and a protected layout: unauthenticated visitors see a public landing/login page and are never shown the file browser; authenticated users land on the files page. This is a UX gate, not a security boundary — real enforcement happens at the IAM layer once STS integration lands — but it prevents non-authenticated users from accessing the S3 interface page and establishes the route structure for all future pages.

## Scope

### In Scope

- Add `react-router-dom` dependency (new — record in CLAUDE.md tech stack table)
- Route structure: public landing page (`/`), protected files page (`/files`)
- `ProtectedLayout` route guard that redirects unauthenticated users away from protected routes
- Post-login redirect to `/files` (including returning to the originally requested protected URL)
- Move the file browser rendering from `App.tsx` into a `/files` route page
- Loading state handling so protected content never flashes before auth resolves

### Out of Scope

- Signup flows (SPEC-009)
- Per-user S3 scoping or any change to which bucket the browser shows — still the SPEC-002 test bucket
- Role-/group-based authorization (all authenticated users see the same thing)
- Additional pages (connection manager, upload UI, etc.)
- Server-side or IAM-layer enforcement (future STS/IAM spec)

---

## Functional Requirements

### FR-001: Router Introduction

#### Description:

The app adopts react-router with a layout-route architecture, preserving current behavior for authenticated users.

#### Acceptance Criteria:

- [ ] `react-router-dom` (v7, library mode) is added to `apps/portal/package.json`
- [ ] `main.tsx` renders a `RouterProvider`/`BrowserRouter` inside `AuthProvider`
- [ ] Routes: `/` (public landing), `/files` (protected — file browser)
- [ ] Unknown routes render a minimal not-found page with a link back to `/`
- [ ] Direct navigation and refresh on `/files` work when deployed (CloudFront 403/404 → `index.html` rewrite from SPEC-003 — verify, no infra change expected)

### FR-002: Public Landing Page

#### Description:

Unauthenticated visitors get a simple landing page that explains the portal and offers sign-in.

#### Acceptance Criteria:

- [ ] `/` shows the app name, a one-line description, and a "Sign in" call-to-action invoking `signIn()` from SPEC-007
- [ ] An authenticated user visiting `/` is redirected to `/files`
- [ ] The landing page renders no S3 data and makes no S3 calls

### FR-003: Protected Layout Route Guard

#### Description:

A shared layout wraps all protected routes and enforces the auth gate in one place.

#### Acceptance Criteria:

- [ ] `ProtectedLayout` renders the shared header (SPEC-007) plus an `<Outlet />` for child routes
- [ ] While auth status is `loading`, the layout renders a loading indicator — protected content is never mounted (no flash, no S3 requests fire)
- [ ] When `unauthenticated`, navigating to any protected route redirects to `/` — the file browser component is never mounted
- [ ] When `authenticated`, child routes render normally
- [ ] Signing out while on a protected route immediately redirects to `/`

### FR-004: Post-Login Return Path

#### Description:

Users who tried to reach a protected URL while signed out return to it after login.

#### Acceptance Criteria:

- [ ] When an unauthenticated user hits a protected route, the intended path is preserved in `sessionStorage` (router state alone does not survive the full-page OAuth redirect)
- [ ] After completing Hosted UI login, the user lands on the originally requested route
- [ ] With no stored return path, login lands on `/files`

### FR-005: Files Page Migration

#### Description:

The existing file browser moves from `App.tsx` into a routed page without behavior change.

#### Acceptance Criteria:

- [ ] `/files` renders `FileBrowser` with the same env-driven bucket/prefix wiring as today (including the missing-`VITE_S3_BUCKET_NAME` config error state)
- [ ] All existing `FileBrowser` tests still pass unmodified
- [ ] Breadcrumb/prefix navigation within the browser is unaffected

---

## Data Model

No new data types. Route definitions are code, not data.

---

## API / Interface Contract

```tsx
// Route structure (createBrowserRouter or JSX routes)
// /            → LandingPage           (public; redirects to /files if authed)
// /files       → ProtectedLayout > FilesPage
// *            → NotFoundPage

// src/components/ProtectedLayout.tsx
// Reads useAuth(); returns <Navigate to="/" /> when unauthenticated,
// loading indicator when loading, <Outlet /> when authenticated.
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/
├── main.tsx                       ← router + provider composition
├── App.tsx                        ← REMOVED or reduced to route definitions
├── routes/                        ← NEW: page-level route components (default exports allowed)
│   ├── LandingPage.tsx
│   ├── FilesPage.tsx
│   └── NotFoundPage.tsx
└── components/
    ├── Header.tsx                 ← from SPEC-007, rendered in layouts
    ├── ProtectedLayout.tsx        ← NEW: auth guard + Outlet
    └── ProtectedLayout.test.tsx
```

> Convention note: page-level route components are the sanctioned exception to the no-default-exports rule (per CLAUDE.md).

## Implementation Phases

### Phase 1: Router and pages (no gating)

- Add `react-router-dom`; record the dependency in CLAUDE.md
- Create routes/pages; move file browser to `/files` (FR-001, FR-002 partial, FR-005)

#### Checkpoint

`npm run dev`: `/` shows the landing page, `/files` shows the working file browser (not yet gated), unknown URL shows not-found. All existing tests pass (`npm run test`).

### Phase 2: Guard and return path

- Implement `ProtectedLayout` with loading/unauthenticated/authenticated branches (FR-003)
- Implement post-login return path (FR-004); redirect authed users off `/`
- Add `ProtectedLayout.test.tsx` covering all three auth states

#### Checkpoint

Manual: signed out, navigating to `/files` redirects to `/`; signing in returns to `/files`; refresh on `/files` while signed in stays (after loading state); sign out on `/files` redirects to `/`. Verify in the network tab that no S3 request fires while signed out. `npm run test` and `npm run lint` pass. After deploy, refresh `/files` on CloudFront URL serves the app.

## Open Questions

- [x] **Resolved (2026-06-10):** logout lands on the plain landing page, no confirmation message.
- [x] **Resolved (2026-06-10):** return path is stored in `sessionStorage` (committed in FR-004).
