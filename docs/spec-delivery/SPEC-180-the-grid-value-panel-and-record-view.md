# Completed Spec — SPEC-180: the Grid, Cell Selection, the Value Panel and the Record View

## What was completed?

SPEC-179's placeholder table is gone, replaced by the grid the feature exists for.

- **`ExplorationResultsRegion`** — the container: the page, the geometry, the selection, the
  toolbar and the pager. `ExplorationResultsTable` is deleted.
- **`ExplorationGrid` + `ExplorationGridHeader`** — `role="grid"`, a sticky pinned block, row
  numbers, drag-reorder grips and a resize handle per column.
- **`useColumnGeometry`** — resize, reorder, pin, hide/show, all keyed by column NAME, resolved
  against whatever columns the current result set has.
- **`useCellSelection`** — the cursor, rectangles, discontiguous cells, whole columns and rows,
  Ctrl/Cmd+A over the loaded page, a single tab stop with roving `tabIndex`.
- **`ColumnsPanel`** — hide/show, pin and the keyboard reorder alternative, announced in a live
  region; every refusal through `Button.disabledReason`.
- **`ValuePanel`, `ExplorationRecordView`, `ExplorationTextView`, `PresentationSwitch`,
  `CellValue`/`cellText`** — the Value panel and the two alternative presentations.
- **`useSourceColumns`** — a `table` source's headers from Glue before any execution returns.

`ExplorationPresentation` gained `presentation`, `valuePanelOpen` and `recordRowIndex`; the tab
restore normalises them rather than discarding a tab over a cosmetic field.

No IaC, no IAM, no new AWS call, no new `GATED_SURFACES` row — everything here is inside `/explore`,
which the `dataExplorer` flag already gates.

## Three shared-layer changes, and why each was not optional

**`ColumnResizeHandle` moved `features/query/` → `features/catalog/`**, generic over its column key.
Two sibling features now draw result grids and neither may import the other; mirroring it would have
been the twin SPEC-095 calls a smell. The Query workspace keys widths by INDEX (a `SELECT` may return
duplicate names) and the Data Explorer by NAME (its geometry outlives the execution), so the key is a
type parameter rather than a number. It also gained the `aria-valuenow`/`aria-valuemin` that a
**focusable** separator requires — caught by axe the first time a grid full of handles was driven
into a live state, and a violation the Query workspace has been carrying unnoticed.

**`getQueryResults` stopped collapsing SQL NULL to `''`.** An absent `VarCharValue` is NULL and an
empty one is an empty string; `?? ''` erased the difference at the service boundary, and no consumer
can reconstruct it. FR-003 AC5 requires the two to be visibly different, so the row type is now
`(string | null)[][]`. The Query workspace renders both as blank exactly as before — the change is
information kept, not behaviour altered — and it is what SPEC-181's `isNull` filters and SPEC-185's
copy will need.

**`useQueryResults` clamps a remembered page index the cache no longer holds.** Pages of an execution
nobody is observing are collected once `gcTime` elapses (switch tabs, come back), and the refetch
starts from page 1 — so the remembered index selected a page that was no longer there. An absent page
is indistinguishable from an empty one, so **a result WITH rows rendered as "No rows returned"**. The
per-execution page memory is unchanged while the pages are still cached; the clamp only bites when
they are gone. The test beside it that was named for the memory could not have caught this: under
`gcTime: 0` it was asserting the transient index, so it now keeps a second observer warm and a new
case covers the collected path.

## Deviations from the spec, and the reasons

- **`Selection` is `CellSelection`.** `Selection` is a DOM global (`window.getSelection()`), and a
  same-named export shadows it silently in any file that reads both — which SPEC-185's copy will.
- **`presentation` is `GridPresentation | null`, not `GridPresentation`.** Null means *unchosen*,
  which is what makes FR-007's mobile default expressible: below `tablet` an unchosen tab opens in
  Record, a chosen one keeps its choice at every width. A non-null default would have to be picked
  by `useExplorationTabs`, which has no business reading the viewport.
- **Widths are NOT `useColumnWidths`.** FR-001 asks to reuse it, but it keys by execution id and
  column INDEX, in memory. The spec's own `columnWidths: Record<string, number>`, FR-001 AC7 (per-tab
  persistence) and FR-006 AC3 (discard geometry for a vanished column) all require name keying. Its
  constants and its resize gesture are reused; the hook is not.
- **Two files the structure did not list.** `ColumnsPanel.tsx` — SPEC-181 owns the per-column header
  menu, so hide/pin/reorder needed a home that does not collide with it. `ExplorationResultsRegion.tsx`
  — the container the three presentations hang off, so each view stays presentational.
- **A cross-block drag is refused rather than coerced.** Dropping an unpinned column onto the pinned
  block does nothing, because inferring "pin this too" from where a drag ended is a mutation the user
  did not ask for. Pinning has its own control.

## What is NOT here

Filtering and ordering (SPEC-181), Calc and grouping (SPEC-182), copy and export (SPEC-185),
colouring and transformers (SPEC-184), and the column header MENU. The header resizes, drags and
pins; its menu trigger is SPEC-181's. Editing is out by decision — an Athena result is not an
editable table.

## Live checks owed

**None.** No infra, no IAM, and no AWS call the app did not already make. The one behaviour worth
watching for in the next live pass is cosmetic and browser-specific: the sticky pinned block and the
Value panel's sheet form below `tablet` are CSS the test runner cannot see, so fold a look at them
into the arc's Safari pass in SPEC-185.

## Help & guides

Nothing added. SPEC-185 writes the Data Explorer guides and takes the `dataExplorer` guide row, once
the feature is shipped end to end (SPEC-074 FR-005 documents only what is wired).
