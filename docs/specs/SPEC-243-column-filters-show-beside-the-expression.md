# Spec: A Column Filter Shows Beside the Expression, and the Generated SQL Opens in Query

**ID:** SPEC-243
**Status:** Draft
**Last Updated:** 2026-09-16
**Depends On:** SPEC-181, SPEC-183, SPEC-238, SPEC-242, and the Copy SQL control #804 added

## Overview

Three testers ran into the same wall between the Data Explorer's two ways of filtering. A filter set
from a column's menu changes the generated SQL but never appears in the *Filter expression* box, so
one tester could not see how to keep building on it. Another wanted to edit the generated SQL
itself. A third wanted to keep filters and to filter on several columns at once.

Several column filters already apply together, but nothing on screen lists them. This spec shows
every column filter as a chip beside the expression box, each removable with one click. It also
adds **Open in Query** to the *Generated SQL* panel, which copies the statement into a new Query tab
where it can be edited freely. The Data Explorer does not read SQL back into its filters, so
editing happens in Query, on a copy.

### What was checked, and how

Read from the code at `73c66eef`.

- **Column filters and the expression are separate fields.** `ExplorationQuery` in
  `features/data-explorer/dataExplorer.types.ts` has `filters: ColumnFilter[]` and
  `expression: string | null`. `renderWhere` in `renderExplorationSql.ts` joins every filter with
  `AND` and adds the parenthesised expression, so filters on several columns already combine.
- **Nothing lists the filters.** The column menu's trigger shows a `•` and says "filtered" in its
  accessible name (`ColumnFilterMenu.tsx`). *Order and filter* shows each column's criteria row.
  Neither sits beside the expression box (`ExplorationResultsRegion.tsx` renders `ExpressionBar`,
  then `GeneratedSqlDisclosure`).
- **The generated SQL is read-only and copyable.** `GeneratedSqlDisclosure` shows the string that
  ran in a read-only textarea with a `CopyButton`, mounted only while the disclosure is open.
- **A shared removable chip exists.** `components/Chip.tsx` exports `Chip` and `ChipList`, with a
  24px remove target, a truncating monospaced name, and a remove label the caller supplies whole.
- **Query can open a tab holding given SQL.** `useQueryTabs.openTab({label, sql})` returns the new
  id, or null at `QUERY_TABS_MAX`, and `QueryWorkspace` raises its tab-limit dialog through
  `onTabLimit`. History's *re-open* loads SQL without running it.
- **A Query capability on a Data Explorer surface is registered under `query`.** `gatedSurfaces.ts`
  lists *Save as query* and *Create view…* on `/explore` under `query` only.
- **Neither feature may import the other.** `eslint.config.js` forbids `features/query/` and
  `features/data-explorer/` importing each other, tests and `import type` included.
- **Saving already exists.** *Save as query* writes the generated SQL to a `.sql` file. Opening a
  `.sql` file as an exploration source is deferred (`ExplorationTab.savedQuery` docstring).

### The decisions, made while authoring

- **Chips, not text written into the expression box.** Writing a filter into the box as SQL would
  make the box's text a mixture of what the user typed and what the app wrote. The app could then no
  longer tell them apart, and the menu could no longer find or replace its own filter.
- **No two-way editing.** Reading arbitrary SQL back into filters, sorts and groupings means parsing
  it, and anything the parser does not cover would be lost silently. **Open in Query** hands over a
  copy instead, and the Explorer tab is left unchanged.
- **A chip removes and nothing else.** Editing a filter stays in the column menu and *Order and
  filter*, which already edit it. The shared `Chip` stays remove-only, since it also serves three
  recipient lists.
- **The label is the filter in words.** It uses the operator labels the menu uses. A text value is
  shown in quotation marks, so leading and trailing spaces are visible. A number is shown bare. An
  empty string reads `(empty)`. A list shows its first three values, then
  "and <n> more".
- **Open in Query opens a new tab and does not run it.** Running the statement is the user's call,
  as it is when *re-open* loads a history entry, and a new tab never overwrites the user's buffer.
