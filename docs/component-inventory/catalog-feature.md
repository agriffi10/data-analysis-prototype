# Catalog feature (`apps/portal/src/features/catalog/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

Public barrel: `features/catalog/index.ts`. The shared catalog & execution layer (SPEC-176): the
Glue schema reader, the Athena start/poll/results/cancel layer, the space list and the column-width
store — everything both the Query workspace and the Data Explorer need. **No UI** and no feature
domain of its own; `features/query/` and `features/data-explorer/` compose it and may not import
each other (enforced by the ESLint layering rule). All services return `ServiceResult<T>`, never
throw.

### Services

| Symbol | File | Purpose |
|---|---|---|
| `runQuery({ sql, database?, username, outputLocation? })` | `athena.service.ts` | `StartQueryExecution` against the shared workgroup. `outputLocation` omitted → the caller's own `{username}/athenaresults/`; pass a shared path for a shared-DB query (SPEC-055). Type-agnostic (SELECT + DDL). `ServiceResult<{ queryExecutionId }>`. |
| `getQueryStatus(id)` | `athena.service.ts` | `GetQueryExecution` → `QueryStatus` (state/reason/stats/outputLocation). |
| `getQueryResults({ queryExecutionId, nextToken?, maxRows? })` | `athena.service.ts` | `GetQueryResults` → typed `QueryResultPage` (first-page header row stripped after a `+1` overfetch; paginates via `nextToken`). DDL → empty page. A cell is **`null` for SQL NULL and `''` for an empty string** since SPEC-180 — the two used to be collapsed here, and no consumer could reconstruct the difference. |
| `stopQuery(id)` | `athena.service.ts` | `StopQueryExecution` → CANCELLED. |
| `isTerminalState(state)` | `athena.service.ts` | Is a `QueryState` terminal (SUCCEEDED/FAILED/CANCELLED)? |
| `runStatementToCompletion({ sql, database, username, signal? })` / `isAbandoned(result)` / `ABANDONED_CODE` | `athena.service.ts` | Run-and-poll-to-terminal helper for background statements (View DDL, Drop, Create view). An abandoned poll is its OWN code, so a caller says nothing rather than borrowing the upload feature's "Upload cancelled." (SPEC-044/048). |
| `getTableDdl({ database, table, username, isView? })` | `athena.service.ts` | `SHOW CREATE TABLE` (or `SHOW CREATE VIEW`) → the assembled DDL (SPEC-044/048). |
| `getDatabase(name)` / `listTables(name)` | `glue.service.ts` | A Glue DB + its tables/columns (paginated). Missing DB → `NotFound` / empty list, never thrown. |

### Hooks, keys, types, constants

