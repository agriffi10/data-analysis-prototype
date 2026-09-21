# Spec: A Query Result Opens in Data Explorer, and a Selection of Statements Gets a Tab Each

**ID:** SPEC-242
**Status:** Completed
**Last Updated:** 2026-09-21
**Depends On:** SPEC-078, SPEC-178, SPEC-179, SPEC-183, SPEC-238

## Overview

A tester asked for the Query workspace to work like a script: write several statements, run one,
some or all of them, and see each result in a grid like the Data Explorer's. Most of that already
exists. **Run Statement** runs a selection or the statement under the cursor, and **Run Multiple
Queries** gives each statement its own result tab. Two gaps remain. Selecting several statements
and choosing **Run Statement** runs them all but shows only the last result. And a result can't be
filtered, grouped, coloured or trimmed to fewer columns the way a Data Explorer table can, which
another tester wants so they can hide columns before exporting.

This spec gives a multi-statement selection one result tab per statement, and adds **Explore in
Data Explorer** to a query result. That opens a Data Explorer tab whose source is the statement
itself, so every Data Explorer tool works on it. It is the first surface to open a Data Explorer
tab from SQL rather than from a table, so it also makes that kind of tab work end to end.

### What was checked, and how

Read from the code at `73c66eef`.

- **A multi-statement selection shows its last result.** `handleRunStatement` in
  `features/query/QueryWorkspace.tsx` submits `resolveRunStatements(…)` with scope `'statement'`.
  `resolveRunStatements` (`query.sql.ts`) re-splits a non-empty selection into every statement in
  it. `displayedResultTab` shows `resultTabs[activeResultTabIndex]` only for `'script-tabs'`, and the
  last result tab otherwise. `useTabRuns` accumulates result tabs in every scope, so the scopes differ
  only in display (`QueryToolbar.tsx` says the two whole-script scopes "differ only in how results
  are shown").
- **An exploration can already have SQL as its source.** `ExplorationSource` has a `sql` arm
  (`{kind: 'sql', body, label}`). `renderFrom` renders it as `(\n<body>\n) AS t`.
  `explorationTabs.ts` restores it, `useSourceColumns` returns no columns for it (so headers come
  from the execution), and `DataExplorerWorkspace` refuses *Create view* for it with an existing
  sentence. Nothing opens one: that refusal's comment says "No such source ships today".
- **The Explorer opens a table from a link, once.** `useExploreDeepLink` resolves
  `/explore?space=&db=&table=`, and `DataExplorerWorkspace` opens the tab through `openTab`, raises
  `ExplorationLimitDialog` when `openTab` returns null, and clears the parameters with `replace`, so
  a reload does not open it again.
- **A Data Explorer capability on a Query surface is registered under both flags.**
  `gatedSurfaces.ts` lists *Explore data on the Query schema rail* under `query` and *Explore data*
  under `dataExplorer`, and `DatabaseNode.tsx` reads `useFeature('dataExplorer')`.
- **The run keeps each statement's text.** A batch's `statements` are `ParsedStatement`s with `sql`,
  and each `ResultTab` names its `statementIndex`. `statementHint(sql)` makes a short label.
- **Neither feature may import the other.** `eslint.config.js` forbids `features/query/` importing
  `features/data-explorer/` and the reverse, tests and `import type` included.
- **Save results sits in the status bar, gated on the result.** `QueryStatusBar.tsx` renders *Save
  results to my files* "gated on the result, never on the verdict", so a batch that failed after a
  succeeded statement still offers that statement's rows.
- **Execution metadata arrives with Glue's type names.** `athena.service.ts` maps Athena's names
  through `normalizeColumnType` (`catalog.format.ts`), so a `varchar` column reports `string` and an
  `integer` one `int`.
- **The registry walk needs distinct names.** `gatedSurfaces.test.tsx` compares the sorted list of
  row names with its recipe keys, so two rows cannot share a name.

### The decisions, made while authoring

- **A selection that resolves to more than one statement runs with the tab-per-statement scope.** A
  single statement, selected or under the cursor, keeps `'statement'`. Only the display changes,
  which is exactly what distinguishes the scopes. This supersedes SPEC-078's "one result view" for
  **Run Statement**, for a selection of several statements only. That spec modelled it on DBeaver's
  single result, and a tester has since asked for one result per statement.
- **The hand-off carries the statement's text, not the result.** The Data Explorer works by
  rendering SQL over its source, so exploring a result means running the statement again, wrapped.
  That is a billed execution, just as opening a table in the Explorer is. The alternative, filtering
  the stored result object, is a different engine and no tester asked for one.
- **A hand-off always runs the statement again.** Executions are cached by their rendered SQL for the
  session, so exploring the same statement a second time, after an `INSERT` for instance, would show
  the earlier rows, and so would every filter, sort or grouping later applied over it. The invariant:
  after a hand-off is accepted, no row cached before it is shown for that statement or any
  description over it, and no other tab's statement starts again. Consuming a hand-off therefore
  removes, with `removeQueries` and only after `openTab` returns an id, every cached execution under
  `explorerKeys.sqlSources()` whose rendered SQL reads from that statement's own subquery,
  `FROM (\n<body>\n) AS t`. Resetting the whole prefix would re-run, and bill, other `sql` tabs, and
  removing only the unfiltered form would serve the first filter re-applied from stale rows.
- **A result whose columns cannot be named is not explorable.** Athena names an unaliased expression
  `_col0`, and the outer query cannot refer to it. A join that selects `a.id` and `b.id` returns two
  columns called `id`, which the outer query cannot tell apart and the grid's name-keyed geometry
  cannot either. Refusing the hand-off, with a reason saying to add `AS`, costs the user one edit.
  Offering the tab and refusing per column would leave some gestures working and others not.
- **A `sql` tab remembers its source's columns.** A table tab's Grouping panel lists the Glue schema,
  and a `sql` source has none. So the tab records the column list of its latest ungrouped execution
  as `sqlSourceColumns`, persisted with the tab, and `useSourceColumns` returns it for a `sql` source.
  Every ungrouped run of one body reports the same list, so recording each one costs nothing and
  keeps the list right if the tables under the statement change shape. *(Revised during the build:
  the draft recorded only the first.)*
- **The hand-off's shape lives in `lib/`.** Neither feature can import the other, so
  this spec creates `lib/routeHandoff.ts` with this hand-off's type, builder and reader, and SPEC-243
  adds its own beside them. One module owns each shape, and its tests pin the round trip.
- **This spec widens `renderWithProviders`.** Testing the Explorer side of a hand-off needs router
  state, so its `route` accepts `{pathname, state}` here, where it is first needed. The Query
  workspace's own helper, `renderWorkspace` in `src/test/queryWorkspaceSupport.tsx`, is widened by
  SPEC-243, whose Query-side test needs it. *(Added during the build:)* it also gains `strictMode`,
  because a `<StrictMode>` passed in as the element under test runs every effect ONCE — React
  double-runs effects only under the StrictMode it places — so the StrictMode criterion below could
  not fail. Measured, and caught by mutating the `location.key` guard, which stayed green.
- **The button follows *Save results*.** It is gated on the displayed result, not the batch
  verdict, in every run scope the editor owns.
- **The text comes from the run, not the editor.** The buffer may have changed since the run. The
  statement handed over is the one whose result is on screen.
- **Only `SELECT`, `WITH` and `VALUES` statements are explorable.** Those are the statements Trino
  accepts as a subquery. `SHOW`, `DESCRIBE` and `EXPLAIN` produce result tabs but cannot be wrapped,
  so they get no control. The check reads the first keyword after comments and whitespace, the way
  `isResultProducingSql` does.
- **The hand-off travels in router state, never the URL.** A statement can be long and can quote the
  user's data, and a URL is kept in history and logs. The Explorer consumes the state once and
  replaces the entry with no state, so a reload or Back does not open a second tab.
- **The Query side computes the label.** The Explorer may not import `features/query/`, so the Query
  side sends `statementHint(statement)` as the source's `label`.
- **The history state is cleared whenever a hand-off is accepted**, including when the tab limit
  refuses the tab, as the deep link clears its parameters either way. Otherwise a reload would raise
  the limit dialog again. A mount with no hand-off state replaces nothing, so `useExploreDeepLink`'s
  parameters are never touched by it.
- **Trailing semicolons are stripped before the hand-off** with `stripTrailingSemicolons`, because
  `(SELECT 1;) AS t` is not valid SQL.

## Scope

### In Scope

- A multi-statement **Run Statement** selection shows a result tab per statement (FR-001).
- `isExplorableSql` and the **Explore in Data Explorer** control on the Query results (FR-002).
- The hand-off, opening the tab once, and the tab limit (FR-003).
- A `sql`-source tab working end to end (FR-004).
- The registry rows and the Query and Data Explorer guides (FR-005).

### Out of Scope

- **Hiding columns or colouring cells in the Query workspace's own results grid.** Exploring the
  result gives both, without a second grid implementation.
- **Filtering the stored result without re-running.**
- **The Query workspace's mobile surface** (`QueryMobileView`).
- **Opening a saved `.sql` file** as an exploration source, and linking the new tab to a saved query.
- **Sending a result from the Data Explorer back to Query.** SPEC-243 opens the Explorer's generated
  SQL in Query.
- **Create view from a `sql`-source tab.** The existing refusal stands, reworded to cover SQL
  opened from a query.
- **Per-column refusals for unnamed or duplicate result columns.** The hand-off is refused instead.

---

## Functional Requirements

### FR-001: A multi-statement selection gets a result tab per statement

#### Description:

`handleRunStatement` submits with scope `'script-tabs'` when `resolveRunStatements` returns more
than one statement, and `'statement'` otherwise. The result-tab strip, the displayed result, Save
results and the status bar then behave as they do for **Run Multiple Queries**.

#### Acceptance Criteria:

- [ ] A buffer of three `SELECT`s with the first two selected: **Run Statement** runs two
  executions, and after both succeed the results region shows a result-tab strip with two tabs, the
  second selected (the index follows the latest result, as it does for **Run Multiple Queries**),
  whose grid holds the second statement's rows.
- [ ] Selecting the first tab shows the first statement's rows, and *Save results* saves that
  execution's output.
- [ ] A selection holding one statement shows no result-tab strip, as today.
- [ ] With no selection, the cursor in the second statement runs only it and shows no strip.
- [ ] A selection of two statements where the first fails stops the batch, as every scope does
  today, and shows that failure.

### FR-002: Explore in Data Explorer is offered on an explorable, succeeded result

#### Description:

`query.sql.ts` exports `isExplorableSql(sql)`: true when the first keyword after leading whitespace
and comments is `SELECT`, `WITH` or `VALUES`, case-insensitively. `QueryStatusBar` renders an
**Explore in Data Explorer** button beside *Save results to my files* when all of these hold: both
the `query` and `dataExplorer` flags are on; the displayed result is a succeeded execution, whatever
the batch's verdict; the statement that produced it, taken from the run's `statements`, is
explorable; and the editor owns the run (`editorOwnsRun`). This applies in every run scope.

The button carries `disabledReason` "Give every column its own name with AS to explore this
result." when the displayed result's columns include a name matching `^_col\d+$`, or two names equal
once lowercased.

#### Acceptance Criteria:

- [ ] `isExplorableSql` is true for `select 1`, `-- note\nWITH x AS (SELECT 1) SELECT * FROM x` and
  `/* a */ VALUES (1)`, and false for `SHOW TABLES IN db`, `DESCRIBE db.t`, `EXPLAIN SELECT 1`,
  `CREATE TABLE …` and `''`.
- [ ] After a succeeded `SELECT` the button is present, and after a succeeded `SHOW TABLES` it is not.
- [ ] In a two-tab result where tab 1 is a `SELECT` and tab 2 a `DESCRIBE`, the button is present
  on tab 1 and absent on tab 2.
- [ ] A two-statement selection whose second statement fails displays the first statement's result,
  and the button is present, as *Save results* is.
- [ ] A single failed statement shows no button, and while a batch runs there is none.
- [ ] With `dataExplorer` off, once *Save results to my files* is present after a succeeded `SELECT`,
  the button is absent.
- [ ] A run submitted by the mobile surface (`editorOwnsRun` false) shows no button in the editor
  shell.
- [ ] A result whose columns are `_col0` and `name`, and one whose columns are `id` and `ID`, each
  show the button disabled with the sentence above.
- [ ] After **Run Query Tab** over a single `SELECT`, the button is present.

### FR-003: The hand-off opens one tab, once, and runs it again

#### Description:

`lib/routeHandoff.ts` exports `buildExploreSqlHandoff({body, label})` and `readExploreSqlHandoff(state)`.
The button navigates to `/explore` with
`buildExploreSqlHandoff({body: stripTrailingSemicolons(statement), label: statementHint(statement)})`
as router state, never in the URL. `DataExplorerWorkspace` reads that state with
`readExploreSqlHandoff`, once, guarded by a ref holding the `location.key` it last consumed, since
`AppRoot` renders under `StrictMode`. When the reader accepts the state, the workspace opens a tab with
source `{kind: 'sql', body, label}` through `openTab`. Only when that returns an id does it remove the
cached executions *The decisions* names. It then replaces the history entry with the same path and
search and no state. When `openTab` returns null it raises `ExplorationLimitDialog`, opens nothing,
and still replaces the entry. State the reader does not accept is ignored, and nothing is replaced.
*(Added during the build, from the plan review:)* while an accepted hand-off is still in the history
state, the tab restored from the session runs nothing, by the page's rule for an unsettled link — it
is about to be switched away from, and running it would bill a statement nobody sees. And a hand-off
arriving on an entry that also carries a deep link waits for the link: the link's tab opens first,
its parameter-clearing replace keeps the history state, and the hand-off is read on the entry that
replace produces — replacing in the same flush put the link's parameters back (diff review).

#### Acceptance Criteria:

- [ ] `readExploreSqlHandoff(buildExploreSqlHandoff({body: 'SELECT 1', label: 'x'}))` returns
  `{body: 'SELECT 1', label: 'x'}`, and it returns null for `{exploreSql: {body: 42}}`, `null`, and
  `{}`.
- [ ] From the Query side: exploring `SELECT name, qty FROM db.orders;` navigates to `/explore` with
  state equal to `buildExploreSqlHandoff({body: 'SELECT name, qty FROM db.orders', label: <its
  statementHint>})` and no query string.
- [ ] From the Explorer side, rendered under `<StrictMode>` with `browserRouter: true` and that state:
  exactly one tab opens, labelled with that hint, whose first execution's SQL is
  `SELECT *\nFROM (\nSELECT name, qty FROM db.orders\n) AS t`. Afterwards `window.history.state.usr`
  carries no `exploreSql`, and unmounting and mounting a fresh workspace opens no second tab.
- [ ] With the unfiltered run of that statement and a filtered run over it both cached, the hand-off
  starts a new execution, and applying the same filter afterwards starts a new one too. A second
  `sql` tab over a different statement keeps its cached execution, and no execution starts for it.
- [ ] Mounting the workspace at a `/explore?space=…&db=…&table=…` link with no hand-off state opens
  the linked table's tab exactly once.
- [ ] At the tab limit, a hand-off whose statement's unfiltered run is cached removes nothing and
  starts no execution.
- [ ] At the tab limit the hand-off raises the limit dialog, the tab count is unchanged, and the
  history state no longer carries `exploreSql`.

### FR-004: A tab whose source is SQL works end to end

#### Description:

A `sql`-source tab, with no Glue schema, draws its headers from its execution's column metadata,
whose types arrive in Glue's spelling (`string`, `int`). `filterValueKind`, `isTextType` and
`operatorsFor` pick operators and value kinds from those. Whenever an execution of the tab's source
with no grouping succeeds, the tab stores its columns as `sqlSourceColumns`, and
`useSourceColumns` returns them for a `sql` source, so the Grouping panel can list columns while a
grouping is applied. `explorationTabs.ts` persists and validates the field. Sorting, filtering,
grouping, Colors, Calc, copy, *Save results to my files* and *Save as query* work as they do on a
table tab. *Create view…* refuses with "A view is created in one database, and SQL opened from a
query or a saved file can read from several. Open a table to create a view from it." The tab restores
from session storage after a reload.

#### Acceptance Criteria:

- [ ] A `sql`-source tab whose execution reports `name string` and `qty int` shows both headers. The
  `qty` menu offers no **contains**, and filtering `qty` greater than `5` renders `"qty" > 5`, bare.
- [ ] Sorting `name` descending renders `SELECT *\nFROM (\n<body>\n) AS t\nORDER BY "name" DESC`.
- [ ] Grouping by `name` with `COUNT(*)` renders a statement that groups over the subquery. Reopening
  the Grouping panel on the grouped tab lists `name` and `qty`, and changing the grouping to `qty`
  applies.
- [ ] *Save results to my files* on the tab saves the tab's own execution output.
- [ ] *Create view…* shows the sentence above.
- [ ] A tabs document holding a `sql`-source tab with `sqlSourceColumns` restores that tab with its
  body, label and columns. A document whose `sqlSourceColumns` is not an array of `{name, type}`
  strings restores the tab without the field.

### FR-005: The registry and the guides

#### Description:

`gatedSurfaces.ts` gains *Explore in Data Explorer* as a `control` on `/query` under `dataExplorer`,
and *Explore in Data Explorer on a query result* under `query`, on the *Explore data* precedent. Both
get a recipe in `gatedSurfaces.test.tsx`. The Query section's `run-script` guide says that selecting
several statements and choosing **Run Statement** gives each one a result tab. The Data Explorer's
*Start exploring* guide says a query result can be opened there with **Explore in Data Explorer**,
which runs the statement again, and that each column needs its own name.

#### Acceptance Criteria:

- [ ] `gatedSurfaces.test.tsx` passes with both rows and their recipes, and fails if the button
  renders with either flag off.
- [ ] The guides carry the sentences, and the `run-query` guide gains none. This is static copy, so
  the diff review checks it.

---

## Data Model

```ts
// apps/portal/src/lib/routeHandoff.ts
export type ExploreSqlHandoff = {exploreSql: {body: string; label: string}};

// apps/portal/src/features/data-explorer/dataExplorer.types.ts — ExplorationTab gains
/** A `sql` source's columns, from its latest ungrouped execution. Absent for a table source. */
sqlSourceColumns?: QueryColumn[];
```

## API / Interface Contract

```ts
// apps/portal/src/lib/routeHandoff.ts
export function buildExploreSqlHandoff(handoff: {body: string; label: string}): ExploreSqlHandoff;
export function readExploreSqlHandoff(state: unknown): {body: string; label: string} | null;

// apps/portal/src/features/query/query.sql.ts
export function isExplorableSql(sql: string): boolean;
```

## File & Folder Structure

```
apps/portal/src/lib/routeHandoff.ts (+ routeHandoff.test.ts)            (FR-003)
apps/portal/src/test/renderWithProviders.tsx                            (router state)
apps/portal/src/features/query/QueryWorkspace.tsx                        (FR-001, FR-002 wiring)
apps/portal/src/features/query/QueryStatusBar.tsx (+ test)               (FR-002, FR-003)
apps/portal/src/features/query/query.sql.ts (+ queryPure.test.ts)        (FR-002)
apps/portal/src/features/data-explorer/DataExplorerWorkspace.tsx (+ test) (FR-003, FR-004 wording)
apps/portal/src/features/data-explorer/dataExplorer.types.ts, explorationTabs.ts,
  useExplorationTabs.ts, useSourceColumns.ts                             (FR-004)
apps/portal/src/features/feature-flags/gatedSurfaces.ts (+ test)         (FR-005)
apps/portal/src/features/help/helpContent.ts                             (FR-005)
apps/portal/info/component-inventory/query-feature.md, data-explorer-feature.md, foundations.md,
  test-utilities.md
```

## Implementation Phases

### Phase 1: Result tabs for a selection

- The scope choice in `handleRunStatement` and its tests (FR-001).

### Phase 2: A `sql`-source tab end to end

- `sqlSourceColumns`, the reworded *Create view…* refusal, and tests for every FR-004 criterion
  against a `sql`-source tab. A further defect those tests expose is fixed in this phase when it lies
  inside the surfaces FR-004 names, and raised as a scope change otherwise. This phase comes before
  the button, so no user can reach a broken arm.

### Phase 3: The hand-off

- `routeHandoff.ts`, `renderWithProviders`' router state, `isExplorableSql`, the button, the Explorer's
  one-time read, the registry rows
  and the guides (FR-002, FR-003, FR-005).
- The live check, run from a signed-in session after deploy: in Query, select two `SELECT`
  statements and choose **Run Statement**; two result tabs appear. On the second, choose **Explore in
  Data Explorer**; a Data Explorer tab opens with that result's columns. Hide a column, filter one,
  then reload the page: the tab is still there and there is only one. Fold it into
  `docs/testing/e2e.md` at completion.
