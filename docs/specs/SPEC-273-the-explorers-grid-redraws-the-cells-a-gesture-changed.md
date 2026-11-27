---
type: Spec
id: SPEC-273
title: "The Explorer's Grid Redraws the Cells a Gesture Changed"
description: "Narrows what a column drag, a cursor move, a presentation edit and a tick in the value picker cost in the Data Explorer: none redraws a cell it did not change, none re-renders the statement, and the tabs are written to session storage once per pause."
spec_status: Draft
depends_on: [SPEC-272]
arc: render-scope
arc_order: 3
---

**Dependency notes:** SPEC-272 delivers `lib/coalescedWrite.ts`, which FR-004 stores through. The
arc's opening change landed `apps/portal/src/test/renderCounter.tsx`, which every budget below is
counted with.

## Overview

The Data Explorer keeps a tab's whole description, the query and the way its result is presented,
at the top of the workspace and writes every tab to session storage whenever any of it changes. A
column's width is part of that description, so dragging a column's edge redraws the workspace,
re-renders the statement and writes storage on every pointer move. The grid's cells are drawn by
one component, so moving the cursor one cell redraws all of them. Measured before this spec on a
100-row by 10-column page with five tabs open, one pointer move of a column drag re-walked 3,516
fibers, rendered all 1,000 cells and wrote 2,382 characters to session storage; one Arrow key
re-walked 3,485 fibers and rendered all 1,000 cells. This spec makes each gesture cost the cells it
changes. Nothing a user does changes.

## Scope

### In Scope

- What a column-resize move, a cursor move, a selection change and a presentation-only edit render
  in the Data Explorer, and whether they re-render the statement.
- When the Explorer's tabs are written to session storage.
- What ticking a value in **Filter by value…** renders.
- A render-scope suite for the Explorer whose budgets fail when any of the above regresses.

### Out of Scope

- **`features/catalog/ColumnResizeHandle.tsx`.** Shared with the Query workspace; neither spec of
  this arc changes it.
- **Windowing the grid or the value picker.** A page is 100 rows, and the picker lists at most
  1,000 values by a recorded decision; once a tick renders one row neither length multiplies a
  gesture's cost.
- **What the renderer takes.** `renderExplorationSql(source, query)` keeps its two arguments; this
  spec changes how often it is called, never what it is given.
- **What a selection means.** Ranges, the cursor, copy and Calc are unchanged.
- The data-quality list's fan-out, which SPEC-272 bounds.

---

## Functional Requirements

### FR-001: A column-resize drag redraws no cell and re-renders no statement

#### Description:

The grid's rows are memoised, and a row's props do not change when an unpinned column's width
does: widths reach the table through its `<colgroup>`. `useExploration` memoises the rendered
statement on the exploration's source and query, the renderer's two arguments, so an edit to the
presentation alone renders nothing.

#### Acceptance Criteria:

- [ ] One pointer move of a drag on an unpinned column renders `CellValue` zero times (before this
      spec: once per cell on the page) and calls `renderExplorationSql` zero times.
- [ ] The dragged column's `<col>` carries the new width after each move, the handle's
      `aria-valuenow` follows it, and the width is clamped as today.
- [ ] Dragging a pinned column still moves the sticky offset of every pinned column after it.
- [ ] The `CellValue` assertion fails when the row's memo is removed (mutation-tested once,
      recorded in the delivery doc).

### FR-002: A cursor move redraws the rows whose selection changed

#### Description:

A row receives only what it needs to draw itself: its values, the columns, its formatting, and its
own share of the selection, in a form that keeps its identity when that share does not change. The
selection model answers whether a cell is selected from a map of column positions built once per
column set, not by searching the column list for every cell.

#### Acceptance Criteria:

- [ ] With a 100-row page and the cursor on a cell, one **ArrowDown** renders `CellValue` at most
      twice per visible column: the row the cursor left and the row it entered (before this spec:
      once per cell on the page).
- [ ] **Shift+ArrowDown**, extending the selection by one row, renders `CellValue` at most twice
      per visible column.
- [ ] Clicking a column header, which selects every row, still marks every cell of that column
      selected.
