# Completed Spec — SPEC-064: Resizable Query-Result Columns

## What was completed?

Query-result columns are now **user-resizable**. The results table renders a `<colgroup>` of explicit
per-column widths under `table-layout: fixed`; each **data** column header carries a drag/keyboard
**resize handle**, cells and headers never wrap and truncate with an ellipsis (full text on hover via
native `title`), and the body scrolls horizontally for wide (20+ column) results. Widths persist for the
current result — across Prev/Next paging **and** query-tab switches — and reset to the default on a new query.

- **`useColumnWidths(executionId, columnCount)`** (NEW) — an in-memory **`Record<executionId, number[]>`**
  width store + clamped `setWidth` (≥ `MIN_COLUMN_WIDTH`) + `resetColumn` for the current execution. Keyed
  by execution id so widths survive paging **and tab switches** (returning to a cached result keeps them);
  a new execution id seeds defaults, and an entry whose column count no longer matches re-defaults — both via
  a **render-phase seed** (no effect, no extra render). Widths within an entry are keyed by column **index**
  (a SELECT can return duplicate/blank names). **Called in `QueryWorkspace`, above the results table** (which
  unmounts when the active tab has no results), with its outputs passed down.
- **`ColumnResizeHandle.tsx`** (NEW) — a focusable `role="separator"` `aria-orientation="vertical"`
  with a column-naming `aria-label`. Pointer drag (window-level move/up listeners scoped to the gesture
  closure), double-click reset, Arrow Left/Right nudge by `COLUMN_RESIZE_STEP_PX`. The leading `#`
  row-number column has no handle and keeps its fixed width.
- **`query.constants.ts`** — added `DEFAULT_COLUMN_WIDTH = 180`, `MIN_COLUMN_WIDTH = 72`,
  `COLUMN_RESIZE_STEP_PX = 16` (exported via the feature barrel alongside `useColumnWidths`).
- **`ColumnResizeHandle.tsx`** (NEW) — a focusable `role="separator"` `aria-orientation="vertical"`
  with a column-naming `aria-label`. Pointer drag (window-level move/up scoped to the gesture closure),
  double-click reset, Arrow Left/Right nudge by `COLUMN_RESIZE_STEP_PX`. The leading `#` column has no
  handle and keeps its fixed width.
- **`query.constants.ts`** — added `DEFAULT_COLUMN_WIDTH = 180`, `MIN_COLUMN_WIDTH = 72`,
  `COLUMN_RESIZE_STEP_PX = 16`.
- Tests: `useColumnWidths.test.ts` (defaults/clamp/reset, persist-across-page, **restore-on-return-to-prior-
  execution = tab switch**, reset-on-new-query, column-count re-default, null id), `ColumnResizeHandle.test.tsx`,
  and SPEC-064 cases in `QueryResultsTable.test.tsx` (handle-per-data-column, colgroup-from-`widths`-prop,
  drag/dbl-click/keyboard call the handlers, truncation/`title`).

**Scope amendment (post-initial-merge, [#138]→this PR):** persistence was extended from paging-only to also
**survive query-tab switches** within the session (user request). This required lifting the width store from
`QueryResultsTable` (which unmounts when a tab has no results) into `QueryWorkspace` and keying it by execution
id (`Record<executionId, number[]>`). No deliberate deviations otherwise; reload / leaving the route still
starts from defaults (out of scope).

## What changed from earlier specs?

- **`QueryResultsTable.tsx`** (SPEC-035/038) is now **controlled** for widths: it dropped the internal
  `useColumnWidths` call and the `queryExecutionId` prop, gaining `widths: number[]`, `onResize`, and
  `onResetColumn`. It switched from auto-layout to `table-fixed` + `<colgroup>`. All other props and the
  empty/loading states + Prev/Next pager are unchanged.
- **`QueryWorkspace.tsx`** now calls `useColumnWidths(succeeded ? activeExecutionId : null, results.columns.length)`
  and passes `widths` / `setWidth` / `resetColumn` to the table. No data-layer / IAM / infra change —
  presentation only.

## Verification

`npm run lint`, `npm run test` (773 passed, incl. the new width-hook / handle / table cases — notably the
tab-switch restore case), and `tsc -b` (typecheck) all green locally. Browser preview was **not** run: the
results table lives on the Cognito-gated `/query` route backed by live Athena, which the local dev-unauth
preview (`/files` read-only) can't exercise — covered instead by the unit suite.
