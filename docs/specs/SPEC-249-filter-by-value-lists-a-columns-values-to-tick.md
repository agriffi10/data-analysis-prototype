# Spec: Filter by Value Lists a Column's Values to Tick

**ID:** SPEC-249
**Status:** Draft
**Last Updated:** 2026-09-28
**Depends On:** SPEC-238, SPEC-243

## Overview

An outside reviewer compared the Data Explorer with DBeaver on 2026-09-28. Today **Filter by this
value** in the **Options** menu filters on the one cell the cursor is on. The reviewers asked for
it to be called **Filter by value** and to work the way DBeaver's does: list every value the
column holds, with how many rows hold each, and let the user tick several. Andrew approved it the
same day. The rename is only honest once the behaviour matches, so both ship together.

This spec replaces the one-cell action with a **Filter by value…** dialog, reached from the
**Options** menu and from each column's header menu. The dialog lists the column's values, most
common first, under the filters already applied to the other columns. The user ticks values and
chooses whether to keep those rows (**is one of**) or hide them (**is not one of**), the two list
operators SPEC-238 added and which today take only typed values. **NULL** and **(empty)** are
listed like any other value and can be ticked.

Listing the values is billed work, because Athena has to read the column to count it. It runs only
when the user opens the dialog, reopening it with the same filters reuses the first result, and
what it scanned is shown the way the Explorer shows every other scan and counts toward the tab's
running total.

SPEC-241 specified this feature on 2026-09-16 and was cancelled that day, before it was built.
This spec reuses its reviewed decisions on the query, the cost and the listing's lifecycle, and
differs from it in four places: it adds **is not one of**, it lets a list hold NULL and (empty),
it replaces the **Options** item rather than adding only a header item, and it gives a total when
the list is cut short. The list itself is a component the AND/OR condition builder, specified
alongside, embeds under its own rows.

### What was checked, and how

Read from the code at `8a628382`.

- **One SQL builder.** `renderExplorationSql.ts` holds the renderer and its private `renderFrom`
  and `renderWhere`. `renderWhere` joins column filters with `AND` and parenthesises the
  expression.
- **Executions are cached by their SQL.** `useExploration` starts a statement with `runQuery` from
  `features/catalog/athena.service`, keyed `explorerKeys.execution(scope, sql)` with `staleTime`
  and `gcTime` both `Infinity`, and polls it with `useQueryExecution`.
- **A catalog change re-runs what is observed.** `evictExplorations` and `evictSqlSource`
  (`useExplorationEviction.ts`) call `resetQueries` on keys under `explorerKeys.execution`, which
  clears every entry and refetches every one that has an observer. That is deliberate for the
  exploration on screen, and it is why a listing keyed there must not stay observed after nobody is
  looking at it.
