# Data Explorer feature (`apps/portal/src/features/data-explorer/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

Public barrel: `features/data-explorer/index.ts`. Look at a table without writing SQL: a user's
grid gestures are a **description of a query**, and the app renders that description and runs it.

**SPEC-179 mounted the first surfaces** (the `/explore` route, the source picker, the tab strip) and
**SPEC-180 replaced its placeholder table with the real grid**: column geometry, a cell cursor with
range selection, the Value panel, and the Record and Text presentations. The engine shipped first
(SPEC-178) because it settles the exploration model and the app's only SQL-value interpolation
point.

> Composes `features/catalog/` (the Glue reader, the Athena execution/results layer) and
> `features/saved-queries/` (the `.sql` store, from SPEC-183). It may **not** import
> `features/query/`, and `features/query/` may not import it — enforced by the ESLint layering
> rule (SPEC-176), which this spec is the first to exercise against real files.

### The rule everything else follows

`renderExplorationSql(source, query)` takes the source and the query description **and nothing
else**. Filters, the expression, ordering and grouping render SQL; column visibility, order,
pinning, width, colour and transformers are *presentation* and render nothing, so they cost
nothing and apply instantly. That is structural — a function that cannot reach presentation state
cannot be made to depend on it by a later edit — and `sqlBuilderSweep.test.ts` forbids a second
builder in the feature.

### Model & rendering

| Symbol | File | Purpose |
|---|---|---|
| `renderExplorationSql(source, query)` | `renderExplorationSql.ts` | The ONE SQL builder. `table` → `FROM "db"."tbl"`, `sql` → `FROM (\n<body>\n) AS t` (the newlines are load-bearing — a body ending in a `--` comment would otherwise swallow the closing paren and the alias); filters, expression, ordering and grouping compose identically over either arm. `SELECT *` unless grouping, no trailing semicolon. Throws `ExplorationRenderError` for a description that cannot render — a valueless comparison, a non-numeric numeric value, an invalid or ambiguous grouping, or an ORDER BY Trino would reject. (Trino rejects that last one at ANALYSIS, scanning nothing and billing nothing — what refusing here buys is immediacy, not money: the gesture is refused where the user made it instead of returning an engine error SPEC-106 forbids rendering.) |
| `ExplorationRenderError` | `renderExplorationSql.ts` | The refusal. Its message is **operator text** and names the offending column — SPEC-106 forbids rendering it to a user. |
| `aggregateAlias(aggregate)` | `renderExplorationSql.ts` | The column name an aggregate produces (`COUNT(*)` → `count_all`), and the name an `ORDER BY` may reference. Exported so SPEC-182's panel labels a column with the name the SQL actually emits. |
| `newExploration(source, id?)` / `newExplorationId()` / `emptyExplorationQuery()` / `emptyExplorationPresentation()` / `explorationSourceLabel(source)` | `exploration.ts` | The model's constructors — one definition of what "empty" means, so two surfaces cannot disagree about whether `expression` starts `null` or `''`. |

### Execution & cost

| Symbol | File | Purpose |
|---|---|---|
| `useExploration(exploration \| null)` | `useExploration.ts` | Renders, runs and reports: `{sql, queryExecutionId, state, cost, isPending, error}`. **The rendered SQL is the cache key**, so an identical description is a cache hit rather than a second bill and toggling a sort back costs nothing. Paging is NOT here — the caller pages the execution id through SPEC-176's `useQueryResults`, whose `NextToken` walk scans no extra bytes. A FAILED/CANCELLED execution is evicted **on the way out** (statement change or unmount), never on observing the failure: evicting while mounted refetches immediately, an unbounded loop against StartQueryExecution (AWS does not bill a FAILED query, but this branch also covers CANCELLED, which IS billed for what it scanned). `gcTime: Infinity` is as load-bearing as `staleTime` — under the 5-minute default the cache promise silently expires and the return trip becomes a second execution. |
| `explorerKeys` | `explorerKeys.ts` | Key factory (`all` / `execution(sql)`), rooted at `['data-explorer']` — never hand-build keys. |

### Tab state

