# Completed Spec — SPEC-035: Tabbed Dashboard + Query Workspace UI

## What was completed?

The portal's second surface: a `/query` workspace where a user writes SQL in a Monaco
editor against their own Glue database, runs it on the shared Athena workgroup, watches
status, and reads results — presentation/interaction only, wired entirely to the SPEC-034
data layer. Built to `docs/design/query-workspace.html` + design-system §6. Full public
surface is in `docs/component-inventory.md` (Query feature → Workspace UI + `PrimaryNav`).

- **Primary tabs (FR-001):** `PrimaryNav` (Files | Query underline tabs) in `Header`,
  authenticated-only, `NavLink`-driven.
- **Route shell (FR-002):** `/query` under `ProtectedLayout` → lazy `QueryPage` →
  `QueryWorkspace`. The protected **left rail is now page-owned** (`AppShell` is a bare flex
  row): `FilesPage` renders `Sidebar`, the workspace renders `SchemaBrowser`. `usePageTitle('Query')`.
- **Monaco editor (FR-003):** `SqlEditor` — self-hosted `@monaco-editor/react` + `monaco-editor`
  (Vite `?worker`, no CDN), `sql` language, token theme mapped to design colors, ⌘⏎ Run,
  `insertAtCursor` via ref. Lazy at both the editor and the route level.
- **Run/Stop (FR-004):** `runQuery`/`stopQuery`; ⌘⏎; disabled-when-empty/in-flight; errors via
  `Banner`. History appended at submit, terminal status/stats patched on completion.
- **Status (FR-005):** `QueryStatusBar` live region — running spinner + elapsed/scanned +
  indeterminate bar; succeeded rows/scanned/duration + Download CSV (`getResultCsvUrl`);
  failed → danger `Banner` (`stateChangeReason`); cancelled note.
- **Results (FR-006):** `QueryResultsTable` reusing the file-table treatment (dynamic columns +
  type, horizontal scroll, empty state, Load more via the infinite hook).
- **Schema (FR-007):** `SchemaBrowser` via `useSchema` — expandable tables/columns,
  click-to-insert, loading/empty/"setting up" (DB not provisioned)/error states; `invalidateSchema`
  after a successful DDL run.
- Monaco deps recorded in CLAUDE.md tech-stack.

### Deliberate deviations

- **Results pagination = "Load more"** (the SPEC-034 infinite hook), not yet a 20-row Prev/Next
  pager. SPEC-035 FR-006 says build for **SPEC-038**'s pager (still Draft); the table is
  structured so SPEC-038 swaps the pager without touching the data wiring. Matches the mockup.
- **Schema rail:** clicking a table toggles its columns (chevron); clicking a **column** inserts
  it (matches the realized mockup). The History/Format toolbar buttons are SPEC-036's (history
  panel) — omitted here rather than shipping dead controls.

## What changed from earlier specs?

- **`ProtectedLayout` `AppShell`** no longer renders `Sidebar` — the left rail is page-owned now
  (so the schema browser, which needs editor wiring, can live on the Query route). `FilesPage`
  renders its own `Sidebar`; no behavior change to the file browser.
- **`Header`** renders `PrimaryNav` when authenticated.
- **`App.tsx`** adds the lazy `/query` route.

## Verification

`npm run lint`, `npm run test` (**326 pass** — workspace integration test + `SchemaBrowser`,
`QueryStatusBar`, `QueryResultsTable`, `query.format` unit tests), and `tsc -b && vite build`
all green. **Build-gate (FR-003) confirmed:** the main bundle stays ~739 kB (≈ pre-Monaco
baseline); Monaco (`editor.api2` 3.6 MB + `SqlEditor` 111 kB + per-language chunks) and the
Athena/Glue SDK clients are in async chunks loaded only on `/query` — resolves the Monaco open
question (Monaco stays).

**Deferred (auth-gated, no local Cognito session):** the live browser checkpoint — signed-in,
tabs visible + deep-link/back-forward, Monaco syntax highlighting on screen, a real SELECT →
running → results table + CSV, a `CREATE EXTERNAL TABLE` refreshing the schema, Stop cancelling.
Exercised once a signed-in user drives it against the already-deployed Athena/Glue stack.