- **The tab's cost total is per execution.** `useExplorationTabs.recordScan(tabId, executionId,
  bytes)` keys bytes by execution id, so recording one execution twice adds nothing.
  `DataExplorerWorkspace` tells a cache hit apart by reading the ledger before recording.
  `CostIndicator` renders a scan, a cache hit (`CACHE_HIT_TEXT`) and the tab total.
- **A result page holds at most 1,000 rows.** `lambdas/api/routes/athena.py` clamps `MaxResults`
  to `ATHENA_MAX_RESULTS = 1000` and drops the header row from the first page. `getQueryResults`
  keeps NULL (`null`) apart from `''`, and `cellText.ts` displays them as `NULL_DISPLAY` and
  `EMPTY_DISPLAY` (`(empty)`).
- **A list today holds non-empty, single-line strings only.** `ColumnFilter.values` is `string[]`.
  `isValidFilterValues` in `explorationTabs.ts` refuses an empty list, `null`, `''` and a line
  break, and `isValidFilter` accepts a list filter with `values` missing altogether, which
  `renderValues` then throws on. `FILTER_KEYS` there is the hand-written set of keys
  `readStrictQuery` allows on a saved view's filter.
- **Two descriptions are compared on a canonical form.** `canonical` in `explorationQueryOps.ts`
  keeps only `column`, `operator`, `value`, `values` and `valueKind`, and `apply` in
  `useExplorationQuery.ts` changes nothing when `sameQuery` holds. A new field that `canonical`
  does not read is a change no apply can make.
- **Order and filter re-parses every list row on apply.** `OrderFilterDialog.tsx` pre-fills each
  row with `filterValuesText(values)` and, on apply, writes `parseFilterValues(text)` for every
  list filter, touched or not. `parseFilterValues` skips blank lines. So a list holding `''` written
  by any other surface would lose it the next time **Order and filter** is applied.
- **`notIn` excludes NULL rows.** SPEC-238 settled it as SQL's own rule, the same as `<>`.
- **The one-cell action.** `filterByCell` in `ExplorationResultsRegion.tsx` writes `=` the cursor's
  raw value, or `isNull` for a NULL cell. It is refused with `NO_CELL_TO_FILTER`, the column's
  `queryRefusalOf`, or `UNFILTERABLE_VALUE` for a numeric value `isBareNumeric` rejects.
  `actions.filter` there builds a list filter from `FilterValueResult.values` alone.
- **The header menu reaches `ColumnFilterMenu` through `ExplorationGrid` and
  `ExplorationGridHeader`.** At `8a628382` Record and Text views have no column header; the Data
  Explorer papercuts work in flight removes both views, so the grid and its header menu will be the
  only presentation at every width. Nothing in this spec depends on either view: the **Options**
  item reads the grid's cursor cell, and both entry points exist whichever lands first.
- **A held tab has run nothing and shows no grid.** A view reopened from a shared space's
  `saved_queries/` opens held (`ExplorationResultsRegionProps.held`), with no rows and so no cursor
  cell, and its filter expression is SQL another member wrote.
- **DBeaver's list ignores the other filters.** Its filter pane lists the whole table's values;
  dbeaver/dbeaver#21416 asks for an option to list only the current result's.
- **Athena accepts the window count, and it scales.** Run in the Query workspace on 2026-09-28,
  each over generated rows (0 B scanned): over six values with `LIMIT 2` the query returned two
  rows, each with `value_count` 5, so the window counts groups before the `LIMIT`. Over 10,000,000
  distinct varchar values with `LIMIT 1000` it succeeded in 4.0 s with `value_count` 10,000,000,
  against 3.1 s for the same query without the window; over 40,000,000 it succeeded in 16.3 s.

### The decisions, made while authoring

- **The list is counted under the other columns' filters and the expression, never this column's
  own filter.** The user is choosing values for this column, so every value the other filters leave
  must be on offer, including the ones this column's filter now excludes. Grouping and ordering do
  not change which values exist, so neither is rendered. This is the spreadsheet behaviour DBeaver
  users have asked for, rather than DBeaver's own.
- **The CALLER says what narrows the list.** `renderColumnValuesSql` takes the narrowing filters and
  expression as an argument and removes nothing itself. The two menus pass the root filters minus
  this column's own, plus the expression. The AND/OR builder passes none, because inside an OR
  group narrowing one condition's values by its siblings hides the values the OR exists to reach.
- **At most `EXPLORER_FILTER_VALUES_MAX` (1,000) values, the most common first.** Ties are broken by
  value, ascending, with NULL last, so the list is the same each time. Sharing the list operators'
  cap means every selection the list alone can make is a legal list filter. The query also counts
  how many values there are in all, with a window `COUNT(*) OVER ()` that scans nothing extra, so a
  list cut short can say "of 12,345". The measurement above is why the window's single-node count
  was judged safe.
- **Search narrows the loaded list and runs no query.** Every search being a fresh billed scan of
  the column is the cost this feature must not have. A value outside the 1,000 is reached by typing
  it with **Filter: is one of…**, and the truncation note says so.
- **Listing is billed and is treated as an apply.** It starts only on the gesture that opens the
  dialog, is cached by its SQL exactly as an exploration is, records its bytes against the tab that
  asked, and shows what it scanned through `CostIndicator`. It pushes no filter-history entry,
  because it changes no description. The **Options** gesture that used to filter on one cell now
  bills the listing as well as the apply; that is the price of the list, and the guide says so.
- **Its cache entry lives under the exploration's execution keys**, `explorerKeys.execution(scope,
  valuesSql)`, so a catalog change drops it with the explorations over that table. Its SQL differs
  from any exploration's, so the two never share an entry. **But a catalog change never STARTS a
  listing**: unlike the exploration on screen, a listing is only ever started by a gesture.
- **Closing the dialog does not stop the listing.** An Athena execution is billed whether or not
  anyone waits for it, and `stopQuery` would bill the part it scanned and leave nothing to show. So
  *Cancel* closes the dialog, the listing settles, its scan is recorded, and reopening the same
  column shows it without a new execution.
- **The workspace hosts the listings; the picker reaches them through context.** The ledger belongs
  to `DataExplorerWorkspace`'s one `useExplorationTabs`, so a provider there owns every listing and
  its recording, and `FilterValuePicker` asks it for one. **Mounting the picker is the billed
  gesture**, which is what lets the builder embed it under a row without owning any of this — and
  why the builder must mount it only on an explicit action.
- **This spec states the listing's invariants and leaves the observer mechanism to the build's
  plan.** SPEC-241's two review rounds each found a hole in a lifecycle mechanism written into the
  spec. FR-002's criteria pin what must hold; the plan review decides how.
- **A list can hold `''` and NULL.** A table built from CSV files stores a blank field as `''`, so
  (empty) is often the value a user most wants to tick, and DBeaver lists NULL as a value. `''`
  becomes an ordinary list value. NULL cannot be one, because `c IN (…, NULL)` never matches a NULL
  row, so the filter carries `includesNull: true` and `in` renders `("c" IN (…) OR "c" IS NULL)`.
  **Which operator may carry it is a column of `FILTER_OPERATOR_SPECS`**, `listsNull`, true for `in`
  alone, and every consumer — `setFilter`, the stored-document check, `canonical`, the typed field
  and the picker — reads that column rather than testing `operator === 'in'`. That is the analytics
  fence's rule, and `canonical` is where a hand-written test would have been missed.
- **`notIn` never lists NULL.** SPEC-238's rule that `notIn` excludes NULL rows stands, and the
  picker shows the NULL entry ticked and locked under **is not one of**, so the tick says what
  happens.
- **The typed field gains two boxes rather than losing the list.** The one-value-per-line field
  cannot write a blank line or a NULL. Rather than forbid those values, the field gets an
  **(empty)** checkbox (text columns) and a **NULL** checkbox (where `listsNull`). Both surfaces that
  use it, the header's **Filter: is one of…** and **Order and filter**, then round-trip any list this
  dialog writes. A value holding a line break stays unlistable: the picker shows it disabled with
  the reason, and the stored-document check keeps refusing it.
- **Only NULL ticked is still a list.** It writes `{operator: 'in', values: [], includesNull: true}`,
  which renders `"c" IS NULL`, rather than switching to the `isNull` operator, so both editors
  reopen it as the list it was made as.
- **Apply does not wait for the list.** The ticked values the dialog starts with — the column's
  filter, or the cell the **Options** menu was opened on — are shown under *Also selected* until the
  listing lands, and Apply works on them in every state. The one rule that needs the whole list,
  "every value ticked clears the filter", applies only once it has landed.
- **Ticking every value of a complete list under is one of clears the filter instead.** The rows are
  the same, and the statement is shorter and matches the unfiltered execution already cached.
- **A value selected but absent from the list stays on show.** *Also selected* holds every value
  that was selected while the picker has been open and that no entry holds, ticked or not, so
  applying never silently drops part of a filter the user built and an untick can be undone. That
  happens when the list is cut at 1,000, when the other filters leave that value no rows, when the
  value was typed, and while the list is still loading.
- **Offered where the list operators are**, which is where `operatorsOf(column)` includes `in`:
  text and numeric columns. A date, timestamp or boolean value would be rendered as a quoted
  string that Trino will not compare with the column. Not on an aggregate column of a grouped
  view, because the listing reads the ungrouped source, which has no `count_all`.
- **The Options item opens the dialog with the cursor's value ticked.** The old one-cell gesture
  becomes one click more, and a user who wanted several values is already in the right place. If
  the column already has a list filter, the dialog starts from that filter instead.
- **Not while the tab is held.** The listing's `WHERE` carries the filter expression, and a held
  tab's expression is SQL from a shared file the user has not chosen to run. Listing it would run
  it. The held refusal is checked first, since a held tab has no cell for the others to judge.
- **The header's typed list items stay.** **Filter: is one of…** and **Filter: is not one of…** keep
  the typed field, which is the only way to paste a long list of known values or reach one past the
  1,000. **Filter by value…** is added beside them, not in their place.

## Scope

### In Scope

- `renderColumnValuesSql` (FR-001).
- Running and hosting the listing: its cache, cost, lifecycle, eviction and failure (FR-002).
- A list holding `''` and NULL, through the operator table, the model, the renderer, the
  comparison, the stored-document checks, the chip and the typed field (FR-003).
- `FilterValuePicker`, the inline list of values to tick, embeddable by the AND/OR builder (FR-004).
- The **Filter by value** dialog and its apply (FR-005).
- The two entry points, the rename, and the *Filter and sort* guide (FR-006).

### Out of Scope

- **Dates, timestamps and booleans** (see *The decisions*).
- **Searching values Athena did not return**, paging through more than 1,000, or a "load more".
- **`notIn` keeping NULL rows.** SPEC-238's rule stands.
- **Values holding a line break.** Listed, disabled, never written into a filter.
- **Counts that follow grouping.** The counts are rows of the filtered source, never groups.
- **Refreshing the list automatically** when data changes. Reopening with the same filters shows
  the cached result for the session, as an exploration does.
- **The AND/OR condition builder's use of the picker.** This spec builds the picker so that spec can
  embed it; wiring it into the builder, and choosing its narrowing, is that spec's work.
- **Filters on an aggregate column in a grouped view.** The header menu already offers them and
  they fail at Athena, since `WHERE` cannot see an aggregate's alias. That is a separate defect;
  this spec only declines to add a new way in.

---

## Functional Requirements

### FR-001: The values query

#### Description:

`renderExplorationSql.ts` exports `renderColumnValuesSql(source, narrowing, column)`, where
`narrowing` is `{filters, expression}` with the types of `ExplorationQuery`'s fields. It renders:

```
SELECT <identifier> AS "value", COUNT(*) AS "row_count", COUNT(*) OVER () AS "value_count"
FROM <renderFrom(source)>
[WHERE <renderWhere(narrowing.filters, narrowing.expression)>]
GROUP BY 1
ORDER BY 2 DESC, 1 ASC NULLS LAST
LIMIT 1000
```

The `WHERE` is built by the same `renderWhere` the exploration uses, so the escaping and the
parenthesisation are identical, and nothing is removed from `narrowing`. The `LIMIT` is
`EXPLORER_FILTER_VALUES_MAX`. Ordinals are used in `GROUP BY` and `ORDER BY`, so a source column
named `value`, `row_count` or `value_count` cannot be mistaken for an output alias.

`explorationQueryOps.ts` exports `narrowingFor(query, column)`: the query's filters without the
filter on `column`, and its expression. It is what both menus pass.

#### Acceptance Criteria:

- [ ] For source `"db"."orders"` and a query with filters `[= 'NY' on state, contains 'ab' on
  brnd_name]`, expression `qty > 5`, a grouping and an ordering,
  `renderColumnValuesSql(source, narrowingFor(query, 'brnd_name'), 'brnd_name')` equals the whole string
  `SELECT "brnd_name" AS "value", COUNT(*) AS "row_count", COUNT(*) OVER () AS "value_count"\nFROM "db"."orders"\nWHERE "state" = 'NY' AND (qty > 5)\nGROUP BY 1\nORDER BY 2 DESC, 1 ASC NULLS LAST\nLIMIT 1000`.
- [ ] With `{filters: [], expression: null}` there is no `WHERE` line.
- [ ] For a `sql` source the `FROM` is the renderer's subquery form, byte-identical to the
  exploration's.
- [ ] A column named `row_count` renders `SELECT "row_count" AS "value", COUNT(*) AS "row_count", …`,
  with `GROUP BY 1` and `ORDER BY 2 DESC, 1 ASC NULLS LAST` unchanged.

### FR-002: Listing is an explicit, cached, costed gesture

#### Description:

`DataExplorerWorkspace` renders a `ColumnValuesProvider` that owns every listing. `useColumnValues`
asks it for one, given `{source, narrowing, column}`. At the request the provider captures the
active tab and the rendered SQL, and the listing's key is `{tabId, valuesSql}`. The provider checks
`exceedsAthenaQueryLimit` first, then starts the statement with `runQuery` under
`explorerKeys.execution(scope, valuesSql)` with the same `staleTime`, `gcTime` and retry policy as
`useExploration`, and polls it with `useQueryExecution`, including the watch ceiling
`useExploration` reports as still running.

Only at `SUCCEEDED` are results read, with `getQueryResults` and `maxRows: 1000`, following a
`nextToken` until 1,000 entries are held or there is none. A failed read makes the listing an
error, never a partial list. A ready listing holds up to 1,000 `{value: string | null, count:
number}` entries, `valueCount` (the `value_count` column, `0` when there are no rows) and
`truncated` (`valueCount >` the entries held). The provider reads the ledger for the listing's
execution id before recording it, and so tells the picker whether the listing is a cache hit. A
failure is shown through `toUserMessage` with *Try again*, which re-reads the results when the
execution `SUCCEEDED`, watches it again when the watch ended with it still running, and starts one
execution when it `FAILED` or was `CANCELLED`. Nothing here changes the tab's
description or its filter history.

These invariants hold, and the criteria below test them:

- every listing execution that reaches a terminal state while it is watched has its scan recorded
  exactly once, against the tab that asked, whether or not any picker is still mounted;
- asking again for a key already running or cached starts nothing;
- no `FAILED` or `CANCELLED` listing starts again without a user gesture, and one no picker shows
  is dropped, so the next request for that key starts one execution;
- an eviction (`evictExplorations`, `evictSqlSource`) starts no listing execution: it drops the
  cached listings it reaches, so the next request starts one, and an execution it catches mid-run
  is still recorded once. A picker showing a listing when it is evicted keeps showing it;
- a picker never shows a listing whose key is not its request's.

#### Acceptance Criteria:

- [ ] Opening the dialog starts exactly one execution. Closing it and reopening it with the same
  applied description starts none.
- [ ] Reopening after a different filter on another column is applied starts one new execution.
- [ ] Reopening after only this column's own filter changed starts none.
- [ ] A succeeded listing that scanned 2,048 bytes raises the tab's running total by 2,048. Closing
  the dialog and reopening it leaves the total unchanged and shows `CACHE_HIT_TEXT`.
- [ ] Choosing *Cancel* while the listing runs closes the dialog and stops nothing: the execution
  settles, its bytes are recorded, and reopening starts no execution.
- [ ] A listing that settles `FAILED` while the dialog is open starts no second execution while the
  dialog stays open. *Try again* starts exactly one. Closing the dialog and reopening it starts one.
- [ ] A listing whose execution `SUCCEEDED` but whose results read fails shows the error, and *Try
  again* reads the results again and starts no execution.
- [ ] Opening the listing for `a`, cancelling, applying a filter on `b`, and reopening the listing
  for `a` before the first settles: the dialog shows only the second listing's values, and both
  executions are recorded once.
- [ ] Opening the listing for `a` in tab 1, cancelling, and switching to tab 2 before it settles:
  its bytes are recorded in tab 1's total and not in tab 2's.
- [ ] Opening the listing for `a`, cancelling and reopening before it settles starts no second
  execution, and the dialog does not show `CACHE_HIT_TEXT` for that first run.
- [ ] Opening the listing, cancelling, and calling `evictExplorations(client, db, table)` for the
  listed table before it settles starts no execution; the first execution's bytes are recorded once;
  reopening afterwards starts one execution.
- [ ] Calling `evictExplorations` for the listed table while the dialog shows a ready listing starts
  no execution and leaves the entries on screen; closing and reopening starts one.
- [ ] The tab's history `past` length is unchanged after a listing runs.
- [ ] A first page of 999 rows with a `nextToken` and a second of 1 yield 1,000 entries. With
  `value_count` 1,000 `truncated` is false; with 1,500 it is true. A first page with no
  `nextToken` reads no second page.
- [ ] No results are read before the listing is `SUCCEEDED`.
- [ ] A values statement over the length limit starts nothing and shows SPEC-238's too-long
  sentence.

### FR-003: A list can hold (empty) and NULL

#### Description:

`FilterOperatorSpec` gains `listsNull: boolean`, true for `in` and false for every other operator.
`ColumnFilter.values` may hold `''` for `in` and `notIn`. `ColumnFilter` gains
`includesNull?: true`, allowed only where `listsNull`.

- **Render.** `in` with `includesNull` renders `("c" IN (<values>) OR "c" IS NULL)`, or `"c" IS NULL`
  when `values` is empty. `in` and `notIn` without it render as today. `''` renders `''`.
- **Compare.** `canonical` compares `includesNull` (as `true` or absent) where `listsNull`, and drops
  it elsewhere, so a change to it alone is a description change.
- **Edit.** `setFilter` keeps `includesNull` only where `listsNull`. `FilterValueResult`'s list arm
  gains `includesNull?: true`, and `actions.filter` in `ExplorationResultsRegion.tsx` writes it.
- **Stored-document check** (`isValidFilter`, and so `readStrictQuery`). A list operator requires
  `values`, an array of strings without a line break, `''` included. `values` may be empty only
  when `includesNull` is `true`. `includesNull` is absent or `true`, and `true` only where
  `listsNull`. `FILTER_KEYS` gains `includesNull`.
- **Chip** (`filterChipLabel`). Values in the renderer's order, `''` as `(empty)`, then `NULL` last
  when `includesNull`.
- **Typed field.** `FilterValuesField` gains, under the text, a group labelled *Also in the list*
  with an **(empty)** checkbox when the column's `valueKind` is `'string'`, and a **NULL** checkbox
  where the operator `listsNull`. It is pre-filled from the stored filter: the non-empty values one
  per line in stored order, **(empty)** ticked when `values` holds `''`, **NULL** ticked when
  `includesNull`. Reading it writes the parsed lines, plus `''` when **(empty)** is ticked, plus
  `includesNull` when **NULL** is ticked. "Enter at least one value." is refused only when no line,
  no **(empty)** and no **NULL** is given, and "Enter at most 1,000 values." counts the lines plus
  `''`, never NULL. `FilterValueDialog`'s list mode and every list row of `OrderFilterDialog` use it.

#### Acceptance Criteria:

- [ ] `in` on `c` with `['b', '', 'a']` and `includesNull` renders `("c" IN ('', 'a', 'b') OR "c" IS NULL)`.
- [ ] `in` on `c` with `[]` and `includesNull` renders `"c" IS NULL`.
- [ ] `notIn` on `c` with `['', 'x']` renders `"c" NOT IN ('', 'x')`.
- [ ] On a tab whose `c` filter is `in ['a']`, ticking **NULL** in **Filter: is one of…** and applying
  starts one execution whose SQL contains `("c" IN ('a') OR "c" IS NULL)`, and pushes one history
  entry; unticking it again starts one more, whose SQL is `"c" IN ('a')`.
- [ ] A stored tab whose filter is `in` with `['', 'a']` and `includesNull: true` restores with the
  filter intact, and `readStrictQuery` returns it unchanged.
- [ ] A stored filter with `includesNull: true` on `notIn`, with `includesNull: false`, with
  `values: []` and no `includesNull`, with `values` missing on `in`, or with a value holding `\n`,
  is refused.
- [ ] The chip for `in` `['b', '', 'a']` with `includesNull` reads `c is one of (empty), “a”, “b” and 1 more`,
  and the chip for `in ['a']` with `includesNull` reads `c is one of “a”, NULL`.
- [ ] Opening **Order and filter** on a tab whose `c` filter is `in ['a', '']` with `includesNull`,
  and applying without touching it, leaves the description unchanged and starts no execution; and
  the same tab's list row shows `a` in the text with **(empty)** and **NULL** ticked.
- [ ] In the header's **Filter: is one of…** dialog on a text column, typing `a`, ticking
  **(empty)** and **NULL** and applying writes `in ['a', '']` with `includesNull`.
- [ ] **Filter: is not one of…** shows the **(empty)** checkbox and no **NULL** checkbox. On a
  `bigint` column **Filter: is one of…** shows **NULL** and no **(empty)**.
- [ ] Nothing typed and neither box ticked is refused with "Enter at least one value.". 1,000 typed
  values plus **(empty)** are refused with "Enter at most 1,000 values."; 999 plus **(empty)** plus
  **NULL** are accepted.

### FR-004: The picker

#### Description:

`FilterValuePicker` is an inline, controlled component with no dialog chrome. It is given the
source, the column, its `valueKind`, the operator (`in` or `notIn`), the narrowing, and the
selection (`{values: string[], includesNull: boolean}`), and reports selection changes. Mounting it
requests the listing (FR-002). It shows:

- a search field, *Search values*, that narrows the entries by case-insensitive substring match on
  their displayed text and runs no query;
- *Select all shown*, which ticks every enabled entry the search leaves, and *Clear selection*,
  which unticks every entry, *Also selected* included;
- one checkbox per entry, in the listing's order, labelled with the value (`NULL_DISPLAY` for NULL
  and `EMPTY_DISPLAY` for `''`, in the grid's muted italic) and its count with thousands
  separators, so its accessible name is `<value>, <n> rows` (`1 row` for a count of one);
- disabled entries, each with its reason: on a numeric column a value `isBareNumeric` rejects
  (`UNFILTERABLE_VALUE`); a value holding a line break ("This value runs over more than one line,
  so it can’t be ticked. Use contains instead."); and, where the operator does not `listsNull`, the
  NULL entry, shown ticked, with "Is not one of always leaves out the NULL rows.";
- when `truncated`, the note "Showing the 1,000 most common of <valueCount> values. Search looks
  only at these. To filter on another value, use Filter: is one of… and type it.", with
  `valueCount` formatted with thousands separators;
- when the listing is ready with no entries, "No rows match the other filters, so there are no
  values to list.";
- *Also selected*: every value that has been in the selection while the picker is mounted and that
  no entry holds, ticked when it is in the selection now. While the listing is pending or failed,
  every selected value is here. On a numeric column a selected value and an entry are the same
  value when `Number()` of each is equal, so `10` matches `10.0`; otherwise they match as exact
  text;
- while the listing runs, a busy state; on failure, the error and *Try again*;
- `CostIndicator` with the listing's bytes, its cache hit and the tab's total.

#### Acceptance Criteria:

- [ ] Entries `[{'Abilify', 40}, {'', 3}, {null, 2}]` render three checkboxes whose accessible names
  are `Abilify, 40 rows`, `(empty), 3 rows` and `NULL, 2 rows`.
- [ ] Typing `abi` leaves only the `Abilify` checkbox, and the number of executions started is
  unchanged.
- [ ] *Select all shown* after typing `abi` ticks only `Abilify`.
- [ ] With the selection `['Abilify', 'Zyrtec']` and no entry for `Zyrtec`, `Abilify` is ticked and
  *Also selected* shows `Zyrtec` ticked. Unticking `Zyrtec` reports a selection without it and
  leaves `Zyrtec` under *Also selected*, unticked; ticking it again reports it back.
- [ ] While the listing is pending, the selection `['Abilify']` shows `Abilify` ticked under *Also
  selected*.
- [ ] `truncated` with `valueCount` 12,345 shows "Showing the 1,000 most common of 12,345 values.…",
  and an untruncated listing shows no note.
- [ ] A count of 1 renders the accessible name `<value>, 1 row`.
- [ ] On a `double` column an entry `NaN` is a disabled checkbox whose reason is `UNFILTERABLE_VALUE`.
- [ ] On a `double` column with the selection `['10']` and an entry `10.0`, `10.0` is ticked and
  *Also selected* is empty.
- [ ] Under `notIn` the NULL entry is ticked and disabled with its reason, and *Clear selection*
  leaves it ticked.
- [ ] An entry `'a\nb'` is disabled with the line-break reason.
- [ ] A ready listing that scanned 2,048 bytes shows `CostIndicator`'s sentence for 2 KB, and a
  cache hit shows `CACHE_HIT_TEXT`.
- [ ] The picker passes axe with a listing of three entries and one disabled entry.

### FR-005: The Filter by value dialog, and its apply

#### Description:

`FilterByValueDialog` is titled "Filter <column> by value". Above the picker it reads "Show rows
where <column>" and a radio group, *Match*, offering **is one of** and **is not one of**
(`FILTER_OPERATOR_LABELS`), then "the ticked values". It passes the picker
`narrowingFor(query, column)`. It starts:

- from the column's filter when that is `in` or `notIn`: its operator, `values` and `includesNull`;
- otherwise with **is one of** and the seed value selected: from the **Options** menu the cursor's
  raw value (a NULL cell selects NULL; a value FR-004 would disable is not selected); from the
  header menu, nothing.

Apply is available in every listing state. It builds the ticked set: the ticked entries plus the
ticked *Also selected* values, and NULL as `includesNull` where the operator `listsNull`, dropped
elsewhere.

- Nothing ticked (a locked NULL does not count): refused with "Tick at least one value.".
- More than `EXPLORER_FILTER_VALUES_MAX` values, NULL not counted: refused with "Choose at most
  1,000 values.".
- **Is one of**, the listing ready and not truncated, every enabled entry ticked, no entry disabled
  and nothing ticked under *Also selected*: Apply clears the column's filter.
- Otherwise Apply sets `{column, operator, values, includesNull?, valueKind: valueKindOf(column)}`
  through `setFilter`, replacing any filter on the column.

Either change is one description change, so at most one execution and one history entry. An apply
that leaves the description unchanged pushes none, as today. *Cancel* applies nothing.

#### Acceptance Criteria:

- [ ] Ticking `Abilify` and `NULL` under **is one of** and applying starts one execution whose SQL
  contains `("brnd_name" IN ('Abilify') OR "brnd_name" IS NULL)`.
- [ ] Ticking `Abilify` and `(empty)` under **is not one of** and applying starts one execution whose
  SQL contains `"brnd_name" NOT IN ('', 'Abilify')`.
- [ ] With the column's filter `notIn ['x']`, the dialog opens on **is not one of** with `x` ticked.
- [ ] With the column's filter `in ['Abilify']`, ticking every entry of an untruncated listing with
  nothing under *Also selected* removes the filter, and the one execution it starts has no predicate
  on the column.
- [ ] Ticking every entry of a truncated listing writes an `in` filter of 1,000 values.
- [ ] Opened from **Options** on an `Abilify` cell, Apply while the listing is still pending writes
  `in ['Abilify']` and starts one execution for the apply.
- [ ] Applying with nothing ticked shows "Tick at least one value." and changes nothing; so does
  **is not one of** with only the locked NULL ticked.
- [ ] A truncated listing of 1,000 all ticked plus one ticked *Also selected* value is refused with
  "Choose at most 1,000 values." and starts no execution.
- [ ] On a `bigint` column, ticking `10` renders `"qty" IN (10)`.
- [ ] Ticking only `NULL` writes `in` with `values: []` and `includesNull`, rendered `"brnd_name" IS NULL`.

### FR-006: Where it is offered, the rename, and the guide

#### Description:

`ColumnQueryActions` gains `filterByValueRefusalOf(column)`, the one reader both menus ask. It
returns `queryRefusalOf(column)` when that is non-null; otherwise "Filter by value works on text
and number columns." when `operatorsOf(column)` lacks `in` or the column is an aggregate alias
(`aggregateAlias`) of the active grouping; otherwise null.

- **Options menu.** **Filter by this value** becomes **Filter by value…**, in the same position. It
  opens the dialog on the cursor's column, seeded with the cursor's value. It is refused, first to
  last, with "Run the view first." while the tab is held, `NO_CELL_TO_FILTER` when there is no
  cursor cell, and `filterByValueRefusalOf(cursor column)`. `UNFILTERABLE_VALUE` no longer refuses
  it.
- **Header menu.** **Filter by value…** is the first item after the sort items' separator, on a
  column whose `filterByValueRefusalOf` is null, and absent on any other. Choosing it calls a new
  `onFilterByValue(column)` prop, threaded from the region through `ExplorationGrid` and
  `ExplorationGridHeader` as `onRequestFilterValue` is. **Filter: is one of…** and **Filter: is not
  one of…** keep the typed dialog.
- **Guide.** The *Filter and sort* guide (`explore-filter-sort`) says that **Filter by value…** is
  in a column's menu and in **Options**, lists the column's values most common first with how many
  rows hold each, keeps (**is one of**) or hides (**is not one of**) the ticked ones, lists NULL and
  (empty) like any value, lists at most 1,000 and searches only those, and runs a query that counts
  toward the tab's scanned total. The step naming **Filter by this value** is replaced. The typed
  list step names the **(empty)** and **NULL** boxes. The expression step no longer offers "a list
  that should keep the NULL rows too" as a reason to write SQL.

#### Acceptance Criteria:

- [ ] A `string` column's header menu and a `double` column's each offer **Filter by value…** as the
  first item after the sort separator.
- [ ] A `date` column's, a `boolean` column's and the percentage column's header menus do not.
- [ ] In a view grouped by `brnd_name` with `COUNT(*)`, `brnd_name` offers it and `count_all` does
  not.
- [ ] Choosing it opens the dialog named "Filter brnd_name by value" and starts one execution.
- [ ] The **Options** menu has no item named **Filter by this value**, and has **Filter by value…**.
  With the cursor on a `brnd_name` cell holding `Abilify`, choosing it opens the dialog with
  **is one of** and `Abilify` ticked.
- [ ] With no cursor cell it is refused with `NO_CELL_TO_FILTER`; on a `date` cell with the
  text-and-number reason; in a held tab with "Run the view first." and no execution starts.
- [ ] On a `double` cell holding `NaN` it is not refused, and opens with nothing ticked.
- [ ] The guide carries the steps. This is static copy, so the diff review checks it against this FR.

---

## Data Model

```ts
// apps/portal/src/features/data-explorer/dataExplorer.types.ts
export type ColumnFilter = {
  column: string;
  operator: FilterOperator;
  value?: string;
  /** `in` and `notIn`: strings without a line break, `''` included. */
  values?: string[];
  /** Only where the operator's spec `listsNull`: NULL is in the list, rendered `OR "c" IS NULL`. */
  includesNull?: true;
  valueKind?: FilterValueKind;
};

