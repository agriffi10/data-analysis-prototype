# Spec: A Query Result Opens in Data Explorer, and a Selection of Statements Gets a Tab Each

**ID:** SPEC-242
**Status:** Draft
**Last Updated:** 2026-09-16
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
- **The Explorer may not import `features/query/`** (`ExportExplorationDialog.tsx` docstring).

### The decisions, made while authoring

- **A selection that resolves to more than one statement runs with the tab-per-statement scope.** A
  single statement, selected or under the cursor, keeps `'statement'`. Only the display changes,
  which is exactly what distinguishes the scopes.
- **The hand-off carries the statement's text, not the result.** The Data Explorer works by
  rendering SQL over its source, so exploring a result means running the statement again, wrapped.
  That is a billed execution, just as opening a table in the Explorer is. The alternative, filtering
  the stored result object, is a different engine and no tester asked for one.
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
- **The Query workspace's mobile surface** (`QueryMobileView`) and the **Run Query Tab** scope.
- **Opening a saved `.sql` file** as an exploration source, and linking the new tab to a saved query.
- **Sending a result from the Data Explorer back to Query.** SPEC-243 opens the Explorer's generated
  SQL in Query.
- **Create view from a `sql`-source tab.** The existing refusal stands.

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
and comments is `SELECT`, `WITH` or `VALUES`, case-insensitively. The results region shows an
**Explore in Data Explorer** button beside *Save results* when all of these hold: the
`dataExplorer` flag is on; the displayed result is a succeeded execution; and the statement that
produced it, taken from the run's `statements`, is explorable. A run the mobile surface submitted
never shows it, following the existing `editorOwnsRun` rule.

#### Acceptance Criteria:

- [ ] `isExplorableSql` is true for `select 1`, `-- note\nWITH x AS (SELECT 1) SELECT * FROM x` and
  `/* a */ VALUES (1)`, and false for `SHOW TABLES IN db`, `DESCRIBE db.t`, `EXPLAIN SELECT 1`,
  `CREATE TABLE …` and `''`.
- [ ] After a succeeded `SELECT` the button is present, and after a succeeded `SHOW TABLES` it is not.
- [ ] In a two-tab result where tab 1 is a `SELECT` and tab 2 a `DESCRIBE`, the button is present
  on tab 1 and absent on tab 2.
- [ ] With `dataExplorer` off the button is absent after a succeeded `SELECT`.
- [ ] While the batch is running, and after a failed one, the button is absent.

### FR-003: The hand-off opens one tab, once

#### Description:

The button navigates to `/explore` with router state
`{exploreSql: {body: stripTrailingSemicolons(statement), label: statementHint(statement)}}`. It
never puts the statement in the URL. `DataExplorerWorkspace` reads that state once, opens a tab with
source `{kind: 'sql', body, label}` through `openTab`, and replaces the history entry with the same
path and no state. When `openTab` returns null it raises `ExplorationLimitDialog`, as a link does
today, and opens nothing. State whose `exploreSql` is not an object with a string `body` and a
string `label` is ignored.

#### Acceptance Criteria:

- [ ] Exploring `SELECT name, qty FROM db.orders;` opens a Data Explorer tab labelled with
  `statementHint` of that statement, whose first execution's SQL is
  `SELECT *\nFROM (\nSELECT name, qty FROM db.orders\n) AS t`.
- [ ] After the hand-off `window.location.search` is empty, the statement text appears nowhere in
  the URL, and the history entry's state no longer carries `exploreSql`.
- [ ] Re-rendering the workspace after the hand-off (standing in for a reload) opens no second tab.
- [ ] At the tab limit the hand-off raises the limit dialog and the tab count is unchanged.
- [ ] State `{exploreSql: {body: 42}}` opens nothing and raises nothing.

### FR-004: A tab whose source is SQL works end to end

#### Description:

A `sql`-source tab, with no Glue schema, draws its headers from the first execution's column
metadata. Each column's type comes from that metadata, so `filterValueKind`, `isTextType` and
`operatorsFor` pick operators and value kinds from Athena's own type names. Sorting, filtering,
grouping, Colors, Calc, copy, *Save results to my files* and *Save as query* work as they do on a
table tab. *Create view* shows its existing refusal. The tab restores from session storage after a
reload.

