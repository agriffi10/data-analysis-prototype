# Spec: Schema Browser — Table Options Menu

**ID:** SPEC-044
**Status:** Draft
**Last Updated:** 2026-06-19
**Depends On:** SPEC-035 (schema browser + query workspace), SPEC-041 (query tabs + `openTab` named-tab API + tab-limit dialog), SPEC-034 (Glue `location` on `GlueTableSummary`, Athena `runQuery`/results, history store), SPEC-013 (authenticated user-space file browser), SPEC-026 (dialog pattern), SPEC-028 (Button primitive)

> **Design:** Needs a design pass (done after this spec, with SPEC-043). Adds a per-table **kebab (⋮) menu** to the schema-browser table rows in `design-system.md` §6 — a small popover menu (no existing menu/popover primitive in the app, so this spec introduces one). Reuses the SPEC-026 confirm-modal for Drop, and a lightweight transient **toast** for Drop feedback.

## Overview

The schema browser currently lets users expand a table and click columns to insert them. This spec adds a per-table **options menu** (a ⋮ button on each table row) with four actions that make the table directly actionable: **View source files** (jump to the table's data in the file browser), **View DDL** (open the table's `CREATE TABLE` definition in a query tab), **View data** (open and run a `SELECT * … LIMIT 10` preview in a tab), and **Drop table** (delete the table after an "are you sure" confirmation). Together these connect the analytics surface back to the file browser and turn the schema list into a control surface for managing tables.

## Scope

### In Scope

- A per-table **options menu** (kebab ⋮) on each schema-browser table row, opening a small accessible popover with the four actions below; this spec introduces a reusable lightweight **menu/popover** component (none exists today)
- **View source files** — navigate the user to the **file browser** at the table's S3 data location (the folder holding its files). Requires adding **`/files?prefix=…` URL support** to the file browser (it currently tracks the prefix in React state only) — in scope here
- **View DDL** — fetch the table's `CREATE TABLE` DDL via Athena `SHOW CREATE TABLE` and open it in a **new query tab** labelled `DDL: {table}` (populated, **not** auto-run)
- **View data** — open a **new query tab** labelled `{table}`, pre-filled with `SELECT * FROM {database}.{table} LIMIT {TABLE_PREVIEW_ROW_LIMIT}` and **auto-run** it
- **Drop table** — an **"are you sure"** confirm modal; on confirm, run `DROP TABLE {database}.{table}` **in the background** (no tab), then refresh the schema, record the run in history, and show a **toast** with success/failure
- A named constant `TABLE_PREVIEW_ROW_LIMIT = 10`
- All tab-opening actions route through SPEC-041 `openTab` and honor the **tab-limit dialog** (FR-008)

### Out of Scope