// FilterOperatorSpec gains
listsNull: boolean;

export type ColumnValueCount = {value: string | null; count: number};

/** What a list value input edits; NULL rides beside the strings because `IN` cannot hold it. */
export type ValueSelection = {values: string[]; includesNull: boolean};

/** What narrows a listing; the caller builds it. */
export type ValuesNarrowing = {filters: ExplorationQuery['filters']; expression: ExplorationQuery['expression']};
```

## API / Interface Contract

```ts
// renderExplorationSql.ts
export function renderColumnValuesSql(source: ExplorationSource, narrowing: ValuesNarrowing, column: string): string;

// explorationQueryOps.ts — what both menus pass
export function narrowingFor(query: ExplorationQuery, column: string): ValuesNarrowing;

// useColumnValues.ts — requests a listing from the workspace's ColumnValuesProvider
export type ColumnValuesListing =
  | {status: 'pending'}
  | {status: 'error'; error: unknown; retry: () => void}
  | {
      status: 'ready';
      entries: ColumnValueCount[];
      valueCount: number;
      truncated: boolean;
      bytesScanned: number;
      fromCache: boolean;
    };
export function useColumnValues(request: {source: ExplorationSource; narrowing: ValuesNarrowing; column: string}): {
  listing: ColumnValuesListing;
  /** The requesting tab's running total, for `CostIndicator`. */
  totalBytes: number;
};

