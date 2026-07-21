# Query feature (`apps/portal/src/features/query/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


Public barrel: `features/query/index.ts`. Data layer for the Athena query workspace (SPEC-034); **no UI** (SPEC-035/036 build it). All services return `ServiceResult<T>`, never throw.

### Services

| Symbol | File | Purpose |
|---|---|---|
| `runQuery({ sql, database, username, outputLocation? })` | `query.service.ts` | `StartQueryExecution` against the shared workgroup. `outputLocation` omitted → the caller's own `{username}/athenaresults/`; pass a shared path for a shared-DB query (SPEC-055). Type-agnostic (SELECT + DDL). `ServiceResult<{ queryExecutionId }>`. |
| `getQueryStatus(id)` | `query.service.ts` | `GetQueryExecution` → `QueryStatus` (state/reason/stats/outputLocation). |
| `getQueryResults({ queryExecutionId, nextToken?, maxRows? })` | `query.service.ts` | `GetQueryResults` → typed `QueryResultPage` (first-page header row stripped; paginates via `nextToken`). DDL → empty page. |
| `getResultCsvUrl({ queryExecutionId, outputLocation })` | `query.service.ts` | Presigned CSV download of the raw result object (reuses `getDownloadUrl`). `ServiceResult<DownloadUrl>`. |
| `stopQuery(id)` | `query.service.ts` | `StopQueryExecution` → CANCELLED. |
| `isTerminalState(state)` | `query.service.ts` | Is a `QueryState` terminal (SUCCEEDED/FAILED/CANCELLED)? |
| `getDatabase(name)` / `listTables(name)` | `glue.service.ts` | The user's own Glue DB + its tables/columns (paginated). Missing DB → `NotFound` / empty list, never thrown. |
| `getQueryHistory(username)` / `appendQueryHistory(username, entry)` / `updateQueryHistoryEntry(username, id, patch)` | `queryHistory.service.ts` | Per-user history JSON at `{username}/user_settings/query-history.json` — read (missing/corrupt → empty), prepend+cap, in-place update. PutObject-only (no delete); read-only to the user. |

### Hooks, keys, types, constants

| Symbol | File | Purpose |
|---|---|---|
| `useQueryExecution(id \| null)` | `useQueryExecution.ts` | Polls `getQueryStatus` via `refetchInterval` until terminal or `MAX_POLL_DURATION_MS`; disabled when null. |
| `useQueryResults(id \| null, maxRows?)` | `useQueryResults.ts` | Prev/Next pager over results via `useInfiniteQuery` (20 rows/page, SPEC-038): exposes the current page's `columns`/`rows`, `pageIndex`/range, `hasPrev`/`hasNext`, `goPrev`/`goNext` (Next fetches forward, Prev from cache), and loaded/total counts. |
| `useResultRowCount(id \| null)` | `useResultRowCount.ts` | Background page-walk that counts a succeeded query's exact total rows via `GetQueryResults` (free, no extra scan) at `ROW_COUNT_PAGE_SIZE`, keyed on the execution id (separate from the visible pager key so it never perturbs it); returns `{total, isCounting, atCeiling}`, stops at `ROW_COUNT_CEILING`, degrades to `null` on a failed page, recomputes on id change. Pass `null` to disable (in-flight / DDL / no result set) — SPEC-080. |
| `useColumnWidths(executionId, columnCount)` | `useColumnWidths.ts` | In-memory `Record<executionId, number[]>` column-width store keyed by query execution id, so widths survive Prev/Next paging **and** query-tab switches; exposes the current execution's `widths`/`setWidth` (clamped ≥ `MIN_COLUMN_WIDTH`)/`resetColumn`; render-phase seed → defaults for a new id (within an entry, keyed by column index). Called in `QueryWorkspace` (above the table that unmounts), outputs passed down (SPEC-064). |
| `useEditorLayout(username \| null, containerHeight)` | `useEditorLayout.ts` | SPEC-079 editor/results layout preset (`editor`/`even`/`results`): per-user `sessionStorage` persistence (degrade-safe, default `even`) + the editor pane's derived px height, capped at `container − MIN_RESULTS_HEIGHT` then floored at `MIN_EDITOR_HEIGHT` (editor floor wins on short viewports); `clampEditorHeight` exported for reuse/tests. |
| `useSchema(db \| null)` + `invalidateSchema(client, db)` | `useSchema.ts` | DB + tables for the schema browser; invalidation helper to refresh after DDL. |
| `useAllSchemas(databaseNames)` | `useSchema.ts` | Loads every accessible database's schema at once (`useQueries`, shares `useSchema`'s per-DB cache keys) → `DatabaseSchema[]` for multi-database autocomplete; failed DBs omitted (SPEC-077). |
| `useQueryHistory(username \| null)` | `useQueryHistory.ts` | History list + `appendEntry`/`updateEntry` mutations (cache-seeding). |
| `getSavedQueries` / `upsertSavedQuery` / `removeSavedQuery` | `savedQueries.service.ts` | Per-user saved-queries JSON store at `{username}/user_settings/saved-queries.json`; PutObject overwrite only (remove rewrites, never an S3 delete), missing-file → empty store, `ServiceResult` (SPEC-043). |
| `useSavedQueries(username \| null)` | `useSavedQueries.ts` | Saved-queries list + `upsert`/`remove` mutations (cache-seeding), `queryKeys.savedQueries` (SPEC-043). |

