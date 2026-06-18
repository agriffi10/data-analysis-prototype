# Spec: Tabbed Dashboard + Query Workspace UI

**ID:** SPEC-035
**Status:** Completed
**Last Updated:** 2026-06-18
**Depends On:** SPEC-008 (auth-gated layout + react-router), SPEC-023 (app shell), SPEC-028 (shared UI primitives), SPEC-034 (query engine data layer), SPEC-033 (per-user database exists)

> **Design:** This spec is design-led. Build it to `docs/design/query-workspace.html` (the query-workspace mockup) and the additions in `docs/design/design-system.md` §6 (Data analysis surface). Where this spec and the design disagree, the design system wins for visuals; this spec wins for behavior/data wiring.

## Overview

Turn the authenticated portal into a two-surface dashboard: the existing file browser and a new **Query** workspace, switched between by a primary tab navigation (Files | Query). The Query workspace is where a user writes SQL against their own Glue database with a syntax-highlighting editor (Monaco), runs it against the shared Athena workgroup, watches execution status, and reads results in a table. It is wired entirely to the SPEC-034 data layer — this spec is presentation + interaction only. Per the design system's forward-looking §6, the workspace reuses existing tokens and the file-table component rather than introducing a second visual language.

## Scope

### In Scope

- **Primary tab navigation** (Files | Query) in the authenticated shell, driving routes `/files` and `/query`; active-tab styling per the design
- New `/query` protected route → `QueryWorkspace` (route-level component, default export per conventions)
- **Monaco SQL editor** (new dependency) with SQL syntax highlighting, mounted in the workspace; Run + Stop controls
- **Schema browser** panel listing the user's database + tables/columns (from `useSchema`), with click-to-insert table/column names into the editor
- **Run / status / results** flow: submit via `useQueryExecution`, show live status (queued/running with elapsed time + data scanned), render the results table via `useQueryResults`, expose "Download CSV"
- **DDL + write support**: `CREATE TABLE`/`DROP TABLE`/`ALTER`, and **writes** (`CREATE TABLE AS SELECT`, `INSERT INTO`) all run through the same Run path (writes are enabled — SPEC-033 grants `INSERT`); on a successful schema-changing statement the schema browser refreshes (invalidate `useSchema`). A comment notes CTAS/INSERT output lands in the user's own prefix (visible/deletable in the file browser), separate from the protected `athenaresults/` results
- Empty/loading/error states: no database yet (ties to SPEC-033 backfill), empty results, failed query (show `stateChangeReason`), no tables yet (guidance to run `CREATE EXTERNAL TABLE`)
- History append on run (calls SPEC-034 `appendQueryHistory`); the history **panel UI** is SPEC-036, but this spec records entries
- `usePageTitle('Query')` (SPEC-031)

### Out of Scope

- The query history panel UI (SPEC-036) — this spec only writes history entries
- Result charting/visualization (future)
- Editor autocomplete/IntelliSense against the live schema (Monaco ships basic SQL tokenization; schema-aware completion is a future enhancement — note it)
- Multi-statement/multi-tab editor sessions (single editor pane in v1)
- Any data-layer change (all in SPEC-034) or IAM/infra change (SPEC-032)

---

## Functional Requirements

### FR-001: Primary Tab Navigation

#### Description:

A persistent primary navigation lets the user switch between the file browser and the query workspace. Placement and styling per the design (`design-system.md` §6 + the mockup).

#### Acceptance Criteria:

- [ ] Two primary destinations — **Files** (`/files`) and **Query** (`/query`) — rendered as tabs in the authenticated shell; the active tab uses the design's active treatment (`accent`/`accent-soft` per §6, matching the sidebar active pattern), inactive tabs are muted with hover
- [ ] Implemented with react-router `NavLink` (or equivalent) so active state follows the URL; deep-linking to `/query` and browser back/forward work
- [ ] Reconcile with the existing `Sidebar` ("My Files"): either the tabs live in/replace the relevant sidebar section, or the sidebar gains a "Query" entry — the design file is authoritative on placement; this spec requires only that both surfaces are reachable and the active one is unambiguous
- [ ] Tabs render only in the authenticated (`ProtectedLayout`) shell, not on the landing page
- [ ] Keyboard accessible (focusable, Enter/Space activate) with a visible focus ring (design system §7)

