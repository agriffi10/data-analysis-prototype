# Completed Spec — SPEC-077: Cross-Database Querying (drop the active-database session)

## What was completed?

The query workspace no longer has an "active database." Users query **any** database they can access and **join
across databases** in one statement, by fully-qualifying every base table as `database.table`. Frontend-only; no
IAM/infra/data-layer change (the shared portal role already holds Glue+LF+S3 on the personal `username` tag + every
shared membership tag).

- **Removed the active-database session (FR-001):** deleted `useActiveDatabase` + `QUERY_ACTIVE_DB_STORAGE_PREFIX`
  (with a one-time `sessionStorage` cleanup in `QueryWorkspace`); dropped the "querying `<db>`" toolbar chip and the
  SPEC-047 fallback banner.
- **No run context (FR-002):** `runQuery`'s `database` is now optional and omitted — `QueryExecutionContext.Database`
  is not sent, so only fully-qualified names resolve (an unqualified base table fails via the existing error path).
- **Browse-only schema rail (FR-003):** `SchemaBrowser`/`DatabaseNode` lost the radio/active selection; each database
  is expandable for inspection only.
- **Per-table actions from node context (FR-007):** `TableActions` callbacks now take `(database, table)`; View
  DDL / View data / Drop act on the node's database (`node-db.table`).
- **Create view derives its target (FR-008):** new `deriveViewTargetDatabase` reads the body's fully-qualified base
  tables — one database → target; zero or multiple → a clear danger toast (never a silent pick). `CreateViewDialog`
  shows the derived target read-only.
- **Multi-database autocomplete (FR-005):** new `useAllSchemas` (via `useQueries`) eagerly loads every accessible
  database's schema; `buildSqlCompletions` now takes `DatabaseSchema[]` and emits **fully-qualified** `database.table`
  table/view suggestions (columns keep their SPEC-065 bare-name + type detail).
- **History/saved queries (FR-006):** the `database` field is informational — runs/saves record the personal db.
- **Marked SPEC-076 Superseded** (already reflected); docs sweep rewrote the Help "Choose the active database" guide
  → "Browse databases and query across them."

### Deliberate deviations (user-confirmed; see spec header)

- **FR-004 dropped** — the rail no longer inserts into the editor at all (no table/column click-to-insert);
  `onInsert`/`SqlEditor.insertAtCursor` removed; columns are non-interactive.
- Run-time shared-result routing removed with the active database; `resultOutputLocation` (SPEC-055) was orphaned
  and deleted — shared save destinations remain a Save-time choice (SPEC-049/055 picker, unchanged).

## What changed from earlier specs?

Supersedes SPEC-047 (workspace-global active database) and SPEC-076 (per-tab database, never built). `runQuery`
signature (`database` optional), `SchemaBrowser`/`DatabaseNode`/`TableActions` props, `buildSqlCompletions` input,
and `SqlEditor` (`completionTables` → `completionSchemas`, `insertAtCursor` removed) all changed. `resultOutputLocation`
and `useActiveDatabase` deleted.

## Verification

`format:check`, `tsc`, ESLint, `build` clean; full Vitest **880 passed** (query suite rewritten for the new
behavior — removed active-db chip/radio/insert tests, `(database, table)` action tests, multi-db fully-qualified
completion tests, derived create-view target). Live browser deferred — `/query` is Cognito-gated and needs live
Athena (dev-unauth covers only `/files`), same limitation as SPEC-040→064.