- A general right-click context menu (the menu is the explicit ⋮ button only)
- Editing table properties, renaming tables, or partition management
- Multi-select / bulk table actions
- Previewing data inline in the schema browser (View data uses the normal results table via a tab)
- **Generating** DDL client-side from Glue metadata — View DDL uses Athena `SHOW CREATE TABLE` (authoritative) rather than reconstructing it
- Any **IAM / infra** change — drop/DDL/preview run through the existing shared role + Athena/Glue access (SPEC-032/033/034); the file-browser deep-link is a frontend-only addition (same bucket/prefix the user already browses)
- Confirming **View data** auto-run cost (it's a `LIMIT 10` scan; acceptable). No separate cost guard beyond the workgroup's existing bytes-scanned cutoff (SPEC-032)

---

## Functional Requirements

### FR-001: Table options menu (kebab)

#### Description:

Each table row gets a ⋮ menu exposing the four actions.

#### Acceptance Criteria:

- [ ] Each schema-browser table row shows a **⋮ options** button (accessible label e.g. `aria-label="Options for sales_2026"`), revealed on row hover/focus and always reachable by keyboard
- [ ] Activating it opens a small **popover menu** with: **View source files**, **View DDL**, **View data**, **Drop table** (Drop visually separated and/or `danger`-toned)
- [ ] The menu is accessible: `aria-haspopup`/`aria-expanded`, focus moves into the menu, **Escape** and **outside-click** close it, arrow-key navigation between items; opening the menu does not toggle the row's expand/collapse
- [ ] This menu/popover is implemented as a small reusable component (the app has no existing menu primitive); it is positioned within the sidebar without being clipped
- [ ] Each action receives the row's `GlueTableSummary` (which carries `name` and `location`, SPEC-034)

### FR-002: View source files (deep-link to the file browser)

#### Description:

Navigate the user to the file browser at the folder backing the table's data.

#### Acceptance Criteria:

- [ ] The file browser accepts an initial prefix from the URL: visiting `/files?prefix={key}` seeds the browser at `{key}` (within the user-space bucket); absent/empty → today's default root behavior (SPEC-013) is unchanged
- [ ] **View source files** derives the table's prefix from `GlueTableSummary.location` (`s3://{bucket}/{key}`) by stripping the `s3://{bucket}/` portion, then navigates (`useNavigate`) to `/files?prefix={key}` — landing the user in the **folder that holds the table's data files** (the table `LOCATION`)
- [ ] The derived prefix is **validated to be within the user's own space** (starts with `{username}/`); if `location` is missing or outside the user prefix, the action is disabled or shows a non-blocking notice rather than navigating somewhere invalid
- [ ] After navigation the file browser shows that folder's contents using the existing authenticated listing (no new S3 permissions); breadcrumbs work from there as normal

### FR-003: View DDL (SHOW CREATE TABLE → new tab)

#### Acceptance Criteria:

- [ ] **View DDL** calls a new service `getTableDdl(database, table)` that runs `SHOW CREATE TABLE {database}.{table}` via Athena (`runQuery` + poll + fetch results) and returns the assembled DDL string (joining the single-column result rows with newlines); returns `ServiceResult<string>`, never throws
- [ ] On success it opens a **new tab** via `openTab({ label: 'DDL: {table}', sql: ddl })` — populated, **not** auto-run — and makes it active; at the tab cap, the SPEC-041 FR-008 dialog shows instead and nothing is lost
- [ ] While fetching, the action shows a brief loading affordance; on failure it surfaces the error (toast or inline notice) without opening a tab
- [ ] The `SHOW CREATE TABLE` helper does **not** append a `query-history` entry (it's an internal UI fetch, not a user-run query)

### FR-004: View data (SELECT * LIMIT 10 → new tab, auto-run)

#### Acceptance Criteria:

- [ ] A named constant `TABLE_PREVIEW_ROW_LIMIT = 10` (in `query.constants.ts`) is the single source of truth for the preview size
- [ ] **View data** opens a **new tab** via `openTab({ label: '{table}', sql })` where `sql = SELECT * FROM {database}.{table} LIMIT {TABLE_PREVIEW_ROW_LIMIT}`, makes it active, and **auto-runs** it through the normal tab Run path (so it polls, shows results, and appends a history entry exactly like a hand-typed query)
- [ ] At the tab cap, the SPEC-041 FR-008 dialog shows and no preview tab opens
- [ ] Identifiers are composed safely from the catalog-safe `database`/`table` names (SPEC-033 username rule); quoting is applied where needed so unusual but valid table names still parse

### FR-005: Drop table (confirm → background run → refresh + toast)

#### Acceptance Criteria:

- [ ] **Drop table** opens an **"are you sure"** confirm modal (SPEC-026 `role="alertdialog"`, danger action) naming the table and warning the action is irreversible
- [ ] Confirming runs `DROP TABLE {database}.{table}` **in the background** (not in a tab): `runQuery` + poll to terminal; the run **is** appended to query history (so there's a record the table was dropped)
- [ ] On **success**, the schema browser is refreshed (`invalidateSchema`, SPEC-034/035) so the table disappears, and a **success toast** is shown ("Dropped {table}"); on **failure**, an **error toast** carries the Athena reason and the schema is left unchanged
- [ ] The confirm modal's action is disabled / shows progress while the drop is in flight; cancelling never runs anything
- [ ] If a tab is currently previewing that table (FR-004), dropping does not crash it — the tab keeps its (now stale) results; no special handling required beyond not erroring

### FR-006: Toast (Drop feedback)

#### Acceptance Criteria:

- [ ] A lightweight, transient **toast/notice** surfaces Drop success/failure (auto-dismiss after a few seconds, manually dismissible, accessible live region). The app has no toast primitive today; this spec introduces a minimal one (or, if preferred, reuses the SPEC-028 `Banner` shown transiently in the workspace — see Open Questions)
- [ ] Toasts never block interaction and stack/replace sensibly if two occur close together

### FR-007: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: the menu opens/closes (Escape/outside-click) and is keyboard-navigable without toggling expand; `/files?prefix=` seeds the browser and a missing param preserves default behavior; View-source-files derives the prefix from `location` and rejects out-of-space locations; `getTableDdl` assembles the DDL and opens a non-auto-run tab (and no history entry is written for it); View-data builds the `LIMIT 10` SQL, opens a tab, and auto-runs; Drop confirm → background run → `invalidateSchema` + history append + success toast, and the failure path shows an error toast and leaves schema intact; all tab-opening actions hit the FR-008 cap dialog at the limit

---

## Data Model

No new persisted types. Adds one constant and one service signature:

```ts
// query.constants.ts
export const TABLE_PREVIEW_ROW_LIMIT = 10; // SPEC-044 FR-004 "View data" preview size

// query.service.ts (or glue.service.ts)
getTableDdl(database: string, table: string): Promise<ServiceResult<string>>; // runs SHOW CREATE TABLE

// Consumes the existing SPEC-034 GlueTableSummary.location for View source files.
```

## API / Interface Contract

```ts
// SchemaBrowser gains per-table action callbacks (wired in QueryWorkspace):
type SchemaBrowserProps = {
  database: string;
  onInsert: (name: string) => void;
  onViewSourceFiles: (table: GlueTableSummary) => void; // → navigate /files?prefix=…
  onViewDdl: (table: GlueTableSummary) => void;          // → getTableDdl → openTab (no run)
  onViewData: (table: GlueTableSummary) => void;         // → openTab(SELECT * LIMIT 10) + run
  onDropTable: (table: GlueTableSummary) => void;        // → confirm → background DROP → refresh + toast
};

// File browser deep-link (FilesPage reads the search param on mount):
//   /files?prefix=alice/datasets/sales_2026/
//   const initialPrefix = new URLSearchParams(location.search).get('prefix') ?? undefined;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts         ← + TABLE_PREVIEW_ROW_LIMIT = 10
├── query.service.ts           ← + getTableDdl (SHOW CREATE TABLE)
├── query.service.test.ts      ← + getTableDdl tests
├── SchemaBrowser.tsx          ← per-table ⋮ menu + action callbacks
├── SchemaBrowser.test.tsx     ← menu + actions tests
├── TableActionsMenu.tsx       ← NEW: kebab button + accessible popover menu (reusable)
├── TableActionsMenu.test.tsx  ← NEW
├── DropTableDialog.tsx        ← NEW: "are you sure" confirm (SPEC-026 alertdialog)
├── QueryWorkspace.tsx         ← wire the four actions (navigate / openTab / getTableDdl / drop+toast)
└── (toast)                    ← Toast.tsx + useToast (minimal) OR reuse components/Banner — see Open Questions
apps/portal/src/features/file-browser/
└── FileBrowser.tsx / FilesPage ← read `?prefix=` on mount to seed the initial prefix (FR-002)
```

## Implementation Phases

### Phase 1: Menu + file-browser deep-link (View source files)

- Build `TableActionsMenu` (kebab + accessible popover) and attach to `SchemaBrowser` rows with the four callbacks (Drop disabled-stub for now)
- Add `/files?prefix=` support to the file browser; implement **View source files** (derive prefix from `location`, validate in-space, navigate)
- Tests: menu a11y; deep-link seeding + default-preserving; prefix derivation/validation (FR-001, FR-002)

#### Checkpoint

Hover a table → ⋮ opens a menu (Escape/outside-click close, keyboard works, expand not toggled). **View source files** lands the file browser in that table's folder; a table whose `location` is missing/out-of-space doesn't navigate. `npm run test` + `npm run lint` pass.

### Phase 2: View DDL + View data

- `getTableDdl` (SHOW CREATE TABLE) + **View DDL** → `openTab` (no run); `TABLE_PREVIEW_ROW_LIMIT` + **View data** → `openTab` + auto-run; both honor the cap dialog (FR-003, FR-004)

#### Checkpoint

**View DDL** opens a `DDL: {table}` tab with the CREATE statement (not run, and no history entry for the fetch). **View data** opens a `{table}` tab with `SELECT * … LIMIT 10` and runs it (results + a history entry). At 10 tabs, either action shows the limit dialog. `npm run test` + `npm run lint` pass.

### Phase 3: Drop table + toast

- `DropTableDialog` confirm; background `DROP TABLE` run + history append + `invalidateSchema`; toast (new minimal toast or transient Banner) for success/failure (FR-005, FR-006)

#### Checkpoint

**Drop table** → confirm → on success the table disappears from the schema and a success toast shows (with a history entry recording the drop); a failing drop shows an error toast and leaves the schema intact. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-19):** View DDL / View data open a **new tab** (not the active tab).
- [x] **Resolved (2026-06-19):** Drop runs **in the background** after confirm — history + schema refresh + toast, no tab.
- [x] **Resolved (2026-06-19):** tabs from these actions use **descriptive labels** (`{table}`, `DDL: {table}`).
- [x] **Default (2026-06-19):** "View source files" navigates to the table's **`LOCATION` folder** (where the data files live), interpreting "parent folder of the data" as that folder. Flag if you instead want one level up.
- [ ] **Toast vs Banner.** No toast primitive exists. Default: introduce a **minimal toast** for Drop feedback. Acceptable alternative: reuse the SPEC-028 `Banner` shown transiently at the top of the workspace (less new surface). Confirm which during the design pass.
- [ ] **Identifier quoting.** `database`/`table` come from catalog-safe names (SPEC-033), so `{database}.{table}` is generally safe; confirm whether to defensively quote identifiers (e.g. Presto double-quotes for `SELECT`, backticks for DDL) for robustness.