### FR-002: Query Route + Workspace Shell

#### Acceptance Criteria:

- [ ] `/query` added under `ProtectedLayout` in `App.tsx`; element is `QueryWorkspace` (route component, default export)
- [ ] `QueryWorkspace` lays out: schema browser (left), editor + run controls (top/center), results (below) — proportions per the mockup
- [ ] Reads the signed-in user's `username` from `useAuth()`/`getCurrentUser()` and uses it **directly** as the database name — they are equal by construction (SPEC-033 FR-001 catalog-safe username rule), so there is no derivation/sanitization and no drift risk
- [ ] `usePageTitle('Query')` sets the document title (SPEC-031)
- [ ] If the user's database does not exist yet (`getDatabase` not-found), renders a friendly empty/"setting up" state, not an error (ties to SPEC-033 backfill)

### FR-003: Monaco SQL Editor

#### Description:

A syntax-highlighting SQL editor as the query input.

#### Acceptance Criteria:

- [ ] Monaco editor integrated (dependency added to `apps/portal/package.json` and the CLAUDE.md tech-stack table); language set to `sql`, theme tuned to the design tokens (or a close built-in), `surface-2` gutter per §6
- [ ] Editor is controlled/uncontrolled per the integration's best practice; current SQL text is readable for Run; supports multi-line, undo/redo, find (Monaco built-ins)
- [ ] Bundle impact is contained: Monaco is loaded for the Query route only (lazy/dynamic import + `React.lazy`/route-level code-split) so the Files route and landing page don't pay for it — verify in the build output. A comment documents the Vite worker setup Monaco requires
- [ ] Editor is keyboard accessible and has a visible focus treatment consistent with the design
- [ ] A sensible default/placeholder query or empty editor per the design

### FR-004: Run & Stop

#### Acceptance Criteria:

- [ ] A primary **Run** button (design system primary, one-per-context) submits the editor's SQL via SPEC-034 `runQuery({ sql, database, username })`; disabled while a query is in flight and when the editor is empty
- [ ] While running, a **Stop** control calls `stopQuery`; status reflects `CANCELLED`
- [ ] On submit, an entry is appended to history (`appendQueryHistory`) per SPEC-034 FR-007 (status updated on completion)
- [ ] Cmd/Ctrl+Enter in the editor triggers Run (documented shortcut)
- [ ] `runQuery` returning a `ServiceResult` error (no creds, denied, malformed) surfaces via a `Banner` (design system) — never an uncaught throw

### FR-005: Execution Status

#### Acceptance Criteria:

- [ ] While `useQueryExecution` polls, the UI shows state (`QUEUED`/`RUNNING`) with elapsed time and, when available, data scanned — styled per the mockup (accent progress/indeterminate treatment, never color-only — pair with text)
- [ ] `SUCCEEDED` reveals the results table (FR-006); `FAILED` shows the `stateChangeReason` in a `danger` `Banner`; `CANCELLED` shows a neutral note
- [ ] The status region is an accessible live region (announces terminal state)

### FR-006: Results Table

#### Description:

Render results reusing the existing file-table visual language (design system §6: "reuse the table component for query results").

#### Acceptance Criteria:

- [ ] Columns from `QueryResultPage.columns` (name + type pill using the existing neutral `Badge`/pill); rows from `QueryResultPage.rows`
- [ ] Container matches the file table (`surface`, `border`, `rounded-lg`, header on `surface-2`, uppercase `text-xs` column labels, 48px-ish rows, hover) — reuse/share styling rather than a parallel implementation
- [ ] Results pagination is delivered by **SPEC-038** as a **20-row Prev/Next pager** (replace, not append) — this supersedes an earlier "Load more" idea here; build the results table to accept the SPEC-038 pager
- [ ] **Download CSV** action uses SPEC-034 `getResultCsvUrl` (presigned) to save the raw result object
- [ ] Empty result set (e.g. successful DDL or zero-row SELECT) renders a friendly empty state, not an error
- [ ] Wide result sets scroll horizontally without breaking the shell layout

