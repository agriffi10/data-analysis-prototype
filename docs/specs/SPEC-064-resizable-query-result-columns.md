# Spec: Resizable Query-Result Columns

**ID:** SPEC-064
**Status:** Completed
**Last Updated:** 2026-06-29
**Depends On:** SPEC-038 (query-results Prev/Next pagination + `useQueryResults`), SPEC-035 (query workspace + `QueryResultsTable`)

> **Design:** Needs a light design pass. The results table keeps its current visual language (surface, border,
> `rounded-lg`, `surface-2` uppercase header, monospace rows). New: a thin column-resize handle on each header
> cell's right edge (hover/active accent), `text-overflow: ellipsis` truncation in cells, and a horizontally
> scrollable body wide enough for many columns. See `design-system.md` §6.

## Overview

The query-results table renders whatever columns a user's `SELECT` returns, but every column is currently sized
automatically and can't be adjusted. Users with wide result sets — some have tables with **20+ columns** — can't
widen a column to read a long value or narrow noisy ones to fit more on screen. This spec makes result columns
**user-resizable** by dragging the boundary between header cells. A user's chosen widths **persist for the
current result** — across Prev/Next paging **and** query-tab switches within the session (keyed by execution id,
so returning to a still-cached result keeps its widths) — and **reset to defaults when a new query runs**.
Columns have a **minimum width**, **never wrap**, and **truncate overflowing text with an ellipsis** (including the
header label when a column is narrower than its name); the results body **scrolls horizontally** so wide result
sets remain fully reachable.

## Scope

### In Scope

- **Drag-to-resize columns** — each data column's header has a resize handle on its right edge; dragging changes
  that column's width. The leading row-number (`#`) column (SPEC-038) is fixed-width and not resizable.
- **Width persistence for the same result** — widths the user sets persist across **Prev/Next** navigation
  within the same query execution **and** across query-tab switches within the session: the widths are keyed by
  **execution id** (held above the results table, in the workspace), so switching to another tab and back to a
  still-cached result keeps its widths. They do **not** reset when changing pages or switching tabs.
- **Reset on new query** — running a **new query** (new execution id) resets all columns to their default width.
- **Minimum column width** — a hard floor (`MIN_COLUMN_WIDTH`) below which a column cannot be dragged.
- **No wrap + ellipsis truncation** — cell and header text never wrap; content that exceeds the column width is
  clipped with a trailing ellipsis. When a column is narrower than its column name, the **header label** itself
  truncates with an ellipsis. The full untruncated value is available on hover (native `title`) for legibility.
- **Horizontal scroll** — the results body scrolls horizontally so all columns of a wide (20+ column) result are
  reachable; the surrounding workspace shell does not break or overflow.
- **Per-column reset + keyboard resize** — double-clicking a handle resets that column to its default width;
  handles are keyboard-operable (Arrow Left/Right adjust width by a step), accessibly labelled.

### Out of Scope

- **Persisting widths across reloads or different queries** — persistence is scoped to the *current result*
  (the current execution id) and lives in memory for the workspace's lifetime; a new query, a reload, or leaving
  the `/query` route starts from defaults. (Cross-tab-switch persistence within the session **is** in scope — see
  FR-002.)
- **Column reordering, hiding/showing columns, sorting, or auto-fit-to-content** — only manual width resize.
- **Resizing the `#` row-number column** — it stays fixed width.
- **Row height / wrapping toggles** — rows stay single-line with ellipsis (no wrap mode).
- Changes to the data layer (`useQueryResults`, pagination, `query.service`) — this is presentation-only.

---

## Functional Requirements

### FR-001: Drag-to-resize a column

#### Description:

Dragging the boundary on a data-column header changes that column's width.

#### Acceptance Criteria:

- [ ] Each **data** column header renders a resize handle on its right edge; pressing and dragging it left/right
  changes that column's rendered width live, for the header and every cell in the column.