| Symbol | File | Purpose |
|---|---|---|
| `useExplorationTabs(username)` | `useExplorationTabs.ts` | Ordered tabs, one active, `sessionStorage` persistence per user, and `openTab` returning **null** at `EXPLORATION_TABS_MAX` so the caller can raise the cap dialog (SPEC-179 renders it). Starts with **no tabs**, unlike `useQueryTabs`' seeded "Query 1" — an exploration needs a source and there is none to guess. `activeTabId` always references an existing tab, or `''` for the legal empty state. |
| `readExplorationTabsState` / `writeExplorationTabsState` / `initialExplorationTabsState` **(internal — not on the barrel)** | `explorationTabs.ts` | The degrade-safe persistence behind it; a corrupt, old or foreign document is discarded **whole**, never partially applied — a half-restored exploration renders SQL from a description the user never built. Validation goes past shape to the fields the renderer BRANCHES on (filter operators, `valueKind`, sort direction, aggregate functions, and that every ledger value is a finite number), because "restorable" is not "renderable": an unknown operator renders `"a" undefined 'x'` and reaches StartQueryExecution. |
| `tabBytesScanned(tab)` | `explorationTabs.ts` | A tab's cumulative bytes, summed from a ledger keyed by **execution id**. That keying is what makes "a cache hit adds nothing" true by construction: a running total would have to *detect* a hit, and a detector can be wrong in the direction that overcharges. |

### Surfaces (SPEC-179)

| Symbol | File | Purpose |
|---|---|---|
| `DataExplorerWorkspace` | `DataExplorerWorkspace.tsx` | The page: picker, tab strip, one exploration's rows, the cap dialog, and the `sharedWorkspaces` filter applied **at the view**. Renders `LoadingState` while a `?space=` link resolves and the refusal ALONE when it is denied — the picker reads a database on mount, so an optimistic render would ask Glue about the wrong space (SPEC-113). |
| `SourcePicker` | `SourcePicker.tsx` | Space on the left, that space's tables **and views** on the right. **No database step**: a space maps to exactly one database, so the control would have one option. Explains itself when there is no usable space. |
| `ExplorationTabStrip` | `ExplorationTabStrip.tsx` | Tabs, `+` and close, with the WAI-ARIA roving-tabindex model. Mirrors the Query strip's shape rather than sharing it (sibling features), and never hides the close control — zero tabs is legal here. |
| `ExplorationResultsRegion` | `ExplorationResultsRegion.tsx` | One exploration's rows: the toolbar, the chosen presentation, the Value panel and the pager. Owns the page, the geometry and the selection so the three views stay presentational. Errors through `ErrorBanner` (SPEC-106) — neither Athena's text nor an `ExplorationRenderError`'s reaches a user. |
| `ExplorationLimitDialog` | `ExplorationLimitDialog.tsx` | The `openTab` → `null` refusal, said out loud. Dismiss-only; the `+` stays enabled so the reason is reachable. |
| `useExploreDeepLink(spaces, username, sharedEnabled)` | `useExploreDeepLink.ts` | `?space=&db=&table=` → a resolution plus `clear()`. Waits for the connections list **only when a `?space=` is present**, and drops the parameters (replacing the history entry) once acted on, so a reload restores the session's tabs instead of stacking a duplicate. |
| `resolveExploreParams(params, spaces, username, sharedEnabled)` / `spaceDatabase(space, username)` | `exploreSources.ts` | The precedence rules, pure: the actor's own username always resolves **personal** (SPEC-113), `?space=` is **not read at all** with `sharedWorkspaces` off, an unreachable NAMED space is `denied` while anything malformed is `none` (the picker). `spaceDatabase` is the one definition of the space↔database mapping. |

### The grid (SPEC-180)

