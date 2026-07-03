# Spec: Cross-Database Querying (drop the active-database session)

**ID:** SPEC-077
**Status:** Completed
**Last Updated:** 2026-07-03

> **Implementation notes (2026-07-03, user decisions).** Two scope changes were confirmed with the user during
> implementation:
> - **FR-004 dropped.** The schema rail no longer inserts anything into the editor — clicking a table/column does
>   not paste a reference. The rail is purely for **inspection** (expand databases → tables → columns). The
>   `onInsert`/`insertAtCursor` path was removed entirely; columns render as non-interactive rows.
> - **FR-005 kept, full breadth.** Autocomplete **eagerly loads every accessible database's schema** (new
>   `useAllSchemas` via `useQueries`) so fully-qualified `database.table` suggestions span all databases from the
>   start. Tables/views are fully-qualified; columns keep their SPEC-065 bare-name + type detail form.
> - Run-time shared-result routing (the SPEC-055 `resultOutputLocation` path) is removed with the active database —
>   results always land in the personal prefix; a shared destination is chosen only at Save time (unchanged
>   SPEC-049/055 picker). The now-orphaned `resultOutputLocation` was deleted.
**Depends On:** SPEC-047 (workspace database selector — superseded here), SPEC-052 (`useConnections`), SPEC-063 (schema-rail tree), SPEC-065 (editor autocomplete)

## Overview

Today the query workspace forces the user to pick **one** active database (SPEC-047,
workspace-global; SPEC-076 proposed making it per-tab). That single database is
sent to Athena as the query's `QueryExecutionContext.Database`, so a query can only
"see" one database at a time and cross-database work is impossible without switching
back and forth. Users have asked to **query any database they have access to, and to
join across databases in a single query**, without managing a "current database"
session at all. This spec removes the database-selection concept **entirely**: the
schema rail becomes a **browse-only** view of every database the user can access, and
**no database is ever "selected."** The deliberate trade-off is that **every table
reference must be fully-qualified `database.table`** — in `FROM`/`JOIN` clauses,
subqueries, and CTE bodies alike. No default catalog context is sent to Athena, so an
unqualified base-table reference simply fails; that is the accepted cost of removing
selection. Because it eliminates the per-session/per-tab active database, this spec
**supersedes SPEC-076** (per-tab database — which will not be built) and retires
SPEC-047's workspace-global active database.

## Scope

### In Scope

- Remove the database-selection concept **entirely** (`useActiveDatabase`,
  `QUERY_ACTIVE_DB_STORAGE_PREFIX`, the schema rail's active/radio selection, and the
  "querying `<db>`" chip). There is no "current database" anywhere in the workspace.
- Send **no database context** to Athena on a run (omit `QueryExecutionContext.
  Database`). Every `database.table` reference is executed as written; an unqualified
  base-table reference is not resolved and fails — the accepted trade-off.
- Schema rail becomes **browse-only**: every accessible database (personal + usable
  shared connections) is expandable to inspect its tables/views; there is no
  "active database" chip or radio. Clicking a table/column inserts its
  **fully-qualified** name at the cursor.
- Editor autocomplete offers tables/columns from **all accessible databases**
  (fully-qualified), not just one active database.
- Per-table actions derive their target database **from context, not a selection**:
  View DDL / View data / Drop / Source files use the database of the rail node the
  table belongs to.