- [ ] The leading `#` row-number column has **no** handle and keeps its fixed width.
- [ ] A column cannot be dragged narrower than `MIN_COLUMN_WIDTH` (the drag clamps at the floor).
- [ ] Resizing one column does not change other columns' widths; the table's total width grows/shrinks accordingly
  (driving horizontal scroll, FR-005).

### FR-002: Widths persist for the same result (paging + tab switches)

#### Description:

Width choices survive Prev/Next navigation within the same query execution **and** query-tab switches within the
session — widths are keyed by execution id and held above the results table.

#### Acceptance Criteria:

- [ ] After the user resizes one or more columns, navigating **Next** then **Prev** (or any page change) within the
  **same** query execution keeps the user-set widths — paging does not reset them.
- [ ] Switching to another query tab and back to a still-cached result keeps that result's widths (the width store
  lives in `QueryWorkspace`, above the results table that unmounts when a tab has no results).
- [ ] Width state is keyed by query **execution id** (a `Record<executionId, number[]>`); it lives in memory for
  the workspace's lifetime (no persistence across reload / leaving the route).

### FR-003: Reset on a new query

#### Acceptance Criteria:

- [ ] Running a **new query** (a new execution id) resets every column to its default width (`DEFAULT_COLUMN_WIDTH`),
  discarding the previous result's widths.
- [ ] A result whose column **count** differs from the prior result starts from defaults (no stale per-index widths
  bleed across differently-shaped results).

### FR-004: No wrap, ellipsis truncation

#### Acceptance Criteria:

- [ ] Cell text never wraps; content wider than the column is clipped with a trailing ellipsis (`…`).
- [ ] The **header** (column name) also truncates with an ellipsis when the column is narrower than the name; the
  column type sub-label truncates the same way.
- [ ] Hovering a truncated cell or header exposes the full text via a native `title` tooltip (so no information is
  lost when a column is narrowed).

### FR-005: Horizontal scrolling for wide results

#### Acceptance Criteria:

- [ ] When the combined column widths exceed the available width, the results body scrolls **horizontally** while
  the rest of the workspace layout (rail, editor, tab strip) stays put and does not overflow the viewport.
- [ ] A 20+ column result is fully reachable by horizontal scroll; the header row scrolls in lockstep with the body
  (header and cells stay aligned).
- [ ] The leading `#` column and the pager remain usable with a wide, scrolled result (the pager is below the
  scroll region, not inside it).

### FR-006: Per-column reset + keyboard resize + a11y

#### Acceptance Criteria:

- [ ] Double-clicking a column's resize handle resets **that** column to `DEFAULT_COLUMN_WIDTH`.
- [ ] Each handle is keyboard-operable: focusable, `role="separator"` with `aria-orientation="vertical"`, an
  `aria-label` naming the column it resizes; Arrow Left/Right adjust the width by `COLUMN_RESIZE_STEP_PX` (clamped at
  `MIN_COLUMN_WIDTH`).
- [ ] No axe violations introduced (covered by the SPEC-045 suite); the table's existing semantics (`scope="col"`
  headers, row association) are preserved.

### FR-007: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: `useColumnWidths` defaults to `DEFAULT_COLUMN_WIDTH`,
  clamps `setWidth` at `MIN_COLUMN_WIDTH`, resets on execution-id change and on column-count change, and resets a
  single column via `resetColumn`; widths persist across a re-render of the same execution (paging) and are
  restored when navigating back to a prior execution id (tab switch); the table renders a handle per data column
  but not for `#`, drives the `<colgroup>` from the `widths` prop, and wires each handle's drag / double-click /
  Arrow key to `onResize` / `onResetColumn`; truncated cells/headers expose `title`.

---

## Data Model

