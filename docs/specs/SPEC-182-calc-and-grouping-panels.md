# Spec: The Calc and Grouping Panels

**ID:** SPEC-182
**Status:** Draft
**Last Updated:** 2026-08-13
**Depends On:** SPEC-180, SPEC-181

## Overview

Two analysis panels that look like siblings and are not. **Calc** aggregates the cells a user
has selected, which exist only in the browser — so it computes client-side, over loaded rows,
and says so. **Grouping** *is* a `GROUP BY` — so it changes the exploration's rendered SQL and
mints an execution like any other query change.

That split is not a compromise between fidelity and cost; it falls out of what each panel is.
Calc over the whole result would require a query per selection change, which is absurd for a
gesture as cheap as dragging across ten cells. Grouping in the browser would aggregate whichever
rows happened to be fetched, which is the scale lie this feature was designed to avoid.

Because grouping generates SQL the user did not write, and because that SQL is an invoice, the
panel shows it. DBeaver's "Query" button is a nicety there; here it is the difference between a
user understanding a charge and not.

## Scope

### In Scope

- The Calc panel: ten aggregate functions over the current cell selection, client-side.
- The Grouping panel: grouping columns and aggregates, rendered into the exploration's SQL.
- The generated-SQL disclosure for grouping.
- Grouping's interaction with the rest of the query description — filters, expression, ordering.
- Leaving grouping mode.

### Out of Scope

- **Any server-side Calc.** It aggregates the selection; a selection is client state.
- **Any client-side grouping.** It renders SQL or it does not exist.
- **Charting the grouped result** — no Chart presentation in this arc.
- **Percent-of-total across the whole table.** See FR-004: the percentage is of the returned
  grouped rows, and is labelled as such.
- Copying the panels' output — SPEC-185.

---

## Functional Requirements

### FR-001: The Calc panel aggregates the selection, client-side

#### Description:

A panel that recomputes as the selection changes, over exactly the cells selected in the grid.

#### Acceptance Criteria:

- [ ] The panel offers Count, Count distinct, Count nulls, Sum, Average, Minimum, Maximum,
      Median and Mode; Count and Count distinct are shown by default.
- [ ] It recomputes on every selection change, including discontiguous selections.
- [ ] Numeric functions ignore non-numeric cells rather than producing `NaN`, and the panel
      reports how many cells were skipped.
- [ ] A numbers/strings toggle switches between numeric-only and mixed aggregation.
- [ ] Functions can be added, removed individually and reset to the default pair.
- [ ] Count nulls counts `NULL`, not the empty string — the same distinction SPEC-180 FR-003 and
      SPEC-181 FR-002 make, and the third place it must not be lost.
- [ ] **Zero executions** are issued by any Calc interaction, asserted by count.

### FR-002: Calc says what it computed over

#### Description:

The panel's honesty requirement. Its numbers describe selected, loaded cells — never the result
set, and never the table.

#### Acceptance Criteria:

- [ ] The panel states the selection it aggregated (cell count, and that it is over loaded
      rows).
- [ ] With nothing selected, the panel explains that rather than showing zeroes, which would
      read as a computed answer.
- [ ] The wording never implies a whole-table figure, and the delivery doc records this as the
      reason the panel is client-side rather than an efficiency choice.

### FR-003: The Grouping panel renders `GROUP BY`

#### Description:

Columns are added to the panel to group by; aggregates are configured against them. Applying
sets the exploration's `grouping` and mints an execution, exactly as a filter does.

#### Acceptance Criteria:

- [ ] Columns are added by drag from a grid header and by an explicit control, in an order the
      user can change; the rendered `GROUP BY` follows that order.
- [ ] `COUNT(*)` is present by default; `SUM`, `AVG`, `MIN` and `MAX` can be added against a
      named column, and `COUNT` alone accepts `*`.
- [ ] Column references go through `sqlIdentifier`; the aggregate function is chosen from a
      closed set and never assembled from user text.
- [ ] Applying mints exactly one execution however many columns and aggregates changed.
- [ ] While grouping is active the grid shows the grouped result — the grouping columns then the
      aggregates — and SPEC-180 FR-006's column-adoption path handles the changed column set.
- [ ] Removing every grouping column leaves grouping mode and returns to the ungrouped
      execution, from cache when still held.

### FR-004: Grouping's extras

#### Description:

The two conveniences that make the panel worth using: finding duplicates, and seeing proportion.

#### Acceptance Criteria:

- [ ] "Show duplicates only" adds a `HAVING COUNT(*) > 1` and is reflected in the disclosed SQL.
- [ ] A percentage column shows each grouped row's share of the **returned grouped rows'** total,
      computed client-side from the result, and is labelled to say so — it is not a share of the
      table.
- [ ] Sorting a grouped result orders by a grouping column or an aggregate; ordering by a column
      that is neither is refused before rendering (SPEC-178 FR-002), with the reason surfaced
      through `Button.disabledReason`.

### FR-005: The generated SQL is disclosed

#### Description:

The panel shows the SQL it produced, because that SQL is what will be billed.

#### Acceptance Criteria:

- [ ] A control reveals the exploration's currently rendered SQL, including the grouping,
      filters, expression and ordering.
- [ ] It is the string `renderExplorationSql` produced — read from the same place the execution
      used, never re-derived for display, so the two cannot drift.
- [ ] It is selectable and copyable.
- [ ] It is available whether or not grouping is active.

### FR-006: Filters and grouping compose

#### Description:

Grouping does not replace the rest of the query description.

#### Acceptance Criteria:

- [ ] Filters and the expression apply in the `WHERE`, before grouping.
- [ ] A filter on a column that is neither grouped nor aggregated is still legal and still
      applies, because it filters rows before the grouping.
- [ ] Clearing all (SPEC-181 FR-007) clears grouping too, and the control's label reflects that.
- [ ] Filter history (SPEC-181 FR-006) records grouping changes like any other description
      change.

---

## Data Model

```ts
// dataExplorer.types.ts

export type CalcFunction =
  | 'count' | 'countDistinct' | 'countNulls'
  | 'sum' | 'avg' | 'min' | 'max' | 'median' | 'mode';

export type CalcPanelState = {
  functions: CalcFunction[];
  /** Numeric-only aggregation when false. */
  includeStrings: boolean;
};

export type CalcResult = {
  fn: CalcFunction;
  value: string;
  /** Cells excluded as non-numeric; surfaced beside the value. */
  skipped: number;
};

/** Extends SPEC-178's Grouping. */
export type Grouping = {
  columns: string[];
  aggregates: GroupingAggregate[];
  duplicatesOnly: boolean;
  showPercentage: boolean;
};
```

```ts
// dataExplorer.constants.ts
export const CALC_DEFAULT_FUNCTIONS: CalcFunction[] = ['count', 'countDistinct'];
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── CalcPanel.tsx
├── GroupingPanel.tsx
├── GeneratedSqlDisclosure.tsx
├── calc.ts                 # the pure aggregate functions
├── calc.test.ts
├── calcPanel.test.tsx
└── groupingPanel.test.tsx
```

---

## Implementation Phases

### Phase 1: Calc

- The pure aggregates over a selection, including the null/empty-string distinction and the
  non-numeric skip count.
- The panel, its function management, and the zero-execution assertion.

### Phase 2: Grouping

- Columns and aggregates into `ExplorationQuery.grouping`; the one-execution apply.
- The changed-column-set path into SPEC-180's grid.

### Phase 3: Extras and disclosure

- Duplicates-only, the labelled percentage, and the ordering refusal.
- The generated-SQL disclosure, read from the executed string.
