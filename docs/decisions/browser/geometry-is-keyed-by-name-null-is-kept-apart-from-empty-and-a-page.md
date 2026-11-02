---
type: Decision
title: "Geometry is keyed by NAME, NULL is kept apart from empty, and a page nobody watched is not \"no rows\" (SPEC-180)"
description: "**Column geometry is keyed by NAME**, so geometry for a column the result no longer has is discarded by construction. **SQL NULL stays apart from the empty string** from `getQueryResults` on, because nothing downstream can undo collapsing them. **A remembered page index must not outlive its cached pages**: an absent page reads as an empty one, so the grid drew \"No rows returned\" over a full result."
---

The grid replaces SPEC-179's placeholder wholesale, and three of its decisions reach outside the
feature.

**Column geometry is keyed by the column NAME, which is why it is not `useColumnWidths`.** FR-001
asks to reuse SPEC-176's width store; that store keys by execution id and column **index**, in
memory, and re-defaults on a column-count change. Every other requirement points the other way — the
spec's own `columnWidths: Record<string, number>`, FR-001 AC7's per-tab persistence through
`sessionStorage`, and FR-006 AC3's "geometry for a column that no longer exists is discarded". Name
keying makes that last one true **by construction**: a width, a pin or a hide belonging to a column
this result set does not contain simply never resolves, where an index would have landed it on
whichever column moved into that position after a re-order or a `GROUP BY`. Stale entries are left
in place rather than pruned, so a re-execution that brings a column back brings its geometry back
too. The catalog's sizing constants and its resize gesture are reused; the hook is not.
`ColumnResizeHandle` itself **moved to `features/catalog/`**, generic over its column key (index for
the Query workspace, name here) — two sibling features now draw result grids and neither may import
the other, so the alternative was the `*Mobile`-style twin SPEC-095 calls a smell.

**A focusable `role="separator"` needs a value, and the Query workspace had been shipping without
one.** axe raised `aria-required-attr` the first time a grid full of handles was driven into a live
state — the violation was always there, but no axe assertion had ever run over a header row carrying
handles. `aria-valuenow`/`aria-valuemin`/`aria-valuetext` now ship with the shared handle, so both
surfaces gain the fix.

**`getQueryResults` stopped collapsing SQL NULL to `''`, because nothing downstream can undo that.**
Athena's Datum omits `VarCharValue` for NULL and carries an empty one for an empty string; the
service mapped both to `''`, so FR-003 AC5 ("an empty string and a `NULL` are visibly different")
was **unbuildable** at the layer that had to satisfy it. Rows are now `(string | null)[][]`. The
Query workspace renders both as blank exactly as before — this is information kept, not behaviour
changed — and SPEC-181's `isNull` filters and SPEC-185's copy both need the distinction. Its cost is
that every consumer of a cell now handles `null`, which the compiler enumerated: six sites.

**A remembered page index outliving its cached pages rendered a result WITH rows as "No rows
returned".** `useQueryResults` keeps a per-execution page position (SPEC-078's result tabs); the
pages behind it are collected once nobody observes that execution for `gcTime`, and the refetch
starts again from page 1. The remembered index then selected a page that was not there, and **an
absent page is indistinguishable from an empty one** — so the pager read `rows: []` with
`isPending: false` and the grid drew the friendly empty state over a full result. The index is now
clamped to the pages actually loaded, only while any are. The neighbouring test named for the page
memory could not have caught it: the test client runs `gcTime: 0`, so it was asserting the transient
index during a refetch rather than a restored position, and it now holds a second observer warm so
the case it is named for is the case it runs.

**Superseded 2026-09-28: the explorer is table-only at every width, so there is no choice to leave
unchosen** ([`docs/decisions/analytics/`](../analytics/the-explorer-shows-a-table-and-nothing-else-and-a-saved-view-still.md)). **`presentation: null` means UNCHOSEN, and that is the whole of FR-007's mobile default.** Below
`tablet` an unchosen tab opens in Record; a tab whose user has chosen keeps that choice at every
width. A non-null default would have had to be picked when the tab is created, by
`useExplorationTabs`, which has no business reading the viewport — and `useIsMobile` would then have
been deciding a persisted value rather than mount-gating one (SPEC-095 FR-008). Record and the grid
share **one** focused row, so switching between them lands where the other left off rather than
where the cursor happened to be.

**The selection model is explicit because two later specs are built on it.** `ranges` is a list of
inclusive rectangles and **the last one is live** — its `from` is the anchor a Shift gesture extends
from, its `to` is the cursor — and a Ctrl/Cmd+click appends a single-cell rectangle that becomes the
live one. Toggling off removes only a rectangle that is exactly that cell, because punching a hole
in a rectangle is not something the model can represent. The count is taken over a **set of
coordinates**, not summed per rectangle, since overlapping ranges are one click away and a sum would
report more cells than the page has. Everything is addressed by (row on the page, column name), so
coordinates are meaningless across a page change — the reset happens **during render**, not in an
effect, because an effect paints one frame of the old selection over the new page's rows, which is
precisely the state AC8 forbids. Cells carry an explicit `role="gridcell"`: a bare `td` inside
`role="grid"` maps correctly only through one HTML-AAM lookup, and several accessibility APIs (and
the test renderer) resolve it statically as `cell`, a role with no selected state.

**Hide, pin and reorder live in a PANEL, not in the header.** SPEC-181 owns the per-column header
menu, so putting them there would have meant building that menu a spec early and rebuilding it a
spec later; the panel is also where the **keyboard alternative to dragging** belongs (Move earlier /
Move later, announced in a live region), since a drag has no keyboard equivalent to inherit. A
cross-block drag — an unpinned column dropped onto the pinned block — is **refused rather than
coerced into a pin**, because inferring a pin from where a drag ended is a mutation the user did not
ask for and pinning has its own control.

## History

### 2026-09-28

- **Changed:** The explorer became table-only at every width, so `presentation: null` as an unchosen Record-or-grid default no longer applies.

### 2026-08-13

- **Settled:** SPEC-180.
