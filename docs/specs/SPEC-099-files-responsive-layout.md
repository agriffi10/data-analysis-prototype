# Spec: Files — Responsive Layout

**ID:** SPEC-099
**Status:** Draft
**Last Updated:** 2026-07-08
**Depends On:** SPEC-095, SPEC-096, SPEC-097, SPEC-098

## Overview

The file browser is desktop-only: a fixed 5-column table, a 248px Spaces rail that simply vanishes
below `tablet`, and toolbar/actions laid out for a wide viewport. The Claude Design responsive mockups
(`docs/design/Responsive Breakpoints.dc.html`, frames `FILES · DESKTOP` / `FILES · TABLET` /
`FILES · MOBILE — FINAL`) reflow the Files surface across three widths so it is usable on a phone.
This spec reflows **only the Files presentation**. Per SPEC-095 FR-008, most of the reflow is
responsive utilities on the existing elements (rail placement, breadcrumb compaction, the bulk toolbar
going icon-only, the Type column shedding at tablet). The **one sanctioned structural exception** is the
listing itself: a **data table** (grid of columns) on desktop/tablet versus a **compact two-line card
list** on mobile are different enough in DOM/semantics to warrant separate markup — a `hidden tablet:grid`
table swapped with a `tablet:hidden` mobile list (a dedicated mobile row component), both driven by the
**same** `files`/`folders` data and the **same** activate/open/details/select handlers (no forked
logic). The Spaces rail moves off-canvas below `tablet`, a persistent mobile bottom action bar carries the
two primary actions, and the details panel becomes a bottom sheet. It consumes the shared responsive
chrome from SPEC-095 (`AppNavDrawer`, `MobileActionBar`, responsive `Drawer`) and the Files feature
changes from SPEC-096/097/098; it changes no data, services, IAM, infra, routing, or auth.

## Scope

### In Scope

- Reflow the Files shell to the SPEC-095 breakpoint convention: on-page 248px Spaces rail at `≥ tablet`,
  off-canvas below `tablet` (rail content passed into `AppNavDrawer`'s contextual slot); single-column
  content on mobile.
- Keep the full **5-column** table on desktop (`desktop`), drop the **Type** column at tablet (`tablet`,
  4 columns), and replace the table markup with a **compact two-line card list** (56px rows) on mobile
  (`< tablet`) via a `hidden tablet:grid` / `tablet:hidden` markup swap.
- A new mobile list-row component (two-line: icon + name/meta + trailing size or chevron) with a
  selected-row treatment (`accent-soft` fill, inset `accent` left bar, checked indicator).
- Reflow/compact the breadcrumb bar on mobile; breadcrumbs persist at every width.
- Mount the SPEC-095 `MobileActionBar` carrying **New folder + Upload** (≥44px targets); pad the
  content scroll region so the bar never occludes the last row.
- Make the SPEC-096 selection (bulk) toolbar responsive: labelled buttons on desktop/tablet, icon-only
  36px buttons on mobile (Delete in danger tone).
- Compose the SPEC-098 `..` parent row (its grid variant at `≥ tablet`, its 56px two-line variant on
  mobile) and the SPEC-097 button-opened details panel (bottom sheet below `tablet` via SPEC-095 FR-007)
  into the responsive listing — referencing, not re-specifying, those specs.

### Out of Scope

- **No data-layer, service, IAM, infra, routing, or auth changes.** No change to any S3 operation or to
  the behavior of `useFileBrowser`, `useFileUpload`, `useCopy`, `useMove`, or `useDelete`; this spec
  edits presentation/markup only.
- The shared responsive primitives themselves — `AppNavDrawer`, `MobileActionBar`, the responsive
  `Modal`/`Drawer`, and the breakpoint convention are owned by SPEC-095; this spec only consumes them.
- The selection-toolbar action set (Copy/Move/Delete) and the details-panel actions (Download/Rename)
  — owned by SPEC-096 and SPEC-097; this spec only makes their layout responsive / composes them.
- The `..` parent-row logic (root detection, navigate-up, selection exclusion) — owned by SPEC-098;
  this spec only places its two per-breakpoint variants in the swapped markup.
- **No header `⋯` overflow menu.** The mockup's mobile header overflow is intentionally omitted (see
  FR-005): its only in-scope actions (New folder, Upload) are already on the bottom bar, and net-new
  Sort / Select-mode are not built. There is no mobile "selection mode"; selection stays via
  always-visible per-row checkboxes at every breakpoint.
