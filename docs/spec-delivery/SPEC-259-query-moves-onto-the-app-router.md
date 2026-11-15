# Completed Spec — SPEC-259: Query Moves Onto the App Router

The move landed as one PR, #986 (`9d72bf65`), on 2026-11-14. The live checks ran on the deployed
image in the small hours of 2026-11-15 (`docs/testing/sessions.md`). A tooling fix it found landed
ahead of it as #982. Nothing changes for a user except Next's own behaviour on an App Router page:
arriving at Query from another page now fetches the page from the server and scrolls to the top.

## What was completed?

- **The page.** `src/app/(signed-in)/query/page.tsx` serves `/query`. It reaches `QueryView` only
  through `next/dynamic` with `ssr: false`, has no loading fallback and takes no props. The view, the
  workspace, the editor and the run engine are unchanged, and the runs still live in the shell.
- **The record.** `src/lib/navigation/areas/query.ts` says `'app'`, so the catch-all's table no
  longer builds Query's route. Neither `routes/table.tsx` nor `routes/areas/query.tsx` changed.
- **The tests**, in `src/routes/areas/query.test.tsx`. Every `renderApp` call names Query's router,
  because `renderApp` serves every area from the catch-all unless a test names it.
  - `/query` renders from its page, and a missing page fails on the catch-all's 404.
  - Arriving from a catch-all page fetches `/query`, which only the App Router's page does.
  - *Open in Query* opens one tab, under `StrictMode`, from Explore served by either router, and
    nothing more on Back and Forward.
  - A refresh link's dismissal is a native replace that neither fetches nor remounts the page.
- **`StrictMode` through `renderApp`.** The harness renders none. The *Open in Query* test passes an
  `auth` component that places `StrictMode` above the auth context. React doubles the effects of a
  fiber placed under it, so the Query page a navigation mounts has its receiver's effect doubled:
  with the receiver's `location.key` guard deleted, both rows find three tabs, and with the wrapper's
  `StrictMode` swapped for a fragment, they find two again.

### Deliberate deviations

- **The web tier was neither switched on nor off by this build.** It was already on, held by SPEC-260
  and SPEC-261 under the arc's holder list (a notes file the arc's sessions share, outside the
  repository), and SPEC-261 still held it when these checks finished.
  FR-003's "switches it on, and off again" became "adds a holder line, and removes it".
- **The *Open in Query* test's App Router row renders Explore's page from disk.** SPEC-260 landed
  first (#985), so the `pages` stand-in the criterion allowed "while it has none on disk" was dropped
  at the rebase.
- **FR-001's second criterion was amended in the build PR.** SPEC-256's completion (#983) made
  `renderApp` serve every area from the catch-all unless named. "The inherited split tests pass
  unchanged" would then have kept testing the catch-all, so every call names Query's router `'app'`.

## What changed from earlier specs?

- **Vitest's module cache is off** (#982, before the move). Vitest 5 skips caching a module that
  contains the literal `import.meta.glob(`, but `src/test/appRouter.tsx`'s typed glob slipped past
  that, and its page list stayed frozen. The new page was invisible to `renderApp` until the cache
  was cleared. The decision is
  `docs/decisions/gates-and-tests/vitests-module-cache-stays-off-because-it-freezes-a-globs-file-list.md`.

## Verification

- **Local gates, by exit code, on the rebased branch:** format, ESLint, `npm run build` (listing
  `ƒ /query`), `check:bundle`, the full Vitest suite, ruff, mypy, pytest, `validate_docs.py` and the
  `ci.yml` validators.
- **`next start` and the standalone `server.js`** each answered `/query` with 200 and HTML that
  carried no workspace markup.
- **The diff's execution review** planted the page, record, provider, receiver and seam mutants, and
  each went red except a `loading` fallback, which the shared page sweep did not check then; #987
  has since added that check (any `next/dynamic` option beyond `{ssr: false}`). It also flipped all six neighbouring areas to `'app'` with no
  change of verdict.
- **Live, on image `a80c9b28`:** every FR-003 check and SPEC-256's cross-router rows on Query's page.
  `docs/testing/e2e.md` §4.3 carries the steps, under *On the App Router*.