- **The hand-off travels in router state, never the URL**, and is consumed once. A reload must not
  open a second tab, and a statement can quote the user's data. `BrowserRouter` keeps navigation
  state in `window.history.state` across a reload, and `AppRoot` renders under `StrictMode`, which
  runs an effect twice in development. So the read is guarded by a ref keyed on `location.key`, and
  the state is then replaced away.
- **The hand-off's shape lives in `lib/routeHandoff.ts`,** beside SPEC-242's, with a builder the
  Explorer calls and a reader Query calls, so the two sides cannot hold different copies of it.
- **On a phone, the hand-off also shows the statement.** Below `tablet` the Query workspace renders
  `QueryMobileView`, which has no editor, so a new tab alone would be invisible. The read therefore
  also calls the mobile surface's existing `viewSql(sql, label)`, which shows SQL read-only without
  running it. The tab is still opened, so the statement is waiting in the editor at a wider width.
- **Chips keep the order filters were set in.** `setFilter` puts an edited filter last, so an edited
  filter's chip moves to the end. That reads as "most recently set last", and it is what array order
  gives without a second ordering rule.
- **The remove control's name carries the whole filter.** `Chip`'s contract is that a truncated name
  stays reachable through the remove button's accessible name, so the name is `Remove filter: <label>`
  rather than naming only the column.
- **Filter the rows on several columns with the existing gestures.** Nothing new is needed there.
  The chips make the combination visible, and the guide says the filters combine.

## Scope

### In Scope

- The chip list of column filters beside the expression box (FR-001).
- Removing one filter from its chip (FR-002).
- **Open in Query** and the Query workspace's one-time read of it (FR-003).
- The registry row and the Data Explorer's *Filter and sort* and *Save as query* guides (FR-004).
- Tests from each side of the hand-off. The Explorer side uses the router state SPEC-242 adds to
  `renderWithProviders`. The Query side needs `renderWorkspace` in `src/test/queryWorkspaceSupport.tsx`
  to accept `{pathname, state}` as well, and this spec widens it.

### Out of Scope

- **Parsing SQL back into the exploration**, or editing the generated SQL in the Data Explorer.
- **Editing a filter from its chip.**
- **Chips for the sort, the grouping or the expression.** The expression is already visible in its
  box, and sorts show on the column headers.
- **Saving filters in a new way.** *Save as query* saves the SQL. Opening a `.sql` file as an
  exploration source stays deferred.
- **Running the statement automatically in Query.**
- **Carrying a Query tab back into the Data Explorer.** SPEC-242 opens a query result there.

---

## Functional Requirements

### FR-001: Every column filter shows as a chip beside the expression box

#### Description:

`ExplorationResultsRegion` renders, directly after `ExpressionBar`, a `ChipList` named
"Column filters" holding one `Chip` per entry of the applied `query.filters`, in array order. It
renders nothing when there are none. `filterChipLabel(filter)` builds each chip's `name`:
`<column> <FILTER_OPERATOR_LABELS[operator]>`, followed by a space and the value where the operator
has one.

- A value is shown bare when the filter's `valueKind` is `'number'` and the operator is a comparison
  or a list operator. Every other value is quoted as `“<value>”`: a string kind, an absent
  `valueKind`, and every value of the four text operators, which SPEC-238 always quotes.
- An empty string is shown as `(empty)`, never quoted.
- A list shows its values de-duplicated and in canonical order (SPEC-238 FR-002), joined by `, `.
  With more than three values it shows the first three, then ` and <n> more`, where n counts the
  de-duplicated values not shown.

#### Acceptance Criteria:

- [ ] Filters `[= 'NY' on state, > 5 (number) on qty]` render a list named "Column filters" with the
  chips `state equals “NY”` and `qty greater than 5`, in that order.
- [ ] `in ['Zyrtec', 'Abilify']` on `brnd_name` renders `brnd_name is one of “Abilify”, “Zyrtec”`.
- [ ] `in ['e', 'd', 'c', 'b', 'a', 'a']` renders `c is one of “a”, “b”, “c” and 2 more` for a column
  named `c`.