| Symbol | File | Purpose |
|---|---|---|
| `ExplorationGrid` / `ExplorationGridHeader` | `ExplorationGrid.tsx`, `ExplorationGridHeader.tsx` | `role="grid"` over the current page: a sticky pinned block, row numbers, a drag grip and a `ColumnResizeHandle` per header. A cell is addressed by (row on the page, column NAME) and reads `row[column.index]`, so display order is free to differ from the execution's. Cells carry an explicit `role="gridcell"` — several accessibility APIs resolve a bare `td` as `cell`, a role with no selected state. |
| `useColumnGeometry(columns, presentation, onChange)` | `useColumnGeometry.ts` | Resolves the tab's presentation against the columns the result actually has → `visible`/`all` plus `setWidth`/`resetWidth`/`toggleHidden`/`togglePinned`/`move`/`moveTo` and the two refusal readers. **Keyed by column NAME**, which is what makes "geometry for a column this result no longer has is discarded" true by construction. Reuses `features/catalog/`'s sizing constants, NOT `useColumnWidths` (index-keyed, per-execution, in-memory). |
| `useCellSelection(rowCount, columns, resetKey)` | `useCellSelection.ts` | The cursor and selection: `ranges` is a list of inclusive rectangles and **the last one is live** (its `from` is the Shift anchor, its `to` the cursor). Pointer, keyboard, whole column, whole row, Ctrl/Cmd+A over the LOADED page, and the WAI-ARIA Space bindings (Ctrl/Cmd+Space = column, Shift+Space = row) so the header and row-number clicks have a keyboard path. Focus follows the cursor by looking the `data-cursor` cell up in the committed DOM — a per-cell ref detaches and attaches in an order React does not promise, and the first keyboard move read a nulled one. Keys arriving from anything but a gridcell are ignored, so the resize handles inside the grid keep their Arrows. `resetKey` changes with the page or the column set and resets during render — an effect would paint one frame of stale coordinates over new rows. The substrate SPEC-182 aggregates over and SPEC-185 copies. |
| `ColumnsPanel` | `ColumnsPanel.tsx` | Hide/show, pin and **Move earlier/later** — the keyboard alternative to dragging a header, announced in a live region. A panel rather than a header menu because SPEC-181 owns the per-column menu. Every refusal rides `Button.disabledReason` (`aria-disabled`, reason in the tab order, never inside the button). |
| `ValuePanel` | `ValuePanel.tsx` | The focused cell's complete value in a read-only `<textarea>` — selectable and copyable, **not focus-trapping**, Escape through the depth-ordered registry. `undefined` (no cell focused) is said in words, never as `NULL`: telling those apart is the panel's job. One tree reflowing: a bottom sheet below `tablet`, a column beside the grid above it. |
| `ExplorationRecordView` / `ExplorationTextView` / `PresentationSwitch` | `*.tsx` | The transposed row (Next/Previous within the page; the default below `tablet`), the fixed-width text rendering of the page, and the Grid/Record/Text control. None of them runs a query. |
| `CellValue` / `cellText(value)` / `NULL_DISPLAY` / `EMPTY_DISPLAY` | `CellValue.tsx`, `cellText.ts` | **NULL and the empty string, told apart** (FR-003 AC5). Athena returns every value as a string; `getQueryResults` now keeps the difference (`null` vs `''`) and this is where it becomes visible, as text rather than as styling. |
| `useSourceColumns(source \| null)` | `useSourceColumns.ts` | The columns a source is known to have before any execution returns: Glue's, for a `table` source (through `features/catalog/`'s cached schema); **empty for `sql`**, whose columns arrive only with `ResultSetMetadata`. The execution's own metadata always wins once it lands — a grouping change replaces the column set wholesale. |

### Types & constants

| Symbol | File | Purpose |
|---|---|---|
| `GridPresentation`, `CellRef`, `CellRange`, `CellSelection` | `dataExplorer.types.ts` | The grid's own model (SPEC-180). `CellSelection` rather than the spec's `Selection`: that name is a DOM global and would shadow `window.getSelection()`'s type wherever both are in scope. `ExplorationPresentation.presentation` is `GridPresentation \| null`, where **null means unchosen** — that is what lets the viewport pick Record below `tablet` without a tab being born knowing how wide the window is. |
| `Exploration`, `ExplorationSource`, `ExplorationQuery`, `ExplorationPresentation` | `dataExplorer.types.ts` | Source + query description + presentation, as **three separate fields** — never a flattened bag, so the renderer's parameter list can exclude one. `ExplorationSource` is a union (`table` \| `sql`) from the outset; only `table` is reachable until SPEC-183, because retrofitting it later would touch every spec in between. |
| `ColumnFilter`, `FilterOperator`, `FilterValueKind`, `SortEntry`, `Grouping`, `GroupingAggregate`, `AggregateFunction` | `dataExplorer.types.ts` | The query dimensions. `valueKind` (`'string'` default \| `'number'`) exists because **Trino does not coerce** — `WHERE "qty" > '5'` against a bigint is a query-time error. SPEC-181 picks it from the column's Glue/Athena type. |
| `ExplorationTab`, `ExplorationTabsState`, `ExecutionCost` | `dataExplorer.types.ts` | A tab and its cost ledger; what one execution scanned. |
| `EXPLORATION_TABS_MAX`, `EXPLORATION_PAGE_SIZE`, `ROW_NUMBER_COLUMN_WIDTH`, `TEXT_VIEW_MAX_COLUMN_CHARS`, `SQL_SOURCE_ALIAS`, `EXPLORATION_TABS_STORAGE_PREFIX` *(internal)* | `dataExplorer.constants.ts` | Ten tabs (mirrors `QUERY_TABS_MAX`); 100 rows a page — FIXED, unlike the Query workspace's user-controlled size, because paging an execution scans no additional bytes and there is nothing to trade off; the per-user storage prefix; the `sql` arm's subquery alias. |
