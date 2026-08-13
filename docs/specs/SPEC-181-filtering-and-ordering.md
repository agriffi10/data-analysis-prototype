# Spec: Filtering and Ordering

**ID:** SPEC-181
**Status:** Draft
**Last Updated:** 2026-08-13
**Depends On:** SPEC-178, SPEC-180

## Overview

This is the spec the feature exists for, and the only place in the Data Explorer where a user
gesture spends money. Every filter and every sort renders new SQL through SPEC-178's builder,
mints a new Athena execution, and reports what it scanned. Nothing is filtered or sorted in the
browser: a client-side sort over the rows that happen to be loaded is a lie a grid this
Excel-like would tell convincingly, and the whole point of the server-side choice was not to
tell it.

Two things need care. Filters apply on an **explicit gesture** — never per keystroke, because a
keystroke would be a query. And the per-column menus compose SQL around values that arrive from
data rather than from a user's keyboard, which is exactly the interpolation hazard SPEC-178's
`sqlLiteral` exists for; a cell containing `O'Brien` filtered by `=` is the whole problem in one
click, and it arrives from real data long before anyone thinks to type it.

## Scope

### In Scope

- A per-column header menu: order ascending/descending, filter by value with six comparison
  operators, `IS NULL` / `IS NOT NULL`.
- **Filter by this cell's value** from the grid.
- The expression bar: a user-authored `WHERE` fragment in raw SQL.
- Multi-column ordering with explicit priority.
- The Order/Filter settings dialog: visible, pinned, order and criteria per column.
- Filter history — back and forward through this tab's recent query descriptions.
- Remove all filters and orderings.
- Per-apply cost reporting, and the cumulative total per tab.

### Out of Scope

- **Named, saved, persisted filters.** History is per tab and per session. A named filter
  implies a store, and SPEC-173's `.sql`-files-in-a-folder is the precedent for what a store
  costs. Deliberately excluded from the arc.
- **Grouping.** The `Grouping` type renders in SPEC-178; its panel is SPEC-182.
- **Any client-side filtering or ordering**, including a "sort the loaded rows" convenience.
  DBeaver offers a server/client toggle; this feature does not, because the client half cannot
  be made honest at Athena scale.
- Column visibility and pinning as *behaviours* — SPEC-180 owns them. This spec only surfaces
  them again inside the settings dialog.

---

## Functional Requirements

### FR-001: The per-column header menu

#### Description:

Each column header carries a menu offering ordering and the common filters for that column,
composed from the `Menu` primitive.

#### Acceptance Criteria:

- [ ] The menu offers: Sort ascending, Sort descending, Clear sort; Filter by value with `=`,
      `<>`, `>`, `>=`, `<`, `<=`; `IS NULL`; `IS NOT NULL`.
- [ ] A filter taking a value opens an input; submitting applies it, and cancelling applies
      nothing.
- [ ] Every value is rendered through `sqlLiteral` — a test filters on a value containing a
      single quote and asserts the query succeeds and returns the matching row.
- [ ] Every column reference is rendered through `sqlIdentifier`, and column names are **not**
      validated against `CATALOG_IDENTIFIER_RE` — column names are not catalog-safe.
- [ ] Applying from the menu mints exactly one execution.
- [ ] The menu's accessible name identifies its column, so a registry-style query can tell two
      columns' menus apart.

### FR-002: Filter by this cell's value

#### Description:

The fastest path to a filter is the cell already showing the value.

#### Acceptance Criteria:

- [ ] The grid offers "Filter by this value" for the focused cell, producing an `=` filter on
      that cell's column.
- [ ] The value used is the **raw** cell value, not its formatted or transformed rendering —
      a transformed URL or a reformatted number must not become the predicate (SPEC-184).
- [ ] A `NULL` cell produces `IS NULL`, not `= ''`. Athena returns every value as a string, so
      this distinction is the app's to make.
- [ ] Applying replaces any existing filter on that column rather than accumulating a second
      contradictory one.

### FR-003: The expression bar

#### Description:

A free-text `WHERE` fragment above the grid, applied on an explicit gesture. It is the user's
own SQL and is composed verbatim, exactly as Monaco's buffer is.

It is **not gated on the `query` flag**. A flag is presentation, never authorization
(SPEC-162): it revokes no grant, the IAM boundary is identical either way, and gating this
input would buy nothing while making the feature unable to express what people actually filter
on. The accepted cost is stated plainly — an environment that turns `query` off to tidy SQL away
will still be offering a SQL input here.

#### Acceptance Criteria:

- [ ] The bar applies on Enter or on an explicit Apply control, and **never** on change — a test
      types a full expression and asserts zero executions until the gesture.
- [ ] The fragment is composed without passing through `sqlLiteral`.
- [ ] When both an expression and column filters are present each side is parenthesized and
      joined with `AND`, so an expression containing `OR` cannot capture a filter.
- [ ] An Athena syntax error renders through `toUserMessage` — the raw engine text never reaches
      the user (SPEC-106) — and the bar keeps the offending text so it can be corrected.
- [ ] A failed apply leaves the previous execution's rows on screen rather than emptying the
      grid.
