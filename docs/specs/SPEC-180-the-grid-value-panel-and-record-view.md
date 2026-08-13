# Spec: The Grid, Cell Selection, the Value Panel and the Record View

**ID:** SPEC-180
**Status:** Draft
**Last Updated:** 2026-08-13
**Depends On:** SPEC-178, SPEC-179

## Overview

This spec replaces SPEC-179's placeholder table with the grid the feature exists for: resizable,
reorderable, pinnable, hideable columns; a real cell cursor with range selection; a Value panel
for content a cell cannot show; and two alternative presentations of the same rows — Record
(transposed) and Text.

Cell **range selection** is the piece to take seriously. It is the substrate the Calc panel
stands on in SPEC-182, it carries the copy behaviour in SPEC-185, and a grid with a selection
model is an accessibility problem in a way a static table is not. It is specified here in full
rather than discovered later.

One requirement arrives from SPEC-178's source union and would be expensive to retrofit: a
`table` source knows its columns from Glue before any query runs, but a `sql` source learns them
only from the first execution's `ResultSetMetadata`. The grid must handle both from the start,
even though the `sql` arm has no UI until SPEC-183.

## Scope

### In Scope

- The grid: column resize, drag-reorder, pin, hide/show, row numbers.
- A cell cursor and rectangular range selection, by mouse and keyboard.
- The Value panel — a side surface for long text and complex values.
- The Record (transposed) presentation and the Text presentation.
- The presentation half of `ExplorationPresentation`, none of which renders SQL.
- Columns-unknown-until-first-execution handling.
- Mobile: Record as the default presentation below `tablet`.

### Out of Scope

- **Filtering and ordering.** The column header menu is SPEC-181's; this spec ships headers
  that resize, drag and pin, and leaves the menu trigger to it.
- **Calc.** Selection is built here; aggregating over it is SPEC-182.
- **Copy.** Selection is built here; copying it is SPEC-185.
- **Colouring, striping and transformers** — SPEC-184.
- **Editing.** The Data Explorer is read-only. No inline edit, no cell editor, no row add,
  duplicate or delete, no save, no generated DML, no virtual keys. Athena results are not an
  editable table, and DBeaver's write half has no counterpart here.
- **The References panel.** Glue has no foreign keys.
- Chart, Spatial, JSON and XML presentations.

---

## Functional Requirements

### FR-001: Column geometry is presentation and costs nothing

#### Description:

Columns can be resized, dragged into a new order, pinned to the left, and hidden or shown. None
of it renders SQL, so none of it runs a query.

#### Acceptance Criteria:

- [ ] Resize works by pointer drag and by Arrow keys on a focusable handle, clamped at
      `MIN_COLUMN_WIDTH`, reusing SPEC-176's `useColumnWidths` machinery.
- [ ] Drag-reorder moves a column and its cells together; a keyboard alternative exists and is
      announced.
- [ ] Pinned columns stay visible while the body scrolls horizontally, in pinned order.
- [ ] Hiding a column removes it from the grid and from the Record view, and it can be restored.
- [ ] Hiding the **last visible** column is refused, with the reason surfaced through
      `Button.disabledReason` (`aria-disabled`, reason in the tab order, never inside the
      button).
- [ ] Every one of these gestures issues **zero** `StartQueryExecution` calls — asserted by
      count, which is FR-003 of SPEC-178 observed from the UI.
- [ ] Geometry persists per exploration tab across paging and tab switches.

### FR-002: The cell cursor and range selection

#### Description:

The grid has a focused cell and a selection that may span a rectangle of cells, whole columns or
whole rows.

#### Acceptance Criteria:

- [ ] Arrow keys move the cursor; Shift+Arrow extends the selection; Home/End and
      PageUp/PageDown move within the loaded page.
- [ ] Click sets the cursor; Shift+click extends to a rectangle; Ctrl/Cmd+click toggles a
      discontiguous cell into the selection.
- [ ] Clicking a column header selects the column; clicking a row number selects the row.
- [ ] Ctrl/Cmd+A selects every cell on the current page, and the label says so — the selection
      is over loaded rows, never over the whole result.
- [ ] The grid is a single tab stop; the cursor moves within it, matching `role="grid"`
      expectations rather than putting every cell in the tab order.
- [ ] `aria-selected` reflects the selection, and the focused cell is the one with DOM focus.
- [ ] `vitest-axe` reports no violations on the grid with a multi-cell selection active, run
      against the **driven container** rather than a re-render.
- [ ] Paging clears the selection rather than carrying stale coordinates onto different rows.

### FR-003: The Value panel

#### Description:

A side panel showing the focused cell's full value, for content the grid truncates — long text,
JSON-ish strings, anything a cell width cannot hold.

#### Acceptance Criteria:

- [ ] The panel shows the focused cell's complete value, not the truncated rendering.
- [ ] It updates as the cursor moves.
- [ ] It is toggleable, and its open state persists per tab.
- [ ] Values are read-only, selectable and copyable.
- [ ] An empty string and a `NULL` are visibly different — Athena returns every value as a
      string, so this distinction is the app's to make and is easy to lose.
- [ ] The panel is reachable by keyboard and does not trap focus.

### FR-004: The Record presentation

#### Description:

A transposed view of the focused row: one line per column, name beside value. It is the natural
way to read a wide row, and on a phone it is the natural way to read any row.

#### Acceptance Criteria:

- [ ] Switching to Record shows the focused row's columns as rows, in the grid's current column
      order, honouring hidden columns.
- [ ] Next/Previous move between result rows without returning to the grid.
- [ ] Switching back restores the same focused row.
- [ ] The presentation choice persists per tab.
- [ ] No query runs on a presentation switch.

### FR-005: The Text presentation

#### Description:

A fixed-width plain-text rendering of the current page — the shape people paste into a ticket.

#### Acceptance Criteria:

- [ ] Columns align at a monospace width; the header row is present.
- [ ] Hidden columns are absent and column order is honoured.
- [ ] The text is selectable and copyable as displayed.
- [ ] It renders the current page only, and says which rows it is showing.

### FR-006: Columns may be unknown until the first execution

#### Description:

A `table` source has its schema from Glue before any query runs; a `sql` source has none until
the first execution returns `ResultSetMetadata`. The grid handles both.

#### Acceptance Criteria:

- [ ] With a `table` source, headers render before results arrive, from the Glue schema.
- [ ] With a `sql` source, the grid renders a loading state with no headers, then adopts the
      columns the execution reports.
- [ ] Column geometry keyed to a column that no longer exists after a re-execution is discarded,
      not applied to whatever column now occupies that position.
- [ ] A grouping change alters the column set entirely; the grid adopts the new columns rather
      than mapping old geometry onto them.

### FR-007: Mobile reflows to Record

#### Description:

Below `tablet`, Record is the default presentation. A horizontally scrolling grid on a 400px
screen is not a data explorer, and Record is already in scope.

#### Acceptance Criteria:

- [ ] Below `tablet` the workspace opens in Record; the user may still switch to Grid.
- [ ] It is one component tree reflowing (SPEC-095) — no `*Mobile` twin component.
- [ ] `useIsMobile` is used for mount-gating only, never for styling.
- [ ] The Value panel becomes a full-width sheet rather than a side panel, and Escape closes it
      through the depth-ordered registry (SPEC-155).

---

## Data Model

```ts
// dataExplorer.types.ts — ExplorationPresentation, extended from SPEC-178

export type GridPresentation = 'grid' | 'record' | 'text';

export type CellRef = {row: number; column: string};

export type Selection = {
  /** The focused cell; always present when the grid has rows. */
  cursor: CellRef;
  /** Rectangles and discontiguous cells, in selection order. */
  ranges: {from: CellRef; to: CellRef}[];
};

export type ExplorationPresentation = {
  hiddenColumns: string[];
  columnOrder: string[];
  pinnedColumns: string[];
  columnWidths: Record<string, number>;
  presentation: GridPresentation;
  valuePanelOpen: boolean;
  /** The Record view's focused row index within the current page. */
  recordRowIndex: number;
};
```

---

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── ExplorationGrid.tsx              # replaces ExplorationResultsTable
├── ExplorationGridHeader.tsx
├── ExplorationRecordView.tsx
├── ExplorationTextView.tsx
├── ValuePanel.tsx
├── PresentationSwitch.tsx
├── useCellSelection.ts
├── useColumnGeometry.ts
├── grid.a11y.test.tsx
├── gridSelection.test.tsx
└── gridPresentations.test.tsx
```

---

## Implementation Phases

### Phase 1: Column geometry

- Resize, reorder, pin, hide/show over `useColumnGeometry`, with the zero-execution assertion.

### Phase 2: Selection

- The cursor, rectangle and discontiguous selection, keyboard and pointer, with the `role="grid"`
  semantics and the axe pass on a live selection.

### Phase 3: The Value panel and the alternative presentations

- Value panel, Record view, Text view, and the persisted presentation choice.

### Phase 4: Unknown columns and mobile

- The `sql`-source column path and geometry invalidation.
- The below-`tablet` Record default and the Value panel's sheet form.
