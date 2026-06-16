# Completed Spec - SPEC-024 File Browser Visual Polish

## What was completed from this spec?

`FileBrowser.tsx` and `FilesPage.tsx` were restyled onto the design system (styling only):

- **FilesPage**: `<main>` now `px-4 py-6` with no `max-w-4xl` clamp; the `<h1>Files</h1>`
  heading was removed (breadcrumbs are the location indicator); config-error alert uses
  `border-danger bg-danger-soft text-danger`.
- **Table container**: a `bg-surface border border-border rounded-lg overflow-hidden`
  wrapper with a **column-header row** (`bg-surface-2 h-10`, uppercase `text-xs` labels —
  Name / Size / Modified / Type) above the `<ul>`. Shared width constants (`w-24`, `w-40`,
  `w-28`) keep header and rows aligned.
- **Rows** (`FolderRow`/`FileRow`): 48px (`h-12`), `border-border-2` dividers,
  `hover:bg-surface-2`, selected `bg-accent-soft`. Emoji icons replaced with inline SVGs
  (filled `text-accent` folder, outlined `text-text-3` file). Names truncate
  (`text-base font-medium`). Type pill shows "Folder" or the uppercased extension. Folder
  size shows an em-dash; the expand `›` arrow was dropped (the name cell is the nav target).
- **Row actions**: revealed on row hover as an absolute right-aligned overlay
  (`opacity-0 group-hover:opacity-100`, bg matched to the row state so it masks the cells).
  Folder → Rename; File → Details / Rename / Download (Download in `accent-text`, busy = "…").
- **Selection bar** (`SelectionToolbar`): `h-11 rounded-lg` bar; turns
  `bg-accent-soft border-accent` with an `accent-text` "{N} selected" count when ≥1 selected,
  neutral otherwise. Move (ghost) + Delete (danger-ghost). Checkboxes use `accent-accent`.
- **States**: loading (`py-16 text-text-3`), error (`border-danger-soft bg-danger-soft`,
  "Failed to load files"), empty (40×40 SVG empty-folder icon + `text-xl` headline + guidance
  shown only when writable).
- **Banners**: delete/move success → `success-soft`; partial failure → `warning-soft`;
  systemic download/delete/move errors → `danger-soft`; all with a muted Dismiss link.
- **Load more**: ghost button (`h-9 rounded-md border-border`).

## What has changed?

Decisions / deviations from the literal spec, all forced by existing behaviour + the test
suite (225 tests, unchanged, all passing):

1. **Selection bar is always rendered, not swapped in on selection.** FR-007 describes the
   bar "replacing" the toolbar when ≥1 item is selected. The existing multi-select toolbar
   (and `FileBrowser.test.tsx`'s "disables Delete until something is selected") requires the
   Delete button to be present-but-disabled at zero selection, so the bar can't be unmounted
   at count 0. Resolution: the bar always renders and only takes the accent-soft treatment
   (and the "{N} selected" label) once `count > 0`. The breadcrumb toolbar row stays visible
   alongside it.
2. **New folder moved into the toolbar row; the dropzone stays always-mounted below.** Per
   the spec's Open Question (deferred to SPEC-025), the upload trigger mechanism was left as
   the always-shown `UploadDropzone`; only the "New folder" button was restyled and relocated
   into the breadcrumb toolbar row. No toolbar "Upload" button was added.
3. **Row actions are an absolute hover overlay** (rather than inline trailing cells) so the
   Name/Size/Modified/Type columns stay aligned with the header regardless of how many
   actions a row has.

All aria-labels (`Open folder X`, `Download X`, `Details for X`, `Rename X`, `Select X`,
`Select all`), the breadcrumb nav, the `File list` list, and result/error roles are
preserved unchanged. `lint`, `test` (225), `build` all green.

> Visual note: the authenticated file browser isn't reachable in the static preview build
> (no auth / no dev-unauth), so verification was via the build + the full DOM-level test
> suite rather than a live screenshot.
