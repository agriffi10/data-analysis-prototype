# Data Explorer feature (`apps/portal/src/features/data-explorer/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

Public barrel: `features/data-explorer/index.ts`. Look at a table without writing SQL: a user's
grid gestures are a **description of a query**, and the app renders that description and runs it.

**SPEC-179 mounted the first surfaces**: the `/explore` route, the source picker, the tab strip
and a **placeholder results table SPEC-180 replaces with the real grid**. The engine shipped first
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
| `ExplorationResultsTable` | `ExplorationResultsTable.tsx` | **A PLACEHOLDER SPEC-180 replaces.** Columns, rows and the shared `Pager` over `useQueryResults`; errors through `ErrorBanner`. No resize, reorder, pin, hide or selection — none of that is missing, it has not been built. |
| `ExplorationLimitDialog` | `ExplorationLimitDialog.tsx` | The `openTab` → `null` refusal, said out loud. Dismiss-only; the `+` stays enabled so the reason is reachable. |
| `useExploreDeepLink(spaces, username, sharedEnabled)` | `useExploreDeepLink.ts` | `?space=&db=&table=` → a resolution plus `clear()`. Waits for the connections list **only when a `?space=` is present**, and drops the parameters (replacing the history entry) once acted on, so a reload restores the session's tabs instead of stacking a duplicate. |
| `resolveExploreParams(params, spaces, username, sharedEnabled)` / `spaceDatabase(space, username)` | `exploreSources.ts` | The precedence rules, pure: the actor's own username always resolves **personal** (SPEC-113), `?space=` is **not read at all** with `sharedWorkspaces` off, an unreachable NAMED space is `denied` while anything malformed is `none` (the picker). `spaceDatabase` is the one definition of the space↔database mapping. |

### Types & constants

| Symbol | File | Purpose |
|---|---|---|
| `Exploration`, `ExplorationSource`, `ExplorationQuery`, `ExplorationPresentation` | `dataExplorer.types.ts` | Source + query description + presentation, as **three separate fields** — never a flattened bag, so the renderer's parameter list can exclude one. `ExplorationSource` is a union (`table` \| `sql`) from the outset; only `table` is reachable until SPEC-183, because retrofitting it later would touch every spec in between. |
| `ColumnFilter`, `FilterOperator`, `FilterValueKind`, `SortEntry`, `Grouping`, `GroupingAggregate`, `AggregateFunction` | `dataExplorer.types.ts` | The query dimensions. `valueKind` (`'string'` default \| `'number'`) exists because **Trino does not coerce** — `WHERE "qty" > '5'` against a bigint is a query-time error. SPEC-181 picks it from the column's Glue/Athena type. |
| `ExplorationTab`, `ExplorationTabsState`, `ExecutionCost` | `dataExplorer.types.ts` | A tab and its cost ledger; what one execution scanned. |
| `EXPLORATION_TABS_MAX`, `EXPLORATION_PAGE_SIZE`, `SQL_SOURCE_ALIAS`, `EXPLORATION_TABS_STORAGE_PREFIX` *(internal)* | `dataExplorer.constants.ts` | Ten tabs (mirrors `QUERY_TABS_MAX`); 100 rows a page — FIXED, unlike the Query workspace's user-controlled size, because paging an execution scans no additional bytes and there is nothing to trade off; the per-user storage prefix; the `sql` arm's subquery alias. |
