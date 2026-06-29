# Completed Spec — SPEC-064: Resizable Query-Result Columns

## What was completed?

Query-result columns are now **user-resizable**. The results table renders a `<colgroup>` of explicit
per-column widths under `table-layout: fixed`; each **data** column header carries a drag/keyboard
**resize handle**, cells and headers never wrap and truncate with an ellipsis (full text on hover via
native `title`), and the body scrolls horizontally for wide (20+ column) results. Widths persist across
Prev/Next within one query execution and reset to the default on a new query.

- **`useColumnWidths(resetKey, columnCount)`** (NEW) — in-memory `number[]` of px widths + clamped
  `setWidth` (≥ `MIN_COLUMN_WIDTH`) + `resetColumn`. Resets to defaults via a **render-phase reset**
  tracking the previous `resetKey` (the query execution id) **and** `columnCount`, mirroring
  `useQueryResults`'s pageIndex reset (no effect, no extra render). Keyed by column **index** (a SELECT
  can return duplicate/blank names).
- **`ColumnResizeHandle.tsx`** (NEW) — a focusable `role="separator"` `aria-orientation="vertical"`
  with a column-naming `aria-label`. Pointer drag (window-level move/up listeners scoped to the gesture
  closure), double-click reset, Arrow Left/Right nudge by `COLUMN_RESIZE_STEP_PX`. The leading `#`
  row-number column has no handle and keeps its fixed width.
- **`query.constants.ts`** — added `DEFAULT_COLUMN_WIDTH = 180`, `MIN_COLUMN_WIDTH = 72`,
  `COLUMN_RESIZE_STEP_PX = 16` (exported via the feature barrel alongside `useColumnWidths`).
- Tests: `useColumnWidths.test.ts`, `ColumnResizeHandle.test.tsx`, and new SPEC-064 cases in
  `QueryResultsTable.test.tsx` (handle-per-data-column, drag/clamp/reset, persist-across-page,
  reset-on-new-query, truncation/`title`).

No deliberate deviations. Persistence is in-memory only, scoped to the current execution (per scope —
no cross-reload/tab/query persistence).

## What changed from earlier specs?

- **`QueryResultsTable.tsx`** (SPEC-035/038) gained one prop — `queryExecutionId: string | null` (the
  width reset key) — and switched from auto-layout to `table-fixed` + `<colgroup>`. All existing props
  and the empty/loading states + Prev/Next pager are unchanged.
- **`QueryWorkspace.tsx`** call site passes `queryExecutionId={succeeded ? activeExecutionId : null}`
  (the same identity that already keys `useQueryResults`). No data-layer / IAM / infra change —
  presentation only.

## Verification

`npm run lint`, `npm run test` (772 passed, incl. the new width-hook / handle / table cases), and
`tsc -b` (typecheck) all green locally. Browser preview was **not** run: the results table lives on the
Cognito-gated `/query` route backed by live Athena, which the local dev-unauth preview (`/files`
read-only) can't exercise — covered instead by the unit suite.