- [ ] `contains` with `valueKind: 'number'` and value `5` renders `name contains “5”`.
- [ ] `isEmpty` on `last_name` renders `last_name is empty`, and `= ''` renders `name equals (empty)`.
- [ ] With an expression applied and no filters, once the *Filter expression* input shows the applied
  expression, no "Column filters" list is in the accessible tree.

### FR-002: Removing a chip removes that one filter

#### Description:

Each chip's remove label is `Remove filter: <label>`, with the label `filterChipLabel` built.
Activating it applies `clearFilter(query, column)` through the region's single `apply`, so it is one
description change: at most one execution and one history entry. Focus then moves to the next chip's
remove control, or the previous one when it was last, or the *Filter expression* input when no chips
remain. The region finds the chip's remove control by querying, within a wrapper it holds a ref to,
for the button with that accessible name. `ExpressionBar` gains an `inputRef` prop for the last case.

#### Acceptance Criteria:

- [ ] With filters on `state` and `qty`, activating `Remove filter: state equals “NY”` produces one execution
  whose SQL has the `qty` predicate and no `state` predicate, and the tab's history `past` grows
  by one.
- [ ] After that, focus is on `Remove filter: qty greater than 5`.
- [ ] Removing the only chip moves focus to the *Filter expression* input.
- [ ] *Back* after the removal restores both filters and both chips.

### FR-003: Open in Query hands the statement to a new Query tab

#### Description:

`GeneratedSqlDisclosure` gains an optional `onOpenInQuery`. When it is given, and `sql` is not null,
an **Open in Query** button renders beside the copy button, mounted under the same rule, only while
the disclosure is open. The Data Explorer gives the prop only when the `query` flag is on. Activating
it navigates to `/query` with router state `buildOpenSqlHandoff({sql, label})`, which is
`{openSql: {sql, label}}`, where `sql` is the disclosure's own `sql` string and `label` is the
exploration tab's label. The statement never goes in the URL.

`DataExplorerWorkspace` supplies the tab's label and the navigation through a new region prop,
`onOpenInQuery`, which the region passes to the disclosure only when the `query` flag is on.

`QueryWorkspace` reads that state with `readOpenSqlHandoff`, once, guarded by a ref holding the
`location.key` it last consumed.
It calls `tabs.openTab({label, sql})`, which makes the new tab active, and below `tablet` it also calls
the mobile surface's `viewSql(sql, label)`. It then replaces the history entry as described below. It does not run the statement. When `openTab` returns null it raises its tab-limit dialog
and opens nothing. State whose `openSql` is not an object with a string `sql` and a string `label` is
ignored, and nothing is replaced. The entry is replaced, keeping its path and search, whenever the
reader accepts the state, including when the tab limit refuses the tab.

#### Acceptance Criteria:

- [ ] With the disclosure open and `query` on, **Open in Query** is present. With the disclosure open
  and `query` off, once the copy button is present, **Open in Query** is absent. With `sql` null it is
  absent once the disclosure shows `NO_GENERATED_SQL`.
- [ ] From the Explorer side: activating it on a tab labelled `orders` navigates to `/query` with state
  `{openSql: {sql: <the disclosure's sql>, label: 'orders'}}` and no query string.
- [ ] From the Query side: rendering `QueryWorkspace` under `<StrictMode>` at `/query` with that state
  opens exactly one new tab, active, labelled `orders`, whose editor text equals the `sql` exactly,
  and starts no execution. Afterwards the history state carries no `openSql`.
- [ ] Below `tablet`, the same state opens the tab and shows the read-only SQL view titled `orders`.
- [ ] At `QUERY_TABS_MAX` the hand-off raises the tab-limit dialog, the tab count is unchanged, and
  the history state no longer carries `openSql`.
- [ ] `readOpenSqlHandoff(buildOpenSqlHandoff({sql: 'SELECT 1', label: 'x'}))` returns
  `{sql: 'SELECT 1', label: 'x'}`.
- [ ] `readOpenSqlHandoff` returns null for `{openSql: {sql: 1}}`, `null` and `{}`, and
  `QueryWorkspace` given such state opens nothing and raises nothing.