| Symbol | File | Purpose |
|---|---|---|
| `useQueryExecution(id \| null)` | `useQueryExecution.ts` | Polls `getQueryStatus` via `refetchInterval` until terminal or `MAX_POLL_DURATION_MS`; disabled when null. |
| `useQueryResults(id \| null, maxRows?)` | `useQueryResults.ts` | Prev/Next pager over results via `useInfiniteQuery`: the current page's `columns`/`rows`, `pageIndex`/range, `hasPrev`/`hasNext`, `goPrev`/`goNext` (Next fetches forward, Prev from cache), loaded/total counts (SPEC-038). The remembered per-execution page is **clamped to the pages actually cached** (SPEC-180): an unobserved execution loses its pages at `gcTime` and refetches from page 1, and an absent page is indistinguishable from an empty one — a result WITH rows rendered as "No rows returned". |
| `useResultRowCount(id \| null)` | `useResultRowCount.ts` | Background page-walk counting a succeeded query's exact total rows via `GetQueryResults` (free, no extra scan) at `ROW_COUNT_PAGE_SIZE`, on a key separate from the visible pager's so it never perturbs it; `{total, isCounting, atCeiling}`, degrades to `null` on a failed page (SPEC-080). |
| `useColumnWidths(executionId, columnCount)` | `useColumnWidths.ts` | In-memory `Record<executionId, number[]>` width store keyed by execution id, so widths survive paging **and** tab switches; `widths`/`setWidth` (clamped ≥ `MIN_COLUMN_WIDTH`)/`resetColumn` (SPEC-064). |
| `ColumnResizeHandle({column, columnName, width, onResize, onReset})` | `ColumnResizeHandle.tsx` | The focusable `role="separator"` on a header's right edge — pointer drag, double-click reset, Arrow nudge by `COLUMN_RESIZE_STEP_PX`, and the `aria-valuenow`/`aria-valuemin`/`aria-valuemax` a focusable separator requires (`MAX_COLUMN_WIDTH`, which both width stores clamp to — ARIA's default max of 100 sat below every real width). Handled Arrows **stop propagating**, or a grid listening above it moves its cell cursor too. Moved here from `features/query/` by SPEC-180 (two sibling features draw grids and neither may import the other) and **generic over its column key**: the Query workspace passes an index (a `SELECT` may return duplicate names), the Data Explorer a name (its geometry outlives the execution). The only UI in this layer. |
| `useSchema(db \| null)` + `invalidateSchema(client, db)` + `onCatalogChange(listener)` | `useSchema.ts` | DB + tables for a schema browser; the invalidation helper that refreshes it after DDL; and the registration by which anything ELSE that caches per-database can hear the same signal. The registration exists because the shared layer must not import the leaf feature — the Data Explorer's execution cache has to be evicted on a rebuild, and `features/catalog/` reaching into `features/data-explorer/` to say so would point the layering the wrong way. Not a query-cache subscription: TanStack emits no event for invalidating a key nothing has cached. |
| `useAllSchemas(databaseNames)` | `useSchema.ts` | Every accessible database's schema at once (`useQueries`, sharing `useSchema`'s per-DB cache keys) → `DatabaseSchema[]`; failed DBs omitted (SPEC-077). |
| `useQuerySpaces()` | `useQuerySpaces.ts` | The one list of spaces a catalog consumer reads from and writes into — the user's own first, then each usable shared connection — as `QuerySpace[]` (SPEC-173 FR-005). |
| `catalogKeys` | `catalogKeys.ts` | Key factory (`all`/`schema`/`execution`/`results`/`rowCount`), rooted at `['catalog']` — never hand-build keys. Rooted away from `['query']` on purpose: a namespace naming a feature the module no longer belongs to would let `invalidateQueries({queryKey: queryKeys.all})` reach into another feature's caches (SPEC-176 FR-003). |
| `useSaveResults({spaces, username, outputLocation, linkedSavedName, toast})` | `useSaveResults.ts` | Copies a succeeded execution's results object out of `athenaresults/` into a chosen space — a server-side `CopyObject`, so ALL rows travel however few pages loaded; a collision returns a warn-and-confirm rather than overwriting. Moved here from `features/query/` by SPEC-185, because the Data Explorer's export needs it and may not import that feature. **`spaces` is a parameter**, not a `useQuerySpaces()` call inside: the hook's own list was unfiltered, so the Save-results dialog offered a colleague's space as a write target with `sharedWorkspaces` off. Both views now gate it, and both have a registry row. |
| `SaveResultsDialog` | `SaveResultsDialog.tsx` | The destination picker + validated `.csv` file-name field, keyed per space so browsing state resets. Moved with the hook (SPEC-185). |
| `normalizeCsvName(name)` | `catalog.format.ts` | Appends `.csv` unless already typed (case-insensitively), never doubling it. Moved from `features/query/query.format.ts`, which held nothing else and is gone. |
| `normalizeColumnType(type)` | `catalog.format.ts` | Maps Athena/Presto engine type names (`varchar`, `integer`) back to the Glue/Hive names the schema rail shows, so a column reads the same in the results header as in the catalog. |
| `QueryState`, `QueryStatus`, `QueryColumn`, `QueryResultPage`, `GlueColumn`, `GlueTableSummary`, `DatabaseSchema`, `QuerySpace` | `catalog.types.ts` | The execution, result-page, Glue and space types. `DatabaseSchema` lives here rather than beside the completion provider that consumes it, because `useAllSchemas` produces it and a catalog module may not import a leaf feature (SPEC-176 FR-001). |
| `POLL_INTERVAL_MS`, `MAX_POLL_DURATION_MS`, `DEFAULT_MAX_ROWS`, `ROW_COUNT_PAGE_SIZE`, `DEFAULT_COLUMN_WIDTH`, `MIN_COLUMN_WIDTH`, `MAX_COLUMN_WIDTH`, `COLUMN_RESIZE_STEP_PX` | `catalog.constants.ts` | Athena's polling cadence and guard, the service-level page size, the row-count walk's page size, and result-column sizing. The **display** page-size constants are a workspace preference (SPEC-087) and stay in `features/query/`. |