### Workspace UI (SPEC-035)

| Symbol | File | Purpose |
|---|---|---|
| `QueryWorkspace` | `QueryWorkspace.tsx` | Top-level `/query` composition: schema rail + toolbar + editor + status + results, wired to the SPEC-034 layer. Rendered by the lazy `QueryPage` route. |
| `SqlEditor` (+ `SqlEditorHandle`) | `SqlEditor.tsx` | Lazy, self-hosted Monaco SQL editor; `value`/`onChange`/`onRun` (⌘⏎), ref exposes `insertAtCursor`. |
| `SchemaBrowser` | `SchemaBrowser.tsx` | Left rail: a **browse-only tree** of `DatabaseNode`s (SPEC-063/077); props `{connections?, actions}` (no active-database selection). Renders unusable shared connections as static status rows. |
| `DatabaseNode` | `DatabaseNode.tsx` | One database in the rail (SPEC-063/077): disclosure node + per-node `useSchema` (fetched only when expanded) + two collapsible **Tables**/**Views** groups (counts + empty states). Browse-only — columns are non-interactive rows (no insert); per-table actions menu (View DDL/data/Drop) invoked with the node's database. Header **Refresh** `IconButton` (expanded nodes only) re-reads just this database via `invalidateSchema`, disabled/spinning on the node's `isFetching` (SPEC-086). |
| `partitionSchema(tables)` | `schema.partition.ts` | Pure split of Glue objects into `{tables, views}` (`tableType === 'VIRTUAL_VIEW'` → views); single source of truth for the rail's two groups (SPEC-063). |
| `QueryStatusBar` | `QueryStatusBar.tsx` | Slim live-region execution status (running/succeeded/failed/cancelled) + **Save results to my files** (`onSaveResults`/`canSaveResults`, shown only for a row-returning success — SPEC-049). |
| `SaveResultsDialog` / `DestinationSpace` (+ `normalizeCsvName` in `query.format.ts`) | `SaveResultsDialog.tsx` | Destination-space selector (personal + member-of shared spaces, SPEC-055) + folder `DestinationPicker` + validated filename modal; `onSave` returns `{destBucket, destPrefix, filename}` for a same- or cross-bucket full-result `copyObject`, `.csv`-normalized (SPEC-049). |
| `QueryResultsTable` | `QueryResultsTable.tsx` | File-table-styled results (dynamic columns + type, horizontal scroll, empty/loading state); shows one page at a time with a Prev/Next pager + "Rows X–Y" indicator (replace, not append — SPEC-038). Columns are **user-resizable** via `<colgroup>` + `table-fixed`, no-wrap + ellipsis + `title` on cells/headers; **controlled** — `widths`/`onResize`/`onResetColumn` come from the parent's `useColumnWidths` (SPEC-064). |
| `EditorLayoutControl` | `EditorLayoutControl.tsx` | Three-option segmented control (labeled `role="group"` + `aria-pressed` toggle buttons) snapping the editor/results vertical split to a preset; controlled `{preset, onChange}`, heights owned by the parent's `useEditorLayout` (SPEC-079). |
| `ColumnResizeHandle` | `ColumnResizeHandle.tsx` | Focusable `role="separator"` resize handle on a data-column header: pointer drag (clamped at `MIN_COLUMN_WIDTH`), double-click reset, Arrow Left/Right keyboard nudge by `COLUMN_RESIZE_STEP_PX`, column-naming `aria-label` (SPEC-064). |
| `QueryHistoryPanel` | `QueryHistoryPanel.tsx` | Right slide-over drawer listing per-user history (`useQueryHistory`); read-only, view/Open/Re-run; empty/loading/error states (SPEC-036). Client-side Prev/Next pager, 7/page newest-first, `"1–7 of N"`, reset-to-newest on open/append (SPEC-042). Header **Refresh** control re-reads from S3 (`useQueryHistory.refresh`/`isRefreshing`); reset-to-newest on success, non-destructive on error (SPEC-046). |
| `QueryHistoryRow` | `QueryHistoryRow.tsx` | One history entry: status badge, relative time, SQL preview, stats, Open/Re-run (SPEC-036). |
| `ClearQueryDialog` | `ClearQueryDialog.tsx` | Warn-and-confirm modal for the Clear-query action (SPEC-026 pattern; `alertdialog`, Escape/backdrop cancel, no undo) (SPEC-040; scoped to the active tab under SPEC-041). |
| `readTabsState` / `writeTabsState` / `initialTabsState` / `migrateDraftToTabs` | `queryTabs.ts` | Per-user `sessionStorage` wrapper for the multi-tab editor state (`s3portal.query.tabs.{username}`); structural validation (corrupt → null), error-swallowing, empty-username no-op, one-time SPEC-040 draft migration (SPEC-041; supersedes the removed `queryDraft.ts`). |
| `useConnections(username)` | `useConnections.ts` | **The** source of databases the user can query (`Connection[]` + `refresh`/`isRefreshing`): merges the personal DB with shared entries read from the per-user cache (personal first, shared A–Z); `refresh` forces a credential refresh then refetches; missing/corrupt cache → personal-only. One hook feeds the schema rail, Files list, and Connections tab (SPEC-047/052). |
| `Connection` / `ConnectionKind` / `isConnectionUsable` | `query.types.ts` | `{id,label,database,kind:'personal'\|'shared',status?,role?,reason?,members?}` — a targetable database; `members?` is the owner-readable projection (SPEC-053); `isConnectionUsable` = personal or `active` shared (SPEC-047/052). |
| `useQueryTabs(username)` | `useQueryTabs.ts` | Owns `QueryTabsState` + persistence; `openTab({label?,sql?,savedQueryId?})` (returns id or **null at `QUERY_TABS_MAX`**; named tabs skip the `Query N` counter), monotonic labelling, `closeTab` (≥1-tab + adjacent-activate), `setActiveSql`/`setActiveTab`/`setActiveSavedQueryId`/`clearActive` (SPEC-041). |
| `QueryTabStrip` | `QueryTabStrip.tsx` | Card-tab strip above the editor: active = surface+border+accent dot, per-tab `×` (hidden when solo), always-enabled `+` (SPEC-041 §6). |
| `TabLimitDialog` / `CloseTabDialog` | `TabLimitDialog.tsx` / `CloseTabDialog.tsx` | FR-008 "close a tab first" alert; FR-005 warn-and-confirm before closing a non-empty tab (both SPEC-026 pattern) (SPEC-041). |
| `SavedQueriesPanel` | `SavedQueriesPanel.tsx` | Right drawer (mirrors history) listing saved queries (most-recently-updated first) with Open + Delete-with-confirm; presentational (workspace owns the data) (SPEC-043). |
| `SaveQueryDialog` | `SaveQueryDialog.tsx` | Name-prompt modal with an inline overwrite-confirm step on a name collision; pre-filled on re-save (SPEC-043). |
| `SavedQuery`, `SavedQueriesStore` | `query.types.ts` | Saved-query record + store types; `QueryHistoryEntry` also gained optional `savedQueryId`/`savedQueryName` (SPEC-043). |
| `TableActionsMenu` | `TableActionsMenu.tsx` | Query schema-rail kebab (⋮) — now composes the shared `Menu` primitive (SPEC-095); maps `TableMenuItem[]` (`danger`/`separatorBefore`) onto `Menu` items, behavior unchanged (SPEC-044). |
| `Toast` (+ `ToastState`) | `Toast.tsx` | **Reusable** minimal transient toast (success/danger auto-dismiss; `info` persists), accessible live region, fixed bottom-right; optional inline `action` (e.g. "View in Files"; suppresses auto-dismiss) (SPEC-044/049). |
| `DropTableDialog` | `DropTableDialog.tsx` | DROP TABLE / DROP VIEW warn-and-confirm (SPEC-026 alertdialog, danger, in-flight lock); `isView` switches the copy/labels (SPEC-044/048). |
| `CreateViewDialog` | `CreateViewDialog.tsx` | Name-prompt modal for Create view; validates the catalog-safe identifier rule; busy-locks while the background `CREATE OR REPLACE VIEW` runs (SPEC-048). |
| `getTableDdl` / `runStatementToCompletion` | `query.service.ts` | `SHOW CREATE TABLE` (or `SHOW CREATE VIEW` when `isView`) → assembled DDL; run-and-poll-to-terminal helper for background statements (View DDL, Drop, Create view) (SPEC-044/048). |
| `CATALOG_IDENTIFIER_RE` / `stripTrailingSemicolons` | `query.constants.ts` / `query.sql.ts` | Shared catalog-safe identifier rule (`^[a-z][a-z0-9_]{2,62}$`, = SPEC-033 username rule); strip trailing `;`/whitespace for embedding a SELECT as a view body (SPEC-048). |
| `QueryTab`, `QueryTabsState`, `QUERY_TABS_MAX`, `DEFAULT_SQL` | `query.types.ts` / `query.constants.ts` | Tab data types, the soft tab cap, and the shared first-tab boilerplate (SPEC-041). |
| `formatBytes` / `formatDurationMs` / `formatRelativeTime` | `query.format.ts` | Display formatters for scanned-bytes / duration / relative timestamps. |
| `queryKeys` | `queryKeys.ts` | Key factory (`schema`/`execution`/`results`/`history`/`savedQueries`/`connections`) — never hand-build keys. |
| `QueryState`, `QueryStatus`, `QueryColumn`, `QueryResultPage`, `GlueColumn`, `GlueTableSummary`, `QueryHistoryEntry`, `QueryHistory` | `query.types.ts` | Feature data types. |
| `POLL_INTERVAL_MS`, `MAX_POLL_DURATION_MS`, `DEFAULT_MAX_ROWS`, `QUERY_HISTORY_MAX` | `query.constants.ts` | Polling cadence/guard, default page size, history cap. |

