# Completed Spec — SPEC-036: Query History Panel UI

## What was completed?

The presentation layer over the SPEC-034 per-user history store, integrated into the
SPEC-035 query workspace: a right slide-over drawer listing the user's past queries
(newest-first) with re-open and re-run. Read-only — no delete/clear (v1 decision). Built to
the history drawer in `docs/design/query-workspace.html` + design-system §6. Public surface in
`apps/portal/info/component-inventory/INDEX.md` (Query feature → Workspace UI).

- **`QueryHistoryPanel.tsx` (FR-001/002):** right slide-over drawer (mirrors the file-browser
  `UploadDrawer` pattern — scrim, Escape/click close), titled "Query history". Lists
  `useQueryHistory(username)` newest-first; loading / friendly empty / `Banner` error states.
- **`QueryHistoryRow.tsx`:** status badge (success/danger/neutral + dot + text, never
  color-only), relative time (`formatRelativeTime`, absolute on `title`), single-line mono SQL
  preview, scanned/duration stats, **Open** / **Re-run** actions.
- **Re-open (FR-003):** loads the entry's SQL into the editor (direct replace), focuses it
  (new `SqlEditorHandle.focus()`), closes the drawer — no auto-run.
- **Re-run (FR-004):** loads + submits via the shared `submit(sqlText)` path (a new history
  entry is appended); disabled while a query is in flight.
- **Status sync (FR-005):** the panel and workspace share the `queryKeys.history(username)`
  cache, so an in-session entry reflects its terminal status (via `updateQueryHistoryEntry`'s
  cache seed) without reload. A stale non-terminal entry (tab closed mid-run) renders a neutral
  **Unknown** badge, never a false "Running".
- **Workspace wiring:** added the **History** toolbar button (deferred from SPEC-035), the drawer
  open state, and the re-open/re-run handlers; refactored the run path into `submit(sqlText)`.
- `query.format.ts` gains `formatRelativeTime(iso, now?)`.

No new types (consumes SPEC-034 `QueryHistory`/`QueryHistoryEntry`); no data-layer/IAM change.

## What changed from earlier specs?

- **`QueryWorkspace` (SPEC-035)** — run logic extracted to `submit(sqlText)`; History button +
  history drawer added; `SqlEditor` handle gained `focus()`. No behavior change to the run/results
  paths beyond the shared `submit`.

## Verification

`npm run lint`, `npm run test` (**338 pass** — `QueryHistoryRow`, `QueryHistoryPanel`,
`formatRelativeTime`, and a workspace re-run-from-panel test), and `tsc -b && vite build` all
green; main bundle unchanged (~739 kB), the panel rides in the lazy `/query` chunk.

**Deferred (auth-gated, no local Cognito session):** the live browser check — opening the drawer
with real prior history, re-opening SQL into Monaco, re-running, and the in-session status badge
flipping to terminal without reload. Verified once a signed-in user drives it.

---

_Closes the analytics arc (SPEC-032→036): the in-app Athena/Glue/Lake Formation query workspace
is feature-complete (pending the deploy/auth-gated live walkthrough)._