- [ ] Focus still follows the cursor, the grid is still one tab stop, and the copied text and the
      Calc panel's figures are unchanged: the existing selection, copy and Calc suites pass with no
      assertion weakened.

### FR-003: An edit that changes neither the result nor the columns redraws no cell

#### Description:

`useExplorationTabs` returns actions whose identity is stable for the life of the hook. The
workspace hands the results region a stable `onPresentationChange`, and the region memoises the
visible column names and the column actions it hands the grid.

#### Acceptance Criteria:

- [ ] Opening the Value panel, a presentation edit that changes no column and no row, renders
      `CellValue` zero times and calls `renderExplorationSql` zero times.
- [ ] Recording an execution's scanned bytes against a tab renders `CellValue` zero times.
- [ ] Two tabs opened in one task still both open, and the third past the cap is still refused:
      the existing tab suites pass with no assertion weakened.

### FR-004: The tabs are written to session storage once per pause

#### Description:

`useExplorationTabs` stores through SPEC-272's coalesced writer, `EXPLORATION_TABS_PERSIST_DELAY_MS`
(300) after the last change, and flushes when it unmounts and on the window's `pagehide`. Every criterion below that names the delay is decided on a fake clock (`src/test/fakeTimers.ts`), and one of them runs under the harness's `strictMode`, whose doubled effects must not lose a write.

#### Acceptance Criteria:

- [ ] A column drag of twenty pointer moves writes `sessionStorage` zero times while the moves are
      delivered inside one delay, and once after it, holding the final width (before this spec:
      once per move).
- [ ] Unmounting the workspace inside the delay writes the latest state before the unmount
      completes, so the next mount restores it.
- [ ] A `pagehide` inside the delay writes the latest state.
- [ ] A filter applied and the tab then reloaded after the delay restores the filter.

### FR-005: Ticking a value redraws that value's row

#### Description:

A listed value is drawn by a memoised row component, `ValueRow`, and whether a value is ticked is
answered from a set built once per selection, not by searching the selection for every row.

#### Acceptance Criteria:

- [ ] With 1,000 values listed and 500 ticked, ticking one more renders `ValueRow` exactly once
      (before this spec every listed row is redrawn, each searching the selection).
- [ ] Search still narrows the list without a query, **Select all shown** still ticks what is
      shown, `(empty)` and `NULL` still behave as their decision records, and a value ticked and
      then filtered out of the list is still listed as also selected: the existing picker suites
      pass with no assertion weakened.

---

## Data Model

```ts
// src/features/data-explorer/dataExplorer.constants.ts
export const EXPLORATION_TABS_PERSIST_DELAY_MS = 300;

// src/features/data-explorer/useCellSelection.ts
export type RowSelection = {
  /** Positions, in display order, of this row's selected cells. */
  selected: ReadonlySet<number>;
  /** Position of the cursor in this row, or -1. */
  cursor: number;
};
// Returned by the hook: the row's share, the SAME object while that share is unchanged.
rowSelection: (row: number) => RowSelection;
```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── ExplorationGrid.tsx              (rows drawn by a memoised row component)
├── useCellSelection.ts              (per-row selection, a position map)
├── useExploration.ts                (the statement memoised on source and query)
├── useExplorationTabs.ts            (stable actions, coalesced storage)
├── DataExplorerWorkspace.tsx        (a stable onPresentationChange)
├── ExplorationResultsRegion.tsx     (memoised visible names and actions)
├── FilterValuePicker.tsx            (a memoised ValueRow, a set for membership)
└── explorerRenderScope.test.tsx     (the budgets)
```

## Implementation Phases

### Phase 1: Baseline, then the drag

- Add the render-scope suite in its measuring form and record the baseline at that commit.
- Memoised rows, the statement memoised on its two inputs, coalesced storage (FR-001, FR-004).

### Phase 2: The selection and the memo chains

- Per-row selection and the position map (FR-002).
- Stable tab actions, `onPresentationChange`, visible names and column actions (FR-003).

### Phase 3: The value picker, budgets, close-out

- The memoised value row and set membership (FR-005).
- Turn the suite's measurements into asserted budgets and mutation-test FR-001's.
- Completion ritual: the delivery doc carries the before and after counts, each anchored to its
  commit; the signed-in pass stays owed in `docs/testing/owed.md`.