```ts
// apps/portal/src/features/query/useColumnWidths.ts  (NEW)

// In-memory per-column widths keyed by query execution id (Record<execId,number[]>)
// so widths survive paging AND tab switches. A new execution id starts from
// defaults (FR-003); an entry whose column count no longer matches re-defaults
// (defensive) — both via a render-phase seed, mirroring useQueryResults's reset
// (no effect, no extra render). Called in QueryWorkspace (above the results table,
// which unmounts when a tab has no results) and its outputs passed down.
export function useColumnWidths(
  executionId: string | null,   // the current query execution id (the store key)
  columnCount: number,
): {
  widths: number[];                          // px per data column of the CURRENT execution; default DEFAULT_COLUMN_WIDTH
  setWidth: (index: number, px: number) => void;   // clamped to >= MIN_COLUMN_WIDTH
  resetColumn: (index: number) => void;            // back to DEFAULT_COLUMN_WIDTH
};
```

```ts
// apps/portal/src/features/query/query.constants.ts  (additions)

// SPEC-064: result-column sizing. Defaults a column to a comfortable width;
// MIN is the hard drag floor (small enough that a narrow column ellipsis-
// truncates its own header). STEP is the keyboard (Arrow) resize increment.
export const DEFAULT_COLUMN_WIDTH = 180;   // px
export const MIN_COLUMN_WIDTH = 72;        // px
export const COLUMN_RESIZE_STEP_PX = 16;   // px per Arrow key press
```

> Widths are keyed by **column index**, not name — a `SELECT` can return duplicate/blank column names, so index is
> the stable identity within a single result.

## API / Interface Contract

```ts
// QueryResultsTable is CONTROLLED: the parent (QueryWorkspace, via useColumnWidths)
// owns the widths so they outlive the table's mount. The table drives a <colgroup>
// of explicit widths (table-layout: fixed) + per-header resize handles. Other props
// unchanged.
type QueryResultsTableProps = {
  // ...existing (columns, rows, pageIndex, range, totals, pager handlers)...
  widths: number[];                                // NEW: px per data column
  onResize: (index: number, px: number) => void;   // NEW: setWidth
  onResetColumn: (index: number) => void;          // NEW: resetColumn (dbl-click)
};

// ColumnResizeHandle: a focusable separator handling pointer-drag + keyboard.
function ColumnResizeHandle(props: {
  columnIndex: number;
  columnName: string;
  width: number;
  onResize: (index: number, px: number) => void;   // setWidth
  onReset: (index: number) => void;                 // resetColumn (dbl-click)
}): JSX.Element;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── QueryWorkspace.tsx          ← calls useColumnWidths (above the table) + passes widths/handlers down
├── QueryResultsTable.tsx       ← controlled: colgroup widths (table-layout fixed) + ellipsis cells + handles
├── QueryResultsTable.test.tsx
├── ColumnResizeHandle.tsx      ← NEW: drag + keyboard resize separator
├── ColumnResizeHandle.test.tsx ← NEW
├── useColumnWidths.ts          ← NEW: per-execution-id widths store (survives paging + tab switches)
├── useColumnWidths.test.ts     ← NEW
└── query.constants.ts          ← + DEFAULT/MIN column width + resize step
```

## Implementation Phases

### Phase 1: Width state + fixed-layout rendering with ellipsis

- Add `useColumnWidths` (a `Record<executionId, number[]>` store) + constants; call it in `QueryWorkspace` and
  pass `widths` down; switch `QueryResultsTable` to a controlled `<colgroup>` of explicit widths
  (`table-layout: fixed`) with `#` fixed and data columns from the `widths` prop; apply no-wrap + ellipsis
  truncation and `title` on header + cells (FR-002, FR-003, FR-004, FR-005).

### Phase 2: Drag + keyboard resize handle

- Add `ColumnResizeHandle` (pointer drag clamped at `MIN_COLUMN_WIDTH`, double-click reset, Arrow-key resize,
  `role="separator"` + aria-label); wire it into each data-column header (FR-001, FR-006).