### FR-007: Schema Browser

#### Acceptance Criteria:

- [ ] Lists the user's database name and its tables (from `useSchema`); expanding a table shows its columns (name + type)
- [ ] Clicking a table or column inserts its name into the editor at the cursor (convenience; per the mockup)
- [ ] Loading, empty ("No tables yet — create one with `CREATE EXTERNAL TABLE …`"), and error/denied states render per the design (denied should never happen for the user's own DB, but is handled defensively)
- [ ] After a successful DDL run (FR-004), the schema list refreshes (invalidate `useSchema` via the SPEC-034 helper)

---

## Data Model

No new types — consumes SPEC-034's `query.types.ts`. A small UI-state reducer (current query execution id, editor text) may live in the feature; document any context in `query.types.ts`.

## File & Folder Structure

```
apps/portal/src/
├── App.tsx                                  ← + /query route under ProtectedLayout
├── components/
│   └── PrimaryNav.tsx (or Sidebar.tsx edit) ← Files | Query tab navigation (per design placement)
├── routes/
│   └── QueryPage.tsx                        ← NEW route component (default export) → renders QueryWorkspace
└── features/query/
    ├── QueryWorkspace.tsx                   ← top-level workspace composition
    ├── QueryWorkspace.test.tsx
    ├── SqlEditor.tsx                        ← Monaco wrapper (lazy-loaded)
    ├── SchemaBrowser.tsx
    ├── QueryResultsTable.tsx
    ├── QueryStatusBar.tsx
    └── (consumes SPEC-034 hooks/services/types)
```

## Implementation Phases

### Phase 1: Tab navigation + query route shell + Monaco editor

- FR-001, FR-002, FR-003

#### Checkpoint

`npm run dev`: a Files | Query tab nav appears in the authenticated shell; clicking Query routes to `/query` and renders the workspace with a working Monaco SQL editor (syntax highlighting); deep-link + back/forward work; the build output confirms Monaco is not in the Files/landing chunks (code-split). `npm run test`/`lint` pass.

### Phase 2: Run/stop/status + results + schema

- FR-004, FR-005, FR-006, FR-007

#### Checkpoint

Signed in with a provisioned database: a `SELECT` runs, shows running status, then a results table with type pills, pagination, and CSV download; a `CREATE EXTERNAL TABLE` over the user's own S3 prefix succeeds and the schema browser then lists the new table; a failing query shows its reason in a danger banner; Stop cancels a long query. History entries are written (verified via SPEC-034 `getQueryHistory`). Matches `docs/design/query-workspace.html`. Tests/lint pass.

## Open Questions

- [x] **Resolved (2026-06-17):** the database name **equals the username** (SPEC-033 FR-001 catalog-safe rule), so the app uses `username` directly — no derivation, no drift, no stored mapping needed.
- [x] **Resolved (2026-06-17):** the primary nav is a **horizontal tab strip in the topbar** (Files | Query), per `docs/design/query-workspace.html` — active tab is `accent-text` with a 2px `accent` underline. The schema browser occupies the left sidebar slot on the Query route. (See design-system.md §6.)
- [x] **Resolved (2026-06-18, build verified):** Monaco **stays** (no CodeMirror fallback). Self-hosted via `@monaco-editor/react` + bundled `monaco-editor` (Vite `?worker`, no CDN). Both the editor (`React.lazy`) and the whole `/query` route are lazy-loaded, so the main bundle stays at ~739 kB (≈ pre-Monaco baseline) and Monaco (`editor.api2` 3.6 MB + `SqlEditor` 111 kB + per-language chunks) + the Athena/Glue SDK clients land in async chunks loaded only on the Query route. Confirmed in the build output.
- [x] **Resolved:** results table **reuses the file-table** component/styling (design system §6); no second table implementation.