// FilterValuePicker.tsx — inline; mounting it is the billed request
export type FilterValuePickerProps = {
  source: ExplorationSource;
  column: string;
  valueKind: FilterValueKind;
  operator: 'in' | 'notIn';
  narrowing: ValuesNarrowing;
  selection: ValueSelection;
  onSelectionChange: (next: ValueSelection) => void;
};

// ColumnFilterMenu.tsx — ColumnQueryActions gains
filterByValueRefusalOf: (column: string) => string | null;
// ColumnFilterMenuProps, ExplorationGrid and ExplorationGridHeader gain
onFilterByValue: (column: string) => void;
```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── dataExplorer.constants.ts               (FR-003: listsNull)
├── dataExplorer.types.ts                   (FR-003)
├── renderExplorationSql.ts (+ test)        (FR-001, FR-003 render)
├── explorationQueryOps.ts (+ test)         (FR-001 narrowingFor; FR-003 canonical, setFilter, chip, parse)
├── explorationTabs.ts (+ test)             (FR-003: stored-document check, FILTER_KEYS)
├── FilterValuesField.tsx                   (FR-003)
├── FilterValueDialog.tsx                   (FR-003)
├── OrderFilterDialog.tsx                   (FR-003)
├── useColumnValues.ts (+ test)             (FR-002: provider and hook)
├── DataExplorerWorkspace.tsx               (FR-002: renders the provider)
├── FilterValuePicker.tsx (+ test)          (FR-004)
├── FilterByValueDialog.tsx (+ test)        (FR-005)
├── ColumnFilterMenu.tsx                    (FR-006)
├── ExplorationGrid.tsx                     (FR-006: threads onFilterByValue)
├── ExplorationGridHeader.tsx               (FR-006: threads onFilterByValue)
├── ExplorationOptionsMenu.tsx              (FR-006)
├── ExplorationResultsRegion.tsx            (FR-003 actions.filter; FR-006)
apps/portal/src/features/help/helpContent.ts   (FR-006)
apps/portal/info/component-inventory/data-explorer-feature.md
```

