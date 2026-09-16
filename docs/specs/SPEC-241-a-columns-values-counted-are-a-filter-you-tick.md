# Spec: A Column's Values, Counted, Are a Filter You Tick

**ID:** SPEC-241
**Status:** Draft
**Last Updated:** 2026-09-16
**Depends On:** SPEC-238, SPEC-178, SPEC-181

## Overview

A tester asked for DBeaver's "filter by value" in the Data Explorer: click a column, see each
distinct value with how many rows hold it, tick the ones you want, and filter to them. This spec
adds **Filter by values…** to the column menu. It runs one query that counts the column's values
under the filters already applied to the other columns, lists the most frequent 1,000 with their
counts, and applies the ticked values as the **is one of** filter SPEC-238 defines.

Listing the values is billed work, since Athena has to read the column to count it. So it runs only
when the user chooses the menu item, a second opening with the same filters reuses the first
result, and what it scanned counts toward the tab's running total like any other query.

### What was checked, and how

Read from the code at `73c66eef`, with SPEC-238's model taken as built.

- **One SQL builder.** `renderExplorationSql.ts` holds the renderer and its private `renderFrom` and
  `renderWhere`. The component inventory calls it the ONE SQL builder for the feature.
- **Executions are cached by their SQL.** `useExploration` starts a statement with `runQuery` from
  `features/catalog/athena.service`, under `explorerKeys.execution(scope, sql)`, with `staleTime`
  and `gcTime` both `Infinity`, and polls it with `useQueryExecution`.
