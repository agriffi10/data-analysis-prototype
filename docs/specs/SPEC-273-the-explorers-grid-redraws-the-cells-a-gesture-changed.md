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
- The data-quality list's fan-out, which SPEC-274 bounds.

---

## Functional Requirements

**How every budget below is asserted.** A count of zero is also what a misspelled component name
or a gesture that did nothing reports. So each test that asserts a zero also asserts, in the same
test, the gesture's visible effect and one component that the gesture must render, by a count
above zero. Every budget in this spec is mutation-tested once: the memo, the stable identity or
the placement it rests on is reverted, the test is seen to fail on that count, and the mutation is
recorded in the delivery doc.

### FR-001: A column-resize drag redraws no cell and re-renders no statement

#### Description:

The grid's rows are memoised, and nothing a row receives changes when an unpinned column's width
does. That is not true of anything the geometry returns today: `useColumnGeometry` rebuilds every
column object on a width change, and the row's columns, the page's formatting, the selection's
column names and the pinned offsets are all derived from those objects. So the geometry also
returns a width-free list of the columns, hidden ones included, whose identity survives a
width-only change. The rows, the page formatting and the selection are computed from that list.
Widths go to the `<colgroup>` and the header alone. The pinned offsets keep their identity unless
a pinned column's width changes.

`useExploration` memoises the rendered statement on the exploration's source and query, the
renderer's two arguments, so an edit to the presentation alone renders nothing.

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

A row receives only what it needs to draw itself: its values, the width-free columns, its
formatting, and its own share of the selection. The share is passed as primitives, a string naming
the row's selected positions and the cursor's position as a number, so two equal shares compare
equal with no object identity carried from one render to the next. The selection model answers
whether a cell is selected from a map of column positions built once per column set, not by
searching the column list for every cell.

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
visible column names. The column header and its menus are not part of this spec: their actions
close over the tab's query, and they may render on any edit.

#### Acceptance Criteria:

- [ ] Opening the Value panel, a presentation edit that changes no column and no row, renders
      `CellValue` zero times and calls `renderExplorationSql` zero times, and renders the panel.
- [ ] Two tabs opened in one task still both open, and the third past the cap is still refused:
      the existing tab suites pass with no assertion weakened.

### FR-004: The tabs are written to session storage once per pause

#### Description:

`useExplorationTabs` stores through SPEC-272's coalesced writer with
`EXPLORATION_TABS_PERSIST_DELAY_MS` (300). The state the hook mounts with is written at once, as
today; every later change is coalesced. The hook flushes when it unmounts and on the window's
`pagehide`, and after it has unmounted it writes nothing and starts no timer.

Every criterion below that names the delay is decided on a fake clock (`src/test/fakeTimers.ts`).

**Existing suites change in how they read storage, and in nothing they assert.** A suite that reads
the tabs' storage after a gesture now reads it after a flush: the fake clock advanced past the
delay, or the workspace unmounted. `useExplorationTabs.test.ts`, `heldTab.test.tsx`,
`filterBuilder.test.tsx` and `formattingUi.test.tsx` are known to; every other suite that reads
`EXPLORATION_TABS_STORAGE_PREFIX` is checked the same way. **A negative read flushes first.** An
assertion that something was not stored passes for the wrong reason while a write is merely
pending, so `exploreHandoff.test.tsx`, `savedViewRefusal.test.tsx` and any other such assertion
flush before they read.

#### Acceptance Criteria:

- [ ] A column drag of twenty pointer moves inside one delay writes `sessionStorage` zero times
      during the moves and once after the delay, holding the final width (measured before this
      spec: one write per move).
- [ ] Unmounting the workspace inside the delay writes the latest state before the unmount
      completes, so the next mount restores it; this criterion also runs under the harness's
      `strictMode`, whose doubled effects must neither lose the write nor leave a timer.
- [ ] A `pagehide` inside the delay writes the latest state.
- [ ] A filter applied, and the workspace remounted after the delay, restores the filter.
- [ ] A tab action called after the hook has unmounted writes nothing and leaves no timer.

### FR-005: Ticking a value redraws that value's row

#### Description:

A listed value is drawn by a memoised row component, `ValueRow`, and whether a value is ticked is
answered from a set built once per selection, not by searching the selection for every row. The
set is keyed so that it agrees with `sameValue`, which compares numbers by value: two spellings of
one number are one member. The handler a row is given keeps its identity across a tick, and reads
the selection as it stands when it is called.

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
// Returned by the hook. Primitives, so equal shares are equal props.
rowSelection: (row: number) => {
  /** The row's selected positions in display order, joined; '' when none. */
  selected: string;
  /** Position of the cursor in this row, or -1. */
  cursor: number;
};

// src/features/data-explorer/useColumnGeometry.ts
/** A column without its width. */
export type RowColumn = Pick<GridColumn, 'name' | 'type' | 'index' | 'pinned' | 'hidden'>;
// Added to UseColumnGeometryResult: the same array while only widths change.
rowColumns: RowColumn[];
```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── ExplorationGrid.tsx              (rows drawn by a memoised row component)
├── useColumnGeometry.ts             (a width-free column list)
├── useCellSelection.ts              (per-row selection, a position map)
├── useExploration.ts                (the statement memoised on source and query)
├── useExplorationTabs.ts            (stable actions, coalesced storage)
├── DataExplorerWorkspace.tsx        (a stable onPresentationChange)
├── ExplorationResultsRegion.tsx     (memoised visible names; formatting from the width-free list)
├── FilterValuePicker.tsx            (a memoised ValueRow, a set for membership)
└── explorerRenderScope.test.tsx     (the budgets)
```

## Implementation Phases

### Phase 1: Baseline, then the drag

- Add the render-scope suite in its measuring form and record the baseline at that commit.
- The width-free column list, memoised rows, the statement memoised on its two inputs, coalesced
  storage (FR-001, FR-004).

### Phase 2: The selection and the memo chains

- Per-row selection and the position map (FR-002).
- Stable tab actions, `onPresentationChange` and visible names (FR-003).

### Phase 3: The value picker, budgets, close-out

- The memoised value row and set membership (FR-005).
- Turn the suite's measurements into asserted budgets and mutation-test FR-001's.
- Completion ritual: the delivery doc carries the before and after counts, each anchored to its
  commit; the signed-in pass stays owed in `docs/testing/owed.md`.