#### Acceptance Criteria:

- [ ] A `sql`-source tab whose execution reports `name varchar` and `qty integer` shows both headers.
  The `qty` menu offers no **contains**, and filtering `qty` greater than `5` renders `"qty" > 5`,
  bare.
- [ ] Sorting `name` descending renders `SELECT *\nFROM (\n<body>\n) AS t\nORDER BY "name" DESC`.
- [ ] Grouping by `name` with `COUNT(*)` renders a statement that groups over the subquery, and the
  grid shows the grouped columns.
- [ ] *Save results to my files* on the tab enqueues or copies the tab's own execution output.
- [ ] *Create view…* shows the sentence the workspace carries today for a non-table source.
- [ ] A tabs document holding a `sql`-source tab written to session storage restores that tab with
  its body and label.

### FR-005: The registry and the guides

#### Description:

`gatedSurfaces.ts` gains *Explore in Data Explorer* as a `control` on `/query` under `dataExplorer`,
and again under `query`, on the *Explore data* precedent. The Query section's `run-script` guide
says that selecting several statements and choosing **Run Statement** gives each one a result tab,
and its `run-query` guide says that **Explore in Data Explorer** opens a result in the Data Explorer,
running the statement again there. The Data
Explorer's *Start exploring* guide says a query result can be opened there from the Query page.

#### Acceptance Criteria:

- [ ] `gatedSurfaces.test.tsx` passes with the two new rows, and fails if the button renders with
  `dataExplorer` off.
- [ ] Both guides carry the sentences. This is static copy, so the diff review checks it.

---

## Data Model

```ts
// The router state the Query side sends and the Explorer reads.
// apps/portal/src/features/data-explorer/dataExplorer.types.ts
export type ExploreSqlHandoff = {exploreSql: {body: string; label: string}};
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/query.sql.ts
export function isExplorableSql(sql: string): boolean;

// apps/portal/src/features/data-explorer — a pure reader beside useExploreDeepLink
export function readExploreSqlHandoff(state: unknown): {body: string; label: string} | null;
```

## File & Folder Structure

```
apps/portal/src/features/query/QueryWorkspace.tsx          (FR-001, FR-002 wiring)
apps/portal/src/features/query/query.sql.ts (+ queryPure.test.ts)   (FR-002)
apps/portal/src/features/query/QueryResultsRegion.tsx (+ test)      (FR-002, FR-003)
apps/portal/src/features/data-explorer/DataExplorerWorkspace.tsx (+ test)  (FR-003)
apps/portal/src/features/data-explorer/useExploreSqlHandoff.ts or a reader beside useExploreDeepLink
apps/portal/src/features/data-explorer/ — tests for a sql-source tab (FR-004)
apps/portal/src/features/feature-flags/gatedSurfaces.ts     (FR-005)
apps/portal/src/features/help/helpContent.ts                (FR-005)
apps/portal/info/component-inventory/query-feature.md, data-explorer-feature.md
```

## Implementation Phases

### Phase 1: Result tabs for a selection

- The scope choice in `handleRunStatement` and its tests (FR-001).

### Phase 2: A `sql`-source tab end to end

- Tests for every FR-004 criterion against a `sql`-source tab, fixing whatever the dormant arm
  gets wrong. This phase comes before the button, so no user can reach a broken arm.

### Phase 3: The hand-off

- `isExplorableSql`, the button, the router state, the Explorer's one-time read, the registry rows
  and the guides (FR-002, FR-003, FR-005).
- The live check, run from a signed-in session after deploy: in Query, select two `SELECT`
  statements and choose **Run Statement**; two result tabs appear. On the second, choose **Explore in
  Data Explorer**; a Data Explorer tab opens with that result's columns. Hide a column, filter one,
  then reload the page: the tab is still there and there is only one. Fold it into
  `docs/testing/e2e.md` at completion.
