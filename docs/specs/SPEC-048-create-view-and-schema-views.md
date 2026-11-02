---
type: Spec
id: SPEC-048
title: "Create View from Query + Views in the Schema Browser"
description: "Lets users create a view from the current SELECT with a Create view action, and makes the schema browser list views with a badge, using view-specific DDL and drop behavior and disabling source files for views."
spec_status: Completed
depends_on: [SPEC-047, SPEC-044, SPEC-041, SPEC-034, SPEC-033, SPEC-026, SPEC-028]
arc: query-editor-round-3
arc_order: 3
---

**Dependency notes:** SPEC-047 (per-tab selected database / connection selector), SPEC-044 (`TableActionsMenu`, `getTableDdl`, `DropTableDialog`, `Toast`, `runStatementToCompletion`), SPEC-041 (query tabs + Run path), SPEC-034 (`runQuery`, `listTables`/`GlueTableSummary.tableType`, history append, `invalidateSchema`), SPEC-033 (catalog-safe identifier rule; LF `CREATE_TABLE`/`ALTER`/`DROP` grant on the user's DB), SPEC-026 (dialog pattern), SPEC-028 (Button/Input)
> **Design:** Needs a design pass. Adds a **Create view** button to the editor toolbar (same group as Run/Save, `design-system.md` §6) and a **view** badge + view-aware options in the schema browser table rows (SPEC-044 menu). Reuses the SPEC-026 name-prompt modal shape and the SPEC-044 `Toast`.

## Overview

After writing a `SELECT` a user often wants to persist it as a reusable **view** rather than re-type or re-open it. This spec adds a **Create view** action that prompts for a view name and runs `CREATE OR REPLACE VIEW {database}.{name} AS {current SQL}` against the tab's **selected database** (SPEC-047), then refreshes the schema so the new view appears. It also makes the schema browser **view-aware**: views (Glue `TableType = VIRTUAL_VIEW`) are listed alongside tables with a distinguishing badge, and the per-table options menu (SPEC-044) behaves correctly for views — **View DDL** uses `SHOW CREATE VIEW`, **Drop** issues `DROP VIEW`, **View source files** is disabled (a view has no S3 location), and **View data** still previews rows.

## Scope

### In Scope

- A **Create view** control in the editor toolbar (acts on the **active tab's SQL**), opening a **name-prompt modal** (SPEC-026 pattern); on confirm it runs `CREATE OR REPLACE VIEW {database}.{name} AS {sql}` against the **active workspace database** (SPEC-047 — workspace-global), **in the background** (like SPEC-044 Drop — the editor keeps showing the user's `SELECT`)
- **View-name validation** to the catalog-safe identifier rule (`^[a-z][a-z0-9_]{2,62}$`, SPEC-033), with inline error messaging in the dialog
- On success: **refresh the schema** (`invalidateSchema` for that database) so the view appears, append a **history** entry (it's a real run), and show a **success Toast** (SPEC-044); on failure, an **error Toast** carrying the Athena reason and no schema change
- **Schema browser views:** `listTables` already returns views (`tableType: 'VIRTUAL_VIEW'`); the schema browser renders them with a **view badge** so users can tell views from tables
- **View-aware options menu (amends SPEC-044):** for a view row — **View DDL** runs `SHOW CREATE VIEW` (not `SHOW CREATE TABLE`); **Drop** opens the confirm and runs `DROP VIEW` (not `DROP TABLE`); **View source files** is **disabled** (a view has no `location`); **View data** opens a `SELECT * … LIMIT {TABLE_PREVIEW_ROW_LIMIT}` preview tab and runs it, exactly as for a table

### Out of Scope

- **Materialized views / CTAS** (`CREATE TABLE AS SELECT`) — this spec is logical views only; materializing data is a separate concern
- **Editing/altering** an existing view's definition through a dedicated UI (re-running Create view with the same name `OR REPLACE`s it — that **is** the edit path; no separate "edit view" screen)
- **Renaming** a view (Athena/Glue has no rename; drop + recreate)
- A separate **view-name uniqueness pre-check** against the catalog — `CREATE OR REPLACE VIEW` is idempotent by design; we rely on it (no extra `GetTable` round-trip). Collisions with an existing **table** of the same name are surfaced as the Athena error (see Open Questions)
- Any **IAM / infra** change — creating/dropping a view in the user's own database uses the existing SPEC-033 grants (`CREATE_TABLE`/`ALTER`/`DROP` on the DB); creating a view in a **shared** database depends on that arc's grants, not this spec
- Validating that the editor SQL is a single well-formed `SELECT` beyond a light guard — Athena rejects an invalid view body and the error Toast surfaces it (see Open Questions)

---

## Functional Requirements

### FR-001: Create view button + name prompt

#### Description:

A toolbar control turns the active tab's SQL into a named view.

#### Acceptance Criteria:

- [ ] A **Create view** button sits in the editor toolbar in the Run/Save group; it acts on the **active tab** and is **disabled** when the tab's SQL is empty/whitespace
- [ ] Clicking it opens a **name-prompt modal** (SPEC-026 pattern; labelled `Input` + **Create**/**Cancel**); **Create** is disabled until the name passes validation
- [ ] Cancel/Escape closes the dialog with no change and no query run

### FR-002: View-name validation

#### Acceptance Criteria:

- [ ] The view name is validated against the catalog-safe identifier rule **`^[a-z][a-z0-9_]{2,62}$`** (SPEC-033) — lowercase, starts with a letter, letters/digits/underscore, 3–63 chars; an invalid name shows an inline error and blocks **Create**
- [ ] The rule string is referenced from the shared username/identifier constant where one exists (don't hand-duplicate the regex), keeping it aligned with SPEC-033

### FR-003: Run CREATE OR REPLACE VIEW

#### Description:

On confirm, build and run the view DDL against the tab's selected database, in the background.

#### Acceptance Criteria:

- [ ] On confirm, the action composes `CREATE OR REPLACE VIEW {database}.{name} AS {sql}` where `database` = the **active workspace database** (SPEC-047) and `sql` = the active tab's current editor SQL with any trailing semicolon/whitespace stripped
- [ ] It runs **in the background** via the SPEC-044 `runStatementToCompletion` helper (StartQueryExecution + poll to terminal) — the editor keeps showing the user's `SELECT`; the run **appends a history entry** (so there's a record the view was created), with the entry's `database` = the selected database
- [ ] Identifiers (`database`, `name`) are composed safely (catalog-safe per FR-002 / SPEC-033; quote where Athena requires) so the statement parses
- [ ] The dialog's **Create** action shows progress / is disabled while the run is in flight; cancelling before confirm runs nothing

### FR-004: Success / failure feedback + schema refresh

#### Acceptance Criteria:

- [ ] On **success**: `invalidateSchema` runs for the selected database (SPEC-034/035) so the schema browser shows the new view, and a **success Toast** appears ("Created view {name}")
- [ ] On **failure**: an **error Toast** carries the Athena failure reason; the schema is left unchanged and the dialog either stays open with the error or closes per the design (default: close + error Toast)
- [ ] Creating a view named identically to an existing **view** simply `OR REPLACE`s it (no error, refreshed definition); a name colliding with an existing **table** surfaces the Athena error via the error Toast (documented behavior — no silent overwrite of a table)

### FR-005: Views listed in the schema browser

#### Acceptance Criteria:

- [ ] The schema browser lists entries with `tableType === 'VIRTUAL_VIEW'` alongside tables, each with a clear **view badge** (text label, not color-only) distinguishing it from a base table
- [ ] Views expand to show their columns exactly like tables (SPEC-035), via the existing `useSchema`/`listTables` data (no new fetch)
- [ ] Ordering/empty/loading/error states are unchanged (a database with only views still renders normally)

### FR-006: View-aware options menu (amends SPEC-044)

#### Acceptance Criteria:

- [ ] For a **view** row, **View DDL** calls a DDL fetch that runs **`SHOW CREATE VIEW {database}.{name}`** (table rows still use `SHOW CREATE TABLE`); the assembled DDL opens in a `DDL: {name}` tab, not auto-run, no history entry (consistent with SPEC-044 FR-003)
- [ ] For a **view** row, **Drop table** is presented appropriately (label/confirm copy may say "Drop view") and runs **`DROP VIEW {database}.{name}`**; on success the schema refreshes and a success Toast shows; failure shows an error Toast and leaves the schema intact (SPEC-044 FR-005 behavior, `DROP VIEW` variant)
- [ ] For a **view** row, **View source files** is **disabled** (a view has no `location` → SPEC-044 `canViewSourceFiles` already returns false; assert it)
- [ ] For a **view** row, **View data** opens and runs `SELECT * FROM {database}.{name} LIMIT {TABLE_PREVIEW_ROW_LIMIT}` exactly like a table (SPEC-044 FR-004)
- [ ] The DDL/drop branching keys off `GlueTableSummary.tableType` (`VIRTUAL_VIEW` → view variant; otherwise table variant); both go through the existing SPEC-044 plumbing (tab cap dialog, Toast, schema refresh)

### FR-007: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: Create-view button disabled on empty SQL; name validation accepts/rejects per the rule; confirm composes `CREATE OR REPLACE VIEW {selectedDb}.{name} AS {strippedSql}` and runs in the background appending one history entry; success → `invalidateSchema(selectedDb)` + success Toast, failure → error Toast + no schema change; views render with a badge and expand to columns; the options menu uses `SHOW CREATE VIEW`/`DROP VIEW` for views and `SHOW CREATE TABLE`/`DROP TABLE` for tables; View source files is disabled for views; View data builds the LIMIT preview for a view

---

## Data Model

No new persisted types. Reuses SPEC-034 `GlueTableSummary` (`tableType`, `location`) and `QueryHistoryEntry`. One validation helper + view-aware DDL/drop SQL:

```ts
// query.constants.ts — reuse the SPEC-033 identifier rule (do not duplicate the regex)
// CATALOG_IDENTIFIER_RE = /^[a-z][a-z0-9_]{2,62}$/   // shared with username/table rule

// view DDL composition (background run, FR-003)
const ddl = `CREATE OR REPLACE VIEW ${database}.${name} AS ${stripTrailingSemicolons(sql)}`;

// view-aware schema actions (FR-006)
const isView = (t: GlueTableSummary) => t.tableType === 'VIRTUAL_VIEW';
// View DDL : isView ? `SHOW CREATE VIEW ${db}.${name}` : `SHOW CREATE TABLE ${db}.${name}`
// Drop     : isView ? `DROP VIEW ${db}.${name}`        : `DROP TABLE ${db}.${name}`
```

## API / Interface Contract

```ts
// Create view goes through the SPEC-044 background-run helper (no new service shape needed):
await runStatementToCompletion({ sql: ddl, database, username });   // appends history (FR-003)

// getTableDdl (SPEC-044) gains view awareness (or a sibling getViewDdl):
getTableDdl(database: string, name: string, isView: boolean): Promise<ServiceResult<string>>;
//   isView ? SHOW CREATE VIEW : SHOW CREATE TABLE
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── CreateViewDialog.tsx        ← NEW: name-prompt modal (validated, SPEC-026 pattern)
├── CreateViewDialog.test.tsx   ← NEW
├── query.service.ts            ← getTableDdl gains isView (SHOW CREATE VIEW); view DROP path
├── query.service.test.ts       ← + view DDL/drop tests
├── query.constants.ts          ← shared catalog-identifier rule reference (no regex dup)
├── SchemaBrowser.tsx           ← view badge; view-aware menu wiring (DDL/Drop/source-files)
├── SchemaBrowser.test.tsx
├── DropTableDialog.tsx         ← copy/label variant for views ("Drop view")
└── QueryWorkspace.tsx          ← Create view button + dialog; compose+run DDL; schema refresh + Toast
```

## Implementation Phases

### Phase 1: Create view (button + dialog + run + feedback)

- `CreateViewDialog` (validated name); compose `CREATE OR REPLACE VIEW` against `activeTab.database`; background run + history append; success/error Toast + `invalidateSchema` (FR-001–FR-004)

#### Checkpoint

`npm run dev`: write a `SELECT`, click **Create view**, enter a valid name → a success Toast appears and the view shows up in the schema browser after refresh; an invalid name is blocked inline; a bad view body shows an error Toast and no schema change; a history entry records the run. `npm run test` + `npm run lint` pass.

### Phase 2: Views in the schema browser + view-aware menu

- View badge in `SchemaBrowser`; branch `getTableDdl`/Drop on `tableType` (`SHOW CREATE VIEW`/`DROP VIEW`); disable View source files for views; View data preview for views (FR-005, FR-006)

#### Checkpoint

A view lists with a **view** badge and expands to its columns; its options menu shows the DDL via `SHOW CREATE VIEW`, drops via `DROP VIEW` (schema refreshes, Toast shows), disables View source files, and previews rows via View data. Tables are unchanged. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-21):** Create view runs **in the background** with a Toast (like SPEC-044 Drop), leaving the editor's `SELECT` intact — rather than overwriting the editor/active-tab with the `CREATE VIEW` text.
- [x] **Resolved (2026-06-21):** the action targets the **active workspace database** (SPEC-047 — workspace-global, switched in the schema rail), so views can be created in whichever database the workspace is pointed at (personal now; shared later).
- [x] **Resolved (2026-06-21):** rely on **`CREATE OR REPLACE VIEW`** for idempotency/edit (no separate view-exists pre-check); re-creating with the same name replaces the view.
- [x] **Resolved (2026-06-21):** view name uses the **catalog-safe identifier rule** (SPEC-033), referenced from the shared constant (no regex duplication).
- [x] **Resolved (2026-06-21, default):** a view name equal to an existing **table** name fails at Athena and is surfaced via the **error Toast** (no extra catalog pre-check round-trip in v1). Flag if a friendlier pre-check message is wanted.
- [x] **Resolved (2026-06-21, default):** the view body gets only a **light guard** (non-empty, strip trailing `;`); Athena rejects a non-`SELECT` body and the error Toast surfaces it. Flag if a stricter client-side "must start with SELECT/WITH" guard is wanted.