- **The tab's cost total is per execution.** `useExplorationTabs.recordScan(tabId, executionId,
  bytes)` keys bytes by execution id, so recording one execution twice adds nothing.
- **A result page holds at most 1,000 rows.** `lambdas/api/routes/athena.py` clamps `MaxResults` to
  `ATHENA_MAX_RESULTS = 1000`. `getQueryResults` keeps NULL apart from `''` (`cellText.ts`).
- **Trino does not coerce.** `FilterValueKind`'s docstring in `dataExplorer.types.ts` records it: a
  string compared with a `bigint` is an error, not a comparison. The model has a numeric kind and a
  string kind, and no typed literal for a date, a timestamp or a boolean.
- **The header menu is unreachable below `tablet`.** `OrderFilterDialog`'s docstring says so, and
  that *Order and filter* is the only way to filter there.

### The decisions, made while authoring

- **The list is counted under the other columns' filters and the expression, never this column's
  own filter.** The user is choosing values for this column, so every value the other filters leave
  must be on offer, including ones the current filter excludes. Grouping and ordering do not change
  which values exist, so neither is rendered.
- **At most `EXPLORER_FILTER_VALUES_MAX` (1,000) values, the most frequent first.** Ties are broken
  by value, ascending, with NULL last, so the list is the same each time. The query asks for 1,001
  rows, so the dialog knows when there are more than it shows. Sharing SPEC-238's constant means
  every selection this list can make is a legal **is one of** filter.
- **Counting is billed and is treated as an apply.** It starts only on the menu gesture, is cached
  by its SQL exactly as an exploration is, records its bytes against the tab, and says what it
  scanned. It pushes no filter-history entry, because it changes no description.
- **Offered on text and numeric columns only.** Their values round-trip into an **is one of**
  filter. A date, timestamp or boolean value would be rendered as a quoted string, which Trino will
  not compare with the column. Typed literals are a change to the filter model, and no tester asked
  for one.
- **Ticking every value of a complete list clears the filter instead.** The rows are the same, and
  the statement is shorter and matches the unfiltered execution already cached.
- **A value already in the column's filter but absent from the list stays selected.** It is shown
  under *Also selected*, so applying never silently drops part of a filter the user built. That
  happens when the list is cut at 1,000, or when the other filters leave that value no rows.
- **Header menu only.** Below `tablet`, **is one of** in *Order and filter* covers the same ground
  without a second billed query.

## Scope

### In Scope

- `renderColumnValuesSql` (FR-001).
- Running the values query, its cache, its cost and its failure (FR-002).
- The values dialog (FR-003) and its apply (FR-004).
- The menu item, which columns get it, and the *Filter and sort* guide (FR-005).

### Out of Scope

- **Dates, timestamps and booleans** (see *The decisions*).
- **More than 1,000 values**, paging through values, or searching values Athena did not return. The
  search box narrows the loaded list only.
- **Filter by values in *Order and filter*** or anywhere below `tablet`.
- **A NOT IN selection** ("everything except the ticked"). **Is not one of** from SPEC-238 is typed.
- **Counts that follow grouping.** The counts are rows of the filtered source, never groups.
- **Refreshing the list automatically** when data changes. Reopening with the same filters shows the
  cached result for the session, as an exploration does.

---

## Functional Requirements

### FR-001: The values query

#### Description:

`renderExplorationSql.ts` exports `renderColumnValuesSql(source, query, column)`. It renders:

```
SELECT <identifier> AS "value", COUNT(*) AS "row_count"
FROM <renderFrom(source)>
[WHERE <renderWhere(filters without column's own filter, expression)>]
GROUP BY 1
ORDER BY 2 DESC, 1 ASC NULLS LAST
LIMIT 1001
```

The `WHERE` is built by the same `renderWhere` the exploration uses, so the escaping and the
parenthesisation are identical. Grouping and ordering are not rendered. `LIMIT` is
`EXPLORER_FILTER_VALUES_MAX + 1`. Ordinals are used in `GROUP BY` and `ORDER BY`, so a source column
named `value` or `row_count` cannot be mistaken for an output alias.

#### Acceptance Criteria:

- [ ] For source `"db"."orders"`, filters `[= 'NY' on state, contains 'ab' on brnd_name]`,
  expression `qty > 5`, a grouping and an ordering, `renderColumnValuesSql(…, 'brnd_name')` equals
  the whole string:
  `SELECT "brnd_name" AS "value", COUNT(*) AS "row_count"\nFROM "db"."orders"\nWHERE "state" = 'NY' AND (qty > 5)\nGROUP BY 1\nORDER BY 2 DESC, 1 ASC NULLS LAST\nLIMIT 1001`.
- [ ] With no other filters and no expression there is no `WHERE` line.
- [ ] For a `sql` source the `FROM` is the renderer's subquery form, byte-identical to the
  exploration's.
- [ ] A column named `row_count` renders `SELECT "row_count" AS "value", COUNT(*) AS "row_count"`,
  with `GROUP BY 1` and `ORDER BY 2 DESC, 1 ASC NULLS LAST` unchanged.

### FR-002: Running it is an explicit, cached, costed gesture

#### Description:

`useColumnValues(exploration, column, tabId)` runs `renderColumnValuesSql` only while it is given a
column, which is only while the dialog is open. It checks `exceedsAthenaQueryLimit` first (SPEC-238
FR-005). It starts the statement with `runQuery` under `explorerKeys.columnValues(scope, sql)`, with
the same `staleTime`, `gcTime` and retry policy as `useExploration`, and polls it with
`useQueryExecution`. It reads at most two result pages, enough for 1,001 rows, and returns up to
1,000 `{value: string | null, count: number}` entries plus `truncated: boolean`. On a terminal
state it calls `recordScan` for the tab, and it returns the execution's `ExecutionCost`. It never
changes the tab's description or its filter history. A failure is returned as an error rendered
through `toUserMessage`, with a retry that evicts the cached start and runs it again.

#### Acceptance Criteria:

- [ ] Opening the dialog starts exactly one execution. Closing it and reopening it with the same
  applied description starts none.
- [ ] Reopening after a different filter on another column is applied starts one new execution.
- [ ] A succeeded values execution that scanned 2,048 bytes raises the tab's running total by
  2,048, and recording it again does not.
- [ ] The tab's history `past` length is unchanged after the values query runs.
- [ ] 1,001 result rows yield 1,000 entries and `truncated: true`, and 1,000 rows yield 1,000 and
  `false`.
- [ ] A failed values execution shows the closed error wording and a *Try again* control, which
  starts one new execution.
- [ ] A values statement over the length limit starts nothing and shows SPEC-238's too-long
  sentence.

### FR-003: The values dialog

#### Description:

`ColumnValuesDialog` is titled "Filter <column> by values". While the query runs it shows a busy
state with *Cancel* enabled. When it lands it shows:

- a search field that narrows the list by case-insensitive substring match on the displayed text,
  running no query;
- *Select all shown* and *Clear selection*;
- one checkbox per value, labelled with the value (`NULL` for NULL and `(empty)` for `''`, in the
  grid's muted italic) and its count formatted with thousands separators;
- when `truncated`, the note "Showing the 1,000 most common values. Values with fewer rows are not
  listed.";
- *Also selected*: the current filter's values that the list does not hold, each ticked;
- what the listing scanned, worded as the cost indicator words a scan.

The checkboxes start ticked from the column's current **is one of** filter, if it has one, and
unticked otherwise.

#### Acceptance Criteria:

- [ ] Values `[{'Abilify', 40}, {'', 3}, {null, 2}]` render three checkboxes whose accessible names
  are `Abilify, 40 rows`, `(empty), 3 rows` and `NULL, 2 rows`.
- [ ] Typing `abi` leaves only the `Abilify` checkbox and starts no execution.
- [ ] With the column's filter `in ['Abilify', 'Zyrtec']`, and `Zyrtec` not among the returned
  values, `Abilify` is ticked and *Also selected* shows `Zyrtec` ticked.
- [ ] *Select all shown* after typing `abi` ticks only `Abilify`.
- [ ] `truncated: true` shows the truncation note, and `false` does not.

### FR-004: Apply writes one filter and one execution

#### Description:

Apply builds the ticked set: the ticked list entries plus the ticked *Also selected* values.

- None ticked: Apply is refused with "Tick at least one value.".
- Every list entry ticked, the list not truncated, and nothing under *Also selected*: Apply clears
  the column's filter.
- Otherwise: Apply sets `{column, operator: 'in', values: <ticked, NULL as null>, valueKind:
  valueKindOf(column)}` through `setFilter`, replacing any filter on the column.

Either change is one description change, so one execution at most and one history entry.

#### Acceptance Criteria:

- [ ] Ticking `Abilify` and `NULL` and applying produces one execution whose SQL contains
  `("brnd_name" IN ('Abilify') OR "brnd_name" IS NULL)`.
- [ ] Ticking every entry of an untruncated list with no *Also selected* removes the column's filter,
  and the next execution's SQL has no predicate on the column.
- [ ] Ticking every entry of a truncated list writes an `in` filter of 1,000 values.
- [ ] Applying with nothing ticked shows "Tick at least one value." and changes nothing.
- [ ] On a `bigint` column, ticking `10` renders `"qty" IN (10)`.

### FR-005: Which columns offer it, and the guide

#### Description:

The column menu offers **Filter by values…** after the filter operators, on a column where
`isTextType(type)` is true or `filterValueKind(type)` is `'number'`, and `queryRefusalOf` is null.
It is not offered on any other column. The *Filter and sort* guide gains a step: **Filter by
values…** lists the column's most common values with how many rows each has, and ticking some
filters to them. It says that listing the values runs a query, which counts toward the tab's scanned
total.

#### Acceptance Criteria:

- [ ] A `string` column's menu and a `double` column's menu each offer **Filter by values…**.
- [ ] A `date` column's menu, a `boolean` column's menu, and the percentage column's menu do not.
- [ ] Choosing it opens the dialog named "Filter brnd_name by values" and starts one execution.
- [ ] The guide carries the step. This is static copy, so the diff review checks it.

---

## Data Model

```ts
// apps/portal/src/features/data-explorer/dataExplorer.types.ts
export type ColumnValueCount = {value: string | null; count: number};
```

## API / Interface Contract

```ts
// renderExplorationSql.ts
export function renderColumnValuesSql(source: ExplorationSource, query: ExplorationQuery, column: string): string;

// explorerKeys.ts
columnValues: (scope: readonly [string, string, string], sql: string) => readonly unknown[];

// useColumnValues.ts
export function useColumnValues(
  exploration: Exploration | null,
  column: string | null,
  tabId: string
): {
  values: ColumnValueCount[];
  truncated: boolean;
  cost: ExecutionCost | null;
  isPending: boolean;
  error: unknown;
  retry: () => void;
};
```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── renderExplorationSql.ts (+ test)       (FR-001)
├── explorerKeys.ts                        (FR-002)
├── useColumnValues.ts (+ test)            (FR-002)
├── ColumnValuesDialog.tsx (+ test)        (FR-003, FR-004)
├── ColumnFilterMenu.tsx                   (FR-005)
├── ExplorationResultsRegion.tsx           (the dialog is raised by the region, as FilterValueDialog is)
apps/portal/src/features/help/helpContent.ts
apps/portal/info/component-inventory/data-explorer-feature.md
```

## Implementation Phases

### Phase 1: The query and its hook

- `renderColumnValuesSql`, the key, and `useColumnValues` with its cost and retry (FR-001, FR-002).

### Phase 2: The dialog, the menu and Help

- `ColumnValuesDialog`, its apply, the menu item and the guide (FR-003–FR-005).
- The live check, run from a signed-in session after deploy, on a CSV table with a `brnd_name`
  column: choose **Filter by values…** on `brnd_name`, see each brand with its count and the scanned
  figure, tick two brands and apply; the grid shows only those brands and the tab's scanned total
  rose by the listing plus the apply. Reopen the dialog: both are ticked and nothing new is scanned.
  Fold it into `docs/testing/e2e.md` at completion.