## Implementation Phases

### Phase 1: The list model

- `listsNull`, `includesNull` and `''` through the operator table, the type, the renderer,
  `canonical`, `setFilter`, `actions.filter`, the stored-document checks, the chip and the typed
  field in both of its surfaces (FR-003). Inert until Phase 3 except for the typed field's new
  boxes, which are live on their own.

### Phase 2: The query and the listing

- `renderColumnValuesSql`, `narrowingFor`, the provider, `useColumnValues` and its cost, eviction
  and retry (FR-001, FR-002).

### Phase 3: The picker, the dialog, the menus and Help

- `FilterValuePicker`, `FilterByValueDialog` and its apply, both menu items, the rename and the
  guide (FR-004–FR-006).
- The live check, run from a signed-in session after deploy, on a CSV table with a `brnd_name`
  column holding blanks and an ID-like column with more than 1,000 distinct values: choose **Filter
  by value…** on `brnd_name`, see each brand with its count, `(empty)` among them, and the scanned
  figure; tick two brands and `(empty)` and apply; the grid shows only those rows and the tab's
  scanned total rose by the listing plus the apply. Reopen the dialog: all three are ticked and
  nothing new is scanned. Switch to **is not one of** and apply: the grid shows every other brand.
  Open it on the ID column: the truncation note names the column's true distinct count. Fold it
  into `docs/testing/e2e.md` at completion, where rows 7 of the Explorer walk and the **Options**
  row still drive **Filter by this value**; and mark superseded the SPEC-238 entry's sentence in
  `docs/decisions/analytics.md` that the stored-document check refuses an empty string.
