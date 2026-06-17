# Completed Spec - Auth-Gated Layout — Protect the S3 Interface

## What was completed from this spec?

Client-side routing (react-router v7, library mode) and a layered layout that
gates the S3 file browser behind authentication. Unauthenticated visitors get a
public landing page and are never shown the file browser; authenticated users
land on `/files`. This is a UX gate, not a security boundary — real enforcement
arrives with scoped credentials (SPEC-011) — but it establishes the route
structure all future pages build on.

- `react-router-dom@^7.17.0` added to `apps/portal` (recorded in the CLAUDE.md tech stack table).
- **Routing** (`src/main.tsx`, `src/App.tsx`): `<BrowserRouter>` nests inside `<AuthProvider>` so route guards can call `useAuth`. `App.tsx` is reduced to `<Routes>` definitions.
- **Layered layouts** (FR-003):
  - `src/components/RootLayout.tsx` — generalized layout rendering the auth-aware `Header` (SPEC-007) plus `<Outlet />` in a `flex min-h-screen flex-col` shell. Wraps **every** route, so the header appears on the landing, files, and not-found pages alike.
  - `src/components/ProtectedLayout.tsx` — gate-only sub-layout nested inside `RootLayout` (renders no chrome of its own). `loading` → a `role="status"` indicator (the `<Outlet />`, and therefore `FileBrowser` + any S3 call, is never mounted — no flash); `unauthenticated` → stores the attempted path then `<Navigate to="/" replace />`; `authenticated` → `<Outlet />`.
- **Pages** (`src/routes/`, default exports — the sanctioned exception to the no-default-exports rule):
  - `LandingPage.tsx` — public `/`: app name, one-line description, and a "Sign in" CTA wired to `signIn()`. Makes no S3 calls. Authenticated visitors are redirected to the stored return path or `/files` (FR-002 + FR-004).
  - `FilesPage.tsx` — `/files`: the file-browser rendering moved verbatim from the old `App.tsx`, including the env-driven bucket/prefix wiring and the missing-`VITE_S3_BUCKET_NAME` config-error state (FR-005). Still the SPEC-002 test bucket.
  - `NotFoundPage.tsx` — `*` catch-all with a link back to `/` (FR-001).
- **Return path** (`src/lib/returnPath.ts`, FR-004): `setReturnPath`/`takeReturnPath` backed by `sessionStorage` (survives the full-page OAuth redirect, which in-memory router state would not). All access is try/guarded so private-browsing failures fall back to the default route.
- **Tests**: `components/RootLayout.test.tsx` (1 — shared header + child render) and `components/ProtectedLayout.test.tsx` (4 — loading shows indicator and never mounts protected content; unauthenticated redirects to `/` and stores the return path; authenticated renders the child).

### Route structure

```
RootLayout              ← Header on every page + <Outlet/>
  /        LandingPage   (public; redirects to /files when authed)
  ProtectedLayout        ← auth gate only (no chrome)
    /files FilesPage
  *        NotFoundPage
```

### Design note — header on the landing page is intentional

`RootLayout` renders the `Header` everywhere, so an unauthenticated visitor on
`/` sees a "Sign in" button in the header *and* the hero "Sign in" CTA. This is
deliberate: sign-in should be available the moment a user arrives.

### Verification

- `tsc -b` clean, `npm run lint` clean, `npm run build` succeeds, `npm run test` → **52 passed** (5 new; all existing FileBrowser/auth tests unmodified, per FR-005).
- Manual Phase 2 checkpoint against the live SPEC-006 pool: signed out → `/files` redirects to `/` with no S3 request firing; sign in returns to `/files`; refresh on `/files` stays after the loading indicator (no content flash); sign out from `/files` redirects to `/`.

## What has changed?

- **`src/App.tsx`** — restructured from an app shell (which rendered `Header` + the file browser directly, delivered in SPEC-007) into `<Routes>` route definitions. The file-browser rendering and its config-error state moved to `routes/FilesPage.tsx`; the `Header` moved to `components/RootLayout.tsx`. No behavior change to the file browser itself.
- **`src/main.tsx`** — added `<BrowserRouter>` between `<AuthProvider>` and `<App>`. (SPEC-007 had deliberately placed `AuthProvider` outside any future router for exactly this.)
- **`src/components/Header.tsx`** — unchanged; now rendered by `RootLayout` rather than `App`.
- **CLAUDE.md** — SPEC-008 marked Completed in the Active Specs table (the tech stack table already listed react-router-dom v7 as introduced by this spec).

### Follow-ups / notes

- No new `VITE_*` variables.
- Direct navigation / refresh on `/files` relies on the CloudFront 403/404 → `index.html` rewrite from SPEC-003 (no infra change). Verified locally via the Vite dev server; verify on the deployed CloudFront URL when the app is next deployed.
- Per-user S3 scoping is still deferred — `/files` browses the SPEC-002 test bucket. The gate is UX-only until scoped credentials land (SPEC-011).

## Later changes

- **Authenticated shell gained a left nav sidebar (PR #56).** `ProtectedLayout` now wraps the
  routed content in an `AppShell` (a `flex` row: `Sidebar` + content column) on its authenticated
  and dev-bypass branches; the `loading` and `unauthenticated` branches are unchanged. The new
  `components/Sidebar.tsx` renders the design's 248px "My Files" rail (the user-space entry links
  to `/files`); the Shared Connections section is intentionally omitted until that feature exists.
  Hidden below `md` so the file browser fills narrow viewports. (See also SPEC-023, which had
  deferred the sidebar.)