- New design tokens, in-browser preview, or any Query/Connections/Notifications/Help reflow.

---

## Functional Requirements

### FR-001: Responsive shell — rail placement and single-column content

#### Description:

The Files page uses a two-region shell: the 248px Spaces rail (existing `Sidebar` → `CollapsibleRail`,
already `hidden tablet:flex`) sits on-page beside the browser at `≥ tablet`; below `tablet` the rail is not on-page
and its Spaces list is supplied to the `AppNavDrawer` contextual slot (SPEC-095 FR-003) so it is
reachable via the hamburger. The file-browser content is a single column at every width and never
scrolls horizontally.

#### Acceptance Criteria:

- [ ] At `≥ desktop` the layout is a `desktop:grid-cols-[248px_1fr]` (or equivalent) two-column shell with the
      Spaces rail on-page; at `tablet` the rail is on-page (unchanged `tablet:flex`) and content fills the rest.
- [ ] At `< tablet` the on-page rail is not rendered (`hidden` below `tablet`) and the Files page passes its
      Spaces list into `AppNavDrawer`'s `contextualRail` slot so it is reachable from the hamburger.
- [ ] The browser content is a single column at all widths and produces no horizontal scrollbar at the
      mobile (~390px), tablet (~1100px), or desktop (~1400px) reference widths.
- [ ] No change to which bucket/prefix is browsed or to any `useFileBrowser` call — layout only.

### FR-002: Desktop/tablet table columns — 5 on desktop, drop Type at tablet

#### Description:

The `≥ tablet` presentation stays a tabular listing rendered with a `hidden tablet:grid` container (header row
+ rows). Desktop (`desktop`) shows all five columns — selection checkbox, Name, Size, Last modified, Type.
At tablet (`tablet`, below `desktop`) the **Type** column is removed, leaving four columns; the remaining
columns keep alignment between the header row and body rows.

#### Acceptance Criteria:

- [ ] At `≥ desktop` the header row and every body row show checkbox, Name, Size, Last modified, and Type.
- [ ] At `tablet` (below `desktop`) the Type column (header cell and every row's Type/Badge cell) is hidden
      (e.g. `hidden desktop:flex` / `hidden desktop:block`), leaving checkbox, Name, Size, Last modified.
- [ ] The header row and body rows stay column-aligned at both `tablet` and `desktop` (no drift when Type drops).
- [ ] The whole tabular block is `hidden` below `tablet` (`hidden tablet:grid` or `hidden tablet:block`), so it does
      not render on mobile.
- [ ] The selection checkbox column and the Details button remain present at both `tablet` and `desktop`.

### FR-003: Mobile compact two-line list

#### Description:

Below `tablet` the tabular markup is replaced by a compact two-line card list (`tablet:hidden`). Each real item
renders a 56px row with no table chrome: a leading file/folder icon (folder icon `accent`-filled), a
two-line primary block (line 1 = name, truncated; line 2 = meta — folders show "Folder", files show
`{TYPE} · {date}` in `text-3`), and a trailing element (files show their formatted size; folders show a
right chevron). A per-row selection checkbox is present for every real item; the selected state renders
`accent-soft` background, an inset `accent` left bar, and a checked indicator.

#### Acceptance Criteria:

- [ ] At `< tablet` the two-line list renders (`tablet:hidden`) and the `hidden tablet:grid` tabular block does not;
      at `≥ tablet` the reverse holds. Both markups are driven by the same `files`/`folders` data.
- [ ] Each row is 56px tall with icon + two-line name/meta; the folder icon is `accent`-filled and the
      file icon is neutral (`text-3`).
- [ ] File rows show a trailing formatted size; folder rows show a trailing chevron (no size).
- [ ] A double-click / tap-activate on a file row downloads it and on a folder row opens it (reusing
      the existing `onActivate` / navigate handlers — no new S3 behavior).
- [ ] Every real item's mobile row carries a selection checkbox (present at all widths per FR-006); a
      selected row shows `accent-soft` background, an inset `accent` (~3px) left bar, and a checked
      indicator.
- [ ] Long names truncate with ellipsis; no row produces horizontal overflow at ~390px.

### FR-004: Responsive breadcrumb bar

#### Description:

The breadcrumb bar persists at every breakpoint. On mobile it compacts (the trailing/current folder
crumb reads as a chip and long crumbs truncate) so it fits the narrow bar without wrapping into the
primary actions; on desktop/tablet it is unchanged.

#### Acceptance Criteria:

- [ ] Breadcrumbs render at mobile, tablet, and desktop widths (never hidden).
- [ ] On mobile the breadcrumb row does not wrap or push content off-screen; crumbs truncate and the
      current crumb reads as a compact chip.
- [ ] At `≥ tablet` the breadcrumb presentation is visually unchanged from today.
- [ ] Activating a crumb navigates to that prefix at every width (existing `setPrefix` behavior).

### FR-005: Persistent mobile bottom action bar (New folder + Upload); no overflow menu

#### Description:

On mobile (writable flows only) the two primary actions move off the top toolbar into a persistent
`MobileActionBar` (SPEC-095 FR-004) fixed to the viewport bottom: **New folder** and **Upload**, both
≥44px. The top-toolbar New folder / Upload / Create table buttons stay as-is at `≥ tablet`. Per the product
decision the mockup's header `⋯` overflow menu is **omitted** — New folder and Upload are already the
bottom-bar actions, and net-new Sort / Select-mode are excluded; there is no mobile selection mode.

#### Acceptance Criteria:

- [ ] At `< tablet`, in a writable flow, `MobileActionBar` renders with a New folder control and an Upload
      control, each a ≥44px target; New folder opens `CreateFolderDialog` and Upload opens the upload
      drawer (same handlers as the desktop buttons).
- [ ] At `≥ tablet` the `MobileActionBar` is not rendered and the top-toolbar New folder / Upload / Create
      table buttons render as today.
- [ ] In the read-only (dev-unauth) flow the `MobileActionBar` is not rendered (no write actions).
- [ ] No header `⋯` overflow menu is rendered at any breakpoint; there is no "selection mode" toggle.
- [ ] The content scroll region gets bottom padding ≥ the bar height on mobile so the last list row is
      never occluded by the bar.

### FR-006: Responsive selection (bulk) toolbar and always-visible checkboxes

#### Description:

The SPEC-096 selection toolbar (Copy / Move / Delete + count/select-all/Clear) keeps labelled buttons
on desktop/tablet and becomes **icon-only 36px buttons** on mobile, with Delete in the danger tone.
Selection checkboxes are present on every real item's row at every breakpoint (no mobile selection
mode); the `..` parent row never carries one (SPEC-098).

#### Acceptance Criteria:

- [ ] At `≥ tablet` the selection toolbar shows labelled Copy / Move / Delete buttons (Delete danger-toned),
      unchanged from SPEC-096.
- [ ] At `< tablet` the Copy / Move / Delete controls render as icon-only 36px buttons with accessible
      labels (`aria-label`), Delete in the danger tone.
- [ ] The selected-count label, select-all, and Clear remain reachable at every width.
- [ ] Every real file/folder row exposes a selection checkbox at mobile, tablet, and desktop widths; the
      `..` row exposes none (SPEC-098 FR-003).
- [ ] Selecting items on mobile reflects in the row's selected treatment (FR-003) and the toolbar count.

### FR-007: Compose the parent row and details panel responsively

#### Description:

The listing composes the SPEC-098 `..` parent row and the SPEC-097 details panel without re-specifying
their mechanics. The `..` row renders as the first listing row when not at the space root, using its
grid variant inside the `hidden tablet:grid` block and its 56px two-line variant inside the `tablet:hidden`
list. The details panel stays button-opened at all widths and presents as a bottom sheet below `tablet`
(SPEC-095 FR-007 `mobileVariant="bottom-sheet"`).

#### Acceptance Criteria:

- [ ] When not at the space root, the `..` row is the first row in both the `hidden tablet:grid` block
      (grid variant) and the `tablet:hidden` list (56px two-line variant); at the root it renders in
      neither (SPEC-098 FR-001).
- [ ] The `..` row has no selection checkbox and is excluded from select-all/count at every width
      (SPEC-098 FR-003).
- [ ] A row's Details control opens `MetadataPanel` / `FolderDetailsPanel` at all widths; below `tablet`
      the panel is a bottom sheet (via the SPEC-095 responsive `Drawer`), not a right slide-over.
- [ ] The details panel's own Download/Rename actions (SPEC-097) are unchanged by this spec.

---

## Data Model

No new persisted data and no new service/hook types. Presentation-only component contract for the new
mobile list row:

```ts
// src/features/file-browser/FileListRowMobile.tsx
type FileListRowMobileProps =
  | {
      kind: 'file';
      file: S3FileItem;
      onActivate: () => void;          // existing download-on-activate handler
      onDetails: (file: S3FileItem) => void;
      selectable: boolean;             // true in writable flows (FR-006)
      isSelected: boolean;
      onToggleSelect: () => void;
    }
  | {
      kind: 'folder';
      folder: S3FolderItem;
      onOpen: () => void;              // existing setPrefix(folder.prefix)
      onDetails: (folder: S3FolderItem) => void;
      selectable: boolean;
      isSelected: boolean;
      onToggleSelect: () => void;
    };
```

## File & Folder Structure

> **Note:** `FileRow`, `FolderRow`, and `SelectionToolbar` are inline function components inside
> `FileBrowser.tsx` (not standalone modules) — edit them in place.

```
src/features/file-browser/
├── FileBrowser.tsx              # responsive shell + rail slot; hidden tablet:grid / tablet:hidden markup swap;
│                                #   mount MobileActionBar (New folder + Upload); responsive breadcrumbs;
│                                #   responsive (inline) SelectionToolbar; compose ParentFolderRow + panel;
│                                #   inline FileRow/FolderRow: Type cell gated on lg (hidden desktop:*)
├── FileBrowser.test.tsx         # breakpoint-swap + bottom-bar + no-overflow-menu assertions (new/updated)
├── FileListRowMobile.tsx        # new — 56px two-line mobile row (file + folder variants)
└── FileListRowMobile.test.tsx   # new — two-line render, trailing size/chevron, selected treatment,
                                 #   checkbox present, activate handlers
```

## Implementation Phases

### Phase 1: Grid column reflow (Type drop at tablet)

- In `FileRow`/`FolderRow` and the `FileBrowser` header row, gate the Type column on `desktop` (`hidden desktop:*`)
  so it shows on desktop and drops at tablet; keep header/body column alignment.
- Wrap the tabular block as `hidden tablet:grid` (or `hidden tablet:block`) so it renders only at `≥ tablet`.

### Phase 2: Mobile two-line list + markup swap

- Build `FileListRowMobile` (file + folder variants): 56px, icon + two-line name/meta, trailing
  size/chevron, selection checkbox, selected treatment (`accent-soft` + inset `accent` bar + checked
  indicator); reuse existing activate/open/details handlers.
- Render the `tablet:hidden` mobile list in `FileBrowser` from the same `files`/`folders` data; place the
  SPEC-098 `..` row's 56px variant first when not at root.

### Phase 3: Shell, breadcrumbs, bottom bar, responsive toolbar

- Apply the responsive shell grid + off-canvas rail slot (feed the Spaces list to `AppNavDrawer`).
- Compact the breadcrumb bar on mobile; mount `MobileActionBar` (New folder + Upload, writable only)
  and add bottom padding to the scroll region; omit the header `⋯` overflow menu.
- Make `SelectionToolbar` icon-only at `< tablet` (Delete danger-toned), labelled at `≥ tablet`.

### Phase 4: Tests + a11y

- Unit tests: `hidden tablet:grid` / `tablet:hidden` swap, Type-column drop at `tablet`, bottom bar `tablet:hidden` +
  read-only omission, icon-only bulk bar on mobile, checkboxes present at all widths, `..` variants,
  details bottom sheet, no overflow menu, no horizontal overflow.
- `vitest-axe` clean on the new mobile list row and the reflowed browser.