- [ ] Returning to `/explore` after the hand-off shows the tab whose `exploration.query`,
  `exploration.presentation` and `history` equal what they were before it.

### FR-004: The registry and the guides

#### Description:

`gatedSurfaces.ts` gains *Open in Query* as a `control` on `/explore` under `query`, on the
*Save as query* precedent. The *Filter and sort* guide says the filters set from column menus show
as chips beside the expression box, that they all apply together with the expression, and that a
chip's **×** removes that filter. The *Save as query* guide (`explore-save-as-query`), which is where
the Help already describes *Generated SQL*, says **Open in Query** copies the statement into a new Query tab to edit and run there, and
that changes there do not come back to the exploration.

#### Acceptance Criteria:

- [ ] `gatedSurfaces.test.tsx` passes with the new row, whose recipe reaches a non-null `sql` and opens
  the disclosure, and fails if the button renders with `query` off.
- [ ] The guides carry the sentences. This is static copy, so the diff review checks it.

---

## API / Interface Contract

```ts
// apps/portal/src/features/data-explorer/explorationQueryOps.ts
export function filterChipLabel(filter: ColumnFilter): string;

// apps/portal/src/features/data-explorer/GeneratedSqlDisclosure.tsx
export type GeneratedSqlDisclosureProps = {
  sql: string | null;
  /** Present only when the `query` flag is on. */
  onOpenInQuery?: (sql: string) => void;
};

// apps/portal/src/lib/routeHandoff.ts, beside SPEC-242's explore hand-off
export type OpenSqlHandoff = {openSql: {sql: string; label: string}};
export function buildOpenSqlHandoff(handoff: {sql: string; label: string}): OpenSqlHandoff;
export function readOpenSqlHandoff(state: unknown): {sql: string; label: string} | null;

// apps/portal/src/features/data-explorer/ExpressionBar.tsx — ExpressionBarProps gains
inputRef?: React.Ref<HTMLInputElement>;

```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/explorationQueryOps.ts (+ test)       (FR-001)
apps/portal/src/features/data-explorer/ExplorationResultsRegion.tsx          (FR-001–FR-003)
apps/portal/src/features/data-explorer/ExpressionBar.tsx                     (FR-002: inputRef)
apps/portal/src/features/data-explorer/DataExplorerWorkspace.tsx             (FR-003: label, navigation)
apps/portal/src/features/data-explorer/GeneratedSqlDisclosure.tsx (+ test)   (FR-003)
apps/portal/src/features/data-explorer/filtering.test.tsx                    (FR-001, FR-002)
apps/portal/src/features/query/QueryWorkspace.tsx (+ QueryWorkspace.test.tsx) (FR-003)
apps/portal/src/lib/routeHandoff.ts (+ routeHandoff.test.ts)                (FR-003)
apps/portal/src/test/queryWorkspaceSupport.tsx                               (renderWorkspace router state)
apps/portal/src/features/feature-flags/gatedSurfaces.ts (+ gatedSurfaces.test.tsx) (FR-004)
apps/portal/src/features/help/helpContent.ts                                 (FR-004)
apps/portal/info/component-inventory/data-explorer-feature.md, query-feature.md, foundations.md,
  test-utilities.md (the renderWorkspace row)
apps/portal/info/component-inventory/shared-components.md (the Chip row no longer says "recipient")
```

## Implementation Phases

### Phase 1: The chips

- `filterChipLabel`, the chip list, removal and focus (FR-001, FR-002).

### Phase 2: Open in Query, the registry and Help

- The disclosure's button, the router state, Query's one-time read, the registry row and the guides
  (FR-003, FR-004).
- The live check, run from a signed-in session after deploy: in the Data Explorer, filter one
  column from its menu and another with **is one of**. Both chips show beside the expression box.
  Remove one and the grid updates. Open *Generated SQL*, choose **Open in Query**, and a new Query
  tab holds the statement, not yet run. Edit it and run it, then return to the Data Explorer, where
  the exploration is as it was. Fold it into `docs/testing/e2e.md` at completion.
