# Completed Spec — SPEC-256: The App Router Owns the Shell, and Navigation Goes Through One Seam

The build landed as one PR, #977 (`a05098b9`), on 2026-11-14, with the decisions it rewrote and the
docs that would have gone stale on its merge. The live checks ran the same day on the deployed image,
with the web tier on through CI; the tier was switched off afterwards through the repository variable
and Deploy Infrastructure. Nothing changes for a user except one thing: while an upload is
unfinished, the browser asks before the page is reloaded or closed.

## What was completed?

- **The boot and the shell in the root layout.** `src/app/layout.tsx` renders `PortalMount`, which
  loads `PortalBoot` client-only; the boot renders `AppFrame` (the providers, the query client made
  per mount through `createQueryClient`) around `AppChrome`, which decides by the address, through the
  area records, whether a page is public or goes inside `ProtectedLayout` and the shell. `App.tsx` and
  `AppRoot.tsx` are gone.
- **The navigation seam**, `src/lib/navigation/`: the hooks, `Link`, `NavLink`, `Navigate`,
  `matchPath`, the one adapter `NavigationProvider` over `next/navigation`, and `CatchAllRouter`
  feeding react-router inside the catch-all. Its rules and the eight Next behaviours they rest on are
  `docs/decisions/browser/react-router-in-the-catch-all-is-a-matcher-the-navigation-seam-feeds.md`.
- **One module per area.** Views in `src/routes/areas/<area>.tsx`, records in
  `src/lib/navigation/areas/<area>.ts`, the table in `src/routes/table.tsx` building routes only for
  areas the catch-all serves, and a record-and-page guard. The four cross-area test files split into
  `routes/table.test.tsx` and `routes/areas/<area>.test.tsx`.
- **Tests under either router.** `src/test/nextNavigation.ts` (Vitest's `next/navigation`, aliased in
  `vite.config.ts`), `renderApp` in `src/test/appRouter.tsx`, and `renderWithProviders` on the seam
  with `path`, `routes` and `location()`.
- **The leave guard.** `UnloadGuard` in the shell cancels `beforeunload` while an upload is unfinished;
  `signOut` disarms it first, and both download helpers click through `withoutLeaveGuard`.
- **The fence.** `react-router` is refused everywhere but the seam, the table and `src/test/`, held by
  the lint rule, `eslintConfigShape.test.ts`, `navigationFence.test.ts` and `reactRouterSweep.test.ts`.

### Deliberate deviations

- **The path-to-view map lives in `src/routes/table.tsx`**, not in each area module, so an area module
  exports components only; a move still edits neither file.
- **The gate and `linkFlags` match the decoded path**, as the route table does (`/fil%65s` is Files),
  and the seam checks a target's origin as written and once resolved, with doubled slashes collapsed
  as react-router collapses them. Both came from the diff reviews.
- **Downloads run with the leave guard disarmed**, because Chrome raises `beforeunload` for a
  navigation to a presigned download URL (measured in review). The spec's leave rule named reloads and
  closed tabs only.
- **FR-006's last criterion was amended**: removing `QueryRunsProvider` from the shell is the mutant
  that reddens the Query runs proof; adding it to the harness cannot, since the shell's provider stays
  the nearest.

### Fixed after the merge

The area moves found three tests that read the production records where they meant a fixed tree:
the record-and-page guard's planted cases, a harness test that reached a catch-all page at `/files`,
and the chunk-failure test, which needs Query and Explore in one react-router slot. A move's flip
turned the first two red and left the third green while it stopped testing anything. So the
completion change made the default a fixture: `renderApp` and `renderWithProviders` serve every area
from the catch-all (`CATCH_ALL_RECORDS`) unless a test names an area's router, `routers:
'as-recorded'` follows the production records, and the guard's planted cases run on fixed records and
pages, with only "agree on the tree as it stands" reading the disk. With Files flipped and its page
added, the whole suite gives the same result as before the flip.

## What changed from earlier specs?

- SPEC-255's `PortalMount` moved from the catch-all's directory up to `src/app/`, and the catch-all's
  page now renders `CatchAllMount`; 255's catch-all sweep is now `src/app/pageSweep.test.ts`, over
  every page.
- `lib/queryClient.ts` exports a factory instead of an instance; `renderWithProviders` lost
  `browserRouter`; hand-off tests read `location().state`, not `window.history.state`.
- Two Python link guards (`test_notify_focommon.py`, `test_file_send_notify.py`) read the Files path
  from its area record instead of `App.tsx`.

## Verification

Every gate by exit code on the rebased head, three diff reviews in different frames, a planted defect
for every guard and review fix, and the production build driven in Chrome under `next start` (28
checks, seven of them red with a path `key` planted). Live on the tier: the search-only, skip-link and
spaced-folder checks of FR-003, and FR-002's upload survival and sign-out; the reload prompt itself is
owed (`docs/testing/owed.md`), and the evidence is in `docs/testing/sessions.md`.
