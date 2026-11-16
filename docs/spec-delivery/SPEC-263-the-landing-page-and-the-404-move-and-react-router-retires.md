# Completed Spec — SPEC-263: The Landing Page and the 404 Move, and React Router Retires

## What was completed?

- **Two App Router pages.** `src/app/page.tsx` (the landing page) and `src/app/not-found.tsx` (the 404)
  each reach their view through `next/dynamic` with `ssr: false` and title themselves as they mount.
  An address no page serves answers the not-found page under a **404**, where the catch-all
  answered 200.
- **React Router is gone**, along with the optional catch-all `src/app/[[...slug]]/`,
  `src/routes/table.tsx`, `CatchAllRouter`, the lint pattern and its two exemption clauses, and the
  views' static boundary keys. `src/test/reactRouterSweep.test.ts` (a source sweep with no exempt
  place, plus a manifest check) keeps it out.
- **The seam on Next's router alone** (`src/lib/navigation/`).
  - A navigation is native only when it keeps the committed pathname.
  - `useParams` is Next's, decoded once.
  - `matchPath` is the seam's own segment walk.
  - The area records lose `router`, and `routerFor` and `AreaRecordsContext` go.
- **One router in the harness.**
  - `renderWithProviders`' `path` and `routes` run on the seam's matcher, with params handed to the
    stand-in raw.
  - `renderApp` loses `routers` and renders `not-found.tsx` at an unmatched address.
  - The `next/navigation` stand-in models a tenth behaviour, `documentLoads()`.
- **A guard ahead of Next.** `apps/portal/server-guard.cjs`, which the image's `CMD` now starts,
  answers each of these with 400, the security headers, the lockdown policy and one log line naming
  the method:
  - a malformed percent-escape;
  - a request target that is not a path;
  - every WebSocket upgrade.
- **The image matrix.** It asserts the 404s, the guard's rows and a 1 GB declaration to a malformed
  path answered at once.

### Deliberate deviations

- **Taken from the 263 inbox, beyond the spec as drafted.** The spec was amended in #1018 to say so.
  - The guard refuses a target that does not start with `/`, which flips the absolute-form rows from
    an off-site 308 to 400.
  - It refuses every upgrade.
  - The live guard probe reads the policy or the log line, not the status alone.
- **Rejected: making the gate stop decoding a static segment.** A gate that claims more than Next
  serves fails safe.
- **Rejected: removing the per-view boundaries.** They are out of scope.
- **A navigation to a path no page serves is a document load** (measured under `next start`). The
  stand-in models it, so two tests changed:
  - The announcement test for `/nope` asserts the document load.
  - The 404's Back test asserts the document reloads.
  The spec's tenth stand-in behaviour records it.
- **The early-close residual is accepted.** A refused bodied request is reset unread, so behind the
  balancer a crafted one may see a 502 (`docs/security-baseline.md`).

## What changed from earlier specs?

- **SPEC-255:**
  - The image starts the guard rather than `server.js`.
  - The matrix's catch-all 200 rows became 404.
  - Its malformed-escape 500 rows and absolute-form 308 rows became the guard's 400s.
- **SPEC-256:**
  - The seam's choice of router, `CatchAllRouter`, `routerFor`, the records' `router` field,
    `CATCH_ALL_RECORDS` and `renderApp`'s `routers` are gone.
  - The decision `browser/react-router-in-the-catch-all-is-a-matcher-the-navigation-seam-feeds.md`
    was rewritten in place.
- **SPEC-258 to 261:** every area test that named a router runs on the App Router alone. The
  cross-router tests were retargeted, or deleted where they duplicated another.
- **The route-announcer fix:** the catch-all's page name went. The landing page and the 404 call
  `usePageTitleOnMount` themselves.

## Verification

- **Locally, by exit code:** format, lint, `tsc -b`, the full Vitest suite, the analyzed build,
  `check:pages`, `check:bundle`, pytest, mypy and every `ci.yml` validator.
- **Images:**
  - The image matrix passed 351 of 351 checks.
  - With `CMD` on `server.js`, 35 rows failed.
- **Mutation checks:** each criterion's mutant was observed red.
- **Test names:** diffed from the runner on both refs (#1018).
- **Live:** FR-006 ran on `724c2713` in `docs/testing/sessions.md` (2026-11-16) and passed. The rows
  are folded into `docs/testing/e2e.md`.