- Create view **infers its target database from the view's own query** — the
  database of the fully-qualified base tables the view body selects from (views
  generally don't span databases), rather than a picker or an active selection.
- Results routing (SPEC-055): a query's results land in the personal
  `athenaresults/` prefix (derived from `username`, not from any selection); routing
  to a shared space's prefix is chosen explicitly at Save time (SPEC-049/055).
- Query history records the query text **as written**; the stored `database` field is
  informational only (no selection to record — see Data Model).
- **Retire SPEC-076 (do not build).** Marked `Superseded (by SPEC-077)` in its header
  and the INDEX; per-tab databases will not be implemented.

### Out of Scope

- Any IAM / Lake Formation / infra change. The single shared portal role already
  holds Glue + LF + S3 grants for the personal database (via the `username`
  principal tag) **and** every shared space the user belongs to (via membership
  tags, SPEC-056), so a query that spans those databases is already authorized. If
  a cross-database query references a database the user cannot access, Athena/LF
  denies it and the existing error path surfaces the failure — this spec adds no
  new authorization logic.
- Changing **where a running query's results are written** based on which databases
  it touches. Results default to the personal prefix; a cross-space query that a
  user wants saved into a shared space uses the existing SPEC-049/055 Save-results
  destination picker. (Run-time shared routing tied to a single "active shared
  connection" no longer exists once the active database is gone.)
- A UI for building cross-database joins (drag-to-join, etc.) — this is purely
  enabling fully-qualified SQL the user writes themselves.
- Multiple-statement execution (SPEC-078), the editor/results splitter (SPEC-079),
  total-row-count stats (SPEC-080) — independent specs in this round.

---

## Functional Requirements

### FR-001: Remove the active-database session

#### Description:

Delete the workspace-global active-database state and its persistence. The workspace
no longer tracks or persists a "current database"; nothing in the UI selects one.

#### Acceptance Criteria:

- [ ] `useActiveDatabase` and the `QUERY_ACTIVE_DB_STORAGE_PREFIX` sessionStorage
      key are removed (with a one-time cleanup that deletes any previously-written
      key so it doesn't linger).
- [ ] The "querying `<db>`" toolbar chip and the schema rail's active/radio control
      are removed.
- [ ] No workspace behavior depends on a single selected database.

### FR-002: No database context — fully-qualified references required

#### Description:

Queries are submitted with **no** `QueryExecutionContext.Database`. Every base-table
reference the query relies on must be fully-qualified `database.table`; there is no
default database that resolves bare names. A query may reference/join any databases
the user can access.

#### Acceptance Criteria:

- [ ] `runQuery` submits the execution without a `QueryExecutionContext.Database`
      (the field is omitted, not set to a default).
- [ ] A query written as `SELECT * FROM db_a.t JOIN db_b.u …` succeeds when the user
      has access to both `db_a` and `db_b` (no selection step).
- [ ] A query with an **unqualified** base table (e.g. `SELECT * FROM orders`) fails
      with the existing error banner (accepted trade-off; not special-cased).
- [ ] A query referencing a database the user cannot access fails with the existing
      error banner (no special-casing).
- [ ] CTE names and column aliases defined within the query are still referenced
      unqualified (only **base tables** require a database prefix).

### FR-007: Per-table actions derive their database from node context

#### Description:

With no active database, per-table actions take their target database from the rail
node the table was invoked from, not from a selector.

#### Acceptance Criteria:

- [ ] View DDL / View data / Drop / Source files run against the database of the node
      the table was invoked from (a table under `db_a` acts on `db_a.<table>`).
- [ ] "View data" opens a tab pre-filled with a fully-qualified
      `SELECT * FROM <node-db>.<table> LIMIT N`.

### FR-008: Create view targets the database its query runs against

#### Description:

Create view **infers** its target database from the view's own query body: the
database of the fully-qualified base tables the body selects from. Views generally
don't span databases, so a single database is expected. The view is created in that
database; the body's base tables stay fully-qualified as written.

#### Acceptance Criteria:

- [ ] A view whose body selects from `db_a.*` is created as
      `CREATE OR REPLACE VIEW db_a.<name> AS <body>` — the target is derived, not
      chosen.
- [ ] Creating the view refreshes that database's schema so the new view appears
      under it in the rail.
- [ ] When the body's base tables all resolve to one database, that database is the
      target (the common case).
- [ ] When the target can't be unambiguously derived (the body references **more
      than one** database, or no fully-qualified base table), the action surfaces a
      clear, non-blocking error asking the user to qualify/scope the view to a single
      database — it does **not** silently pick one.
- [ ] The view body's base-table references are left fully-qualified (unchanged).

### FR-003: Browse-only schema rail across all accessible databases

#### Description:

The schema rail lists every accessible database (personal + usable shared
connections from `useConnections`) as an expandable node for inspection only. There
is no active-database selection; expanding a node loads that database's
tables/views (unchanged `DatabaseNode`/`useSchema`).

#### Acceptance Criteria:

- [ ] Each accessible database is independently expandable/collapsible to browse
      its tables and views.
- [ ] Unusable shared connections (provisioning/failed/leaving) remain shown but
      not expandable (unchanged from SPEC-063).
- [ ] No radio / "set active" affordance is present.
- [ ] Removing the last-used shared database no longer triggers a "switched back to
      your workspace" fallback banner (there is nothing to fall back from).

### FR-004: Inserting a table/column inserts a fully-qualified reference

#### Description:

Clicking a table (or column) in the schema rail inserts its **fully-qualified**
`database.table` (or `database.table.column`) name at the editor cursor, so an
inserted reference is unambiguous regardless of the default context.

#### Acceptance Criteria:

- [ ] Inserting a table from database `db_a` inserts `db_a.<table>`.
- [ ] Inserting a table from the personal database inserts `<username>.<table>`.
- [ ] The inserted text lands at the cursor (unchanged `insertAtCursor`).

### FR-005: Autocomplete spans all accessible databases

#### Description:

The Monaco completion provider (SPEC-065) offers table/view + column suggestions
from **every accessible database**, each suggestion fully-qualified, alongside SQL
keywords. Keyword-only fallback remains when no schema is loaded.

#### Acceptance Criteria:

- [ ] Completions include fully-qualified table names from more than one database
      when the user has multiple accessible databases.
- [ ] Column suggestions carry their type detail (unchanged from SPEC-065).
- [ ] With no schema available, keyword-only completion still works.

### FR-006: History reflects the query as written

#### Description:

A history entry stores the exact SQL the user ran; its `database` field is the fixed
default context (personal), used only for display/back-compat, not to reconstruct a
selection.

#### Acceptance Criteria:

- [ ] Re-opening a history entry loads its SQL verbatim into the active tab.
- [ ] Re-running a history entry runs the same SQL with the personal default
      context.
- [ ] No history entry implies a per-tab/global active database.

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts
// QueryTab loses nothing (SPEC-076's proposed `database` field is NOT added).
// Connection is unchanged; `isConnectionUsable` still gates which databases the
// rail can expand and which appear in autocomplete/save destinations.

// runQuery drops the required `database` — the execution carries NO database
// context. `username` still drives result-output routing (personal athenaresults/).
runQuery(p: {sql: string; username: string; database?: string; outputLocation?: string})
// When `database` is omitted (the default now), QueryExecutionContext is sent
// without a Database field. Internal DDL helpers (getTableDdl / drop) pass the
// node's database only to build fully-qualified `db.table` statement text — they
// do not need a run context.

// QueryHistoryEntry.database is now informational (kept for back-compat / display).
// New/query runs store it as empty string (or the personal db) — it no longer
// reconstructs any selection.
```

The `useActiveDatabase` hook and `QUERY_ACTIVE_DB_STORAGE_PREFIX` are deleted; a
one-time `sessionStorage.removeItem` cleans up any persisted key.

## API / Interface Contract

```ts
// SchemaBrowser loses the active-selection props (`database`, `onSelectDatabase`)
// and becomes browse-only. onInsert now receives a fully-qualified name.
onInsert(fullyQualifiedName: string): void; // e.g. "db_a.orders" or "db_a.orders.id"

// Autocomplete source: all usable connections' schemas, not one active schema.
completionTables: Array<{database: string; tables: GlueTableSummary[]}>;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── QueryWorkspace.tsx     # drop active-DB wiring, chip, fallback banner; run w/ personal ctx
├── SchemaBrowser.tsx      # browse-only rail (no radio/active), fully-qualified insert
├── DatabaseNode.tsx       # unchanged expand/browse; no "set active"
├── CreateViewDialog.tsx   # show the derived target database (read-only); no picker
├── query.sql.ts           # helper: derive the target database from a view body's
│                          #   fully-qualified base tables (single-db / ambiguous)
├── sqlCompletions.ts      # multi-database, fully-qualified completions
├── useActiveDatabase.ts   # REMOVED
├── query.constants.ts     # remove QUERY_ACTIVE_DB_STORAGE_PREFIX (+ cleanup)
└── *.test.tsx             # updated coverage
```

## Implementation Phases

### Phase 1: Remove the active-database session

- Delete `useActiveDatabase` + the sessionStorage key (with one-time cleanup);
  remove the "querying `<db>`" chip and the SPEC-047 fallback banner from
  `QueryWorkspace`.
- Drop the run database context: `runQuery` omits `QueryExecutionContext.Database`.
  Table/Create-view actions source their target database from node context /
  personal (FR-007). Keep results routing default = personal (`username`).

### Phase 2: Browse-only schema rail + fully-qualified insert

- Make `SchemaBrowser`/`DatabaseNode` browse-only (no radio, no active state);
  expansion still lazy-loads each database's schema.
- Change table/column insert to emit fully-qualified names.
- Per-table actions use their node's database (FR-007); Create view derives its
  target database from the view body's fully-qualified base tables (error when
  ambiguous / multi-database) and refreshes that database's schema on success
  (FR-008).

### Phase 3: Multi-database autocomplete

- Feed the completion provider every usable database's schema; emit fully-qualified
  table suggestions + typed columns; keyword-only fallback preserved.

### Phase 4: Completion ritual

- Delivery doc; INDEX status; mark **SPEC-076 superseded by SPEC-077**; update the
  Key Decisions line that names SPEC-047's "workspace-global active database" to
  record that the active-database session is removed in favor of fully-qualified
  cross-database queries.