- [ ] The bar is present with `query` off, and a test asserts it.

### FR-004: Multi-column ordering

#### Description:

Ordering is a prioritized list, not a single column.

#### Acceptance Criteria:

- [ ] Adding a second sorted column appends it at the next priority; the rendered `ORDER BY`
      lists columns in priority order.
- [ ] Priority is reorderable in the settings dialog.
- [ ] Clearing one column's sort leaves the others' relative priorities intact and contiguous.
- [ ] The header shows each sorted column's direction and its priority position.
- [ ] Sorting by a column and then unsorting it returns to the unsorted execution from cache,
      issuing no new query (SPEC-178 FR-006).

### FR-005: The Order/Filter settings dialog

#### Description:

One dialog holding every column's visibility, pinning, sort priority and criteria — the place to
make several changes and apply them as one query rather than one query per gesture.

#### Acceptance Criteria:

- [ ] Every column appears with its visible, pinned, order and criteria state.
- [ ] Changes are staged and applied together: closing with Apply mints **one** execution
      however many criteria changed.
- [ ] Cancelling discards every staged change, including the presentation ones.
- [ ] Visibility and pinning changes apply without an execution even when made here, because
      they render no SQL.
- [ ] Built on `FormDialog`, with implicit submission suppressed and exactly one field
      submitting on Enter (SPEC-155) — a criteria row mid-edit must not file the whole dialog.
- [ ] `<select>` elements are covered by that suppression, as `DestinationPicker` also needed
      (SPEC-175).

### FR-006: Filter history

#### Description:

Back and forward through this tab's recent query descriptions, so an experiment is cheap to
undo.

#### Acceptance Criteria:

- [ ] Applying any change pushes the previous description onto the tab's history.
- [ ] Back and forward restore a description and re-render its SQL; if that SQL has already run,
      the result comes from cache and **no** execution is issued.
- [ ] History is capped, per tab, and held in `sessionStorage` with the tab state.
- [ ] Navigating history never re-runs a query that failed; it restores the description and
      leaves the retry to the user.
- [ ] History holds descriptions, not result sets.

### FR-007: Remove all

#### Acceptance Criteria:

- [ ] One control clears every filter, the expression and every sort in a single apply.
- [ ] It is disabled with `Button.disabledReason` when there is nothing to clear.
- [ ] Clearing returns to the unfiltered execution, from cache when it is still held.

### FR-008: Cost is reported on every apply

#### Description:

Every apply is a bill, and Athena offers no pre-flight estimate, so reporting is the only honest
signal available.

#### Acceptance Criteria:

- [ ] After each execution the surface shows that execution's bytes scanned, through
      `formatBytes`.
- [ ] The tab shows a cumulative bytes-scanned total across its executions.
- [ ] A cache hit adds nothing to the total and says so rather than showing a stale figure.
- [ ] The delivery doc records that a pre-flight "this looks expensive" confirm is **not
      buildable** — Athena will not report what a query will scan before running it — so the
      guards are the workgroup's per-query cutoff and this reporting.

---

## Data Model

No new persisted types; this spec fills in SPEC-178's `ExplorationQuery`. The history addition:

```ts
// dataExplorer.types.ts

export type QueryHistoryCursor = {
  /** Previous descriptions, oldest first, capped at EXPLORER_FILTER_HISTORY_MAX. */
  past: ExplorationQuery[];
  /** Descriptions stepped back past, for forward navigation. */
  future: ExplorationQuery[];
};
```

```ts
// dataExplorer.constants.ts
export const EXPLORER_FILTER_HISTORY_MAX = 25;
```

---

## API / Interface Contract

```ts
export function useExplorationQuery(tabId: string): {
  query: ExplorationQuery;
  /** Stages a change without executing; used by the settings dialog. */
  stage: (next: Partial<ExplorationQuery>) => void;
  /** Applies staged (or supplied) changes — this is what mints an execution. */
  apply: (next?: Partial<ExplorationQuery>) => void;
  clearAll: () => void;
  canGoBack: boolean;
  canGoForward: boolean;
  back: () => void;
  forward: () => void;
};
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── ColumnFilterMenu.tsx
├── ExpressionBar.tsx
├── OrderFilterDialog.tsx
├── FilterHistoryControls.tsx
├── CostIndicator.tsx
├── useExplorationQuery.ts
├── filtering.test.tsx
├── ordering.test.tsx
└── expressionBar.test.tsx
```

---

## Implementation Phases

### Phase 1: Column menu and cell filters

- The header menu, the value input, and the `sqlLiteral` / `sqlIdentifier` paths end to end.
- Filter by this cell's value, including the `NULL` and raw-value rules.

### Phase 2: Ordering

- Multi-column priority, header indicators, and the cache-hit assertion on unsort.

### Phase 3: The expression bar and the settings dialog

- The bar, its explicit-apply rule, its error path and its ungated presence.
- The staged dialog applying as one execution.

### Phase 4: History, clear-all and cost

- The per-tab description history with its cache-hit behaviour.
- Remove-all with its disabled reason, and the cost indicators.
