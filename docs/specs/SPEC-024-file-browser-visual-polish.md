# Spec: File Browser Visual Polish

**ID:** SPEC-024  
**Status:** Completed  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021

## Overview

The file browser is the core of the portal UI, and it currently uses generic Tailwind utilities (gray scale, blue highlights, emoji icons). This spec replaces those with the design system's table-forward layout: a `surface` container with `border` and `rounded-lg`, a `surface-2` header row with uppercase column labels, 48px rows with hover and selection states, SVG folder/file icons, type pills, and a proper selection toolbar using `accent-soft`. The breadcrumb toolbar and the page-level layout (`FilesPage.tsx`) are also updated.

This spec is **styling only** — no business logic, hook behaviour, or accessibility semantics change.

## Scope

### In Scope

- `apps/portal/src/features/file-browser/FileBrowser.tsx` — all JSX and `className` props for: `FileBrowserContent`, `FolderRow`, `FileRow`, `SelectionToolbar`, breadcrumbs, loading/error/empty states, delete/move result banners, load-more button.
- `apps/portal/src/routes/FilesPage.tsx` — page wrapper class and the "Files" heading style.
- Replacing emoji folder (`📁`) and file (`📄`) icons with SVG icons as specified below.

### Out of Scope

- `UploadDropzone` — covered in SPEC-025.
- `CreateFolderDialog`, `CollisionPrompt` — covered in SPEC-026.
- `MetadataPanel` — covered in SPEC-027.
- Any non-styling changes to hooks, services, or types.

---

## Functional Requirements

### FR-001: Page layout

#### Description

The `FilesPage` wrapper provides proper content area padding and alignment. The "Files" heading no longer appears as a separate h1 — navigation context is communicated entirely by the breadcrumbs (design system pattern).

#### Acceptance Criteria

- [ ] `FilesPage` outer `<main>` uses `py-6 px-4` (or `p-6`) with no max-width constraint — the browser fills the available content column.
- [ ] The `<h1>Files</h1>` heading is removed; breadcrumbs serve as the location indicator.
- [ ] The configuration error alert uses design token colors: `bg-danger-soft border border-danger text-danger rounded-lg p-4`.

### FR-002: Toolbar row

#### Description

The toolbar row (containing breadcrumbs + primary actions on the right) sits above the table. When nothing is selected it shows the breadcrumbs on the left and "New folder" + "Upload" buttons on the right. When items are selected the toolbar is replaced by the selection bar (FR-006).

#### Acceptance Criteria

- [ ] Toolbar row: `flex items-center gap-3 mb-4` — breadcrumbs on the left, action buttons flush right.
- [ ] "Upload" button (primary): `bg-accent text-white text-base font-medium rounded-md px-4 h-9 hover:bg-accent-hover disabled:opacity-45`. **Note:** the upload trigger was previously an `UploadDropzone` always visible — the toolbar should expose a visible "Upload" button that opens the dropzone (if the dropzone is always shown, the button is omitted; keep whatever the current trigger mechanism is, just style the existing "New folder" button correctly).
- [ ] "New folder" button (default): `bg-surface border border-border text-text text-base font-medium rounded-md px-4 h-9 hover:bg-surface-2 disabled:opacity-45`.
- [ ] Buttons are hidden when `!writable`.

### FR-003: Breadcrumbs

#### Description

Breadcrumbs render inside the toolbar row. Each segment is a clickable link except the last (current folder), which is non-interactive.

#### Acceptance Criteria

- [ ] Breadcrumb `<ol>`: `flex items-center gap-1 text-sm flex-1 min-w-0`.
- [ ] Separator `/`: `text-text-3 mx-0.5`.
- [ ] Non-final crumb `<button>`: `text-text-2 hover:text-text hover:underline truncate max-w-[160px]`.
- [ ] Final crumb `<span>`: `text-text font-semibold truncate max-w-[200px]` with `aria-current="page"`.

### FR-004: File table container

#### Description

The file and folder list is displayed as a table-styled container — not a floating card.

#### Acceptance Criteria

- [ ] `<ul>` (file list): `bg-surface border border-border rounded-lg overflow-hidden`.
- [ ] A table header row is added **above** the `<ul>` (as a sibling div inside the same container wrapper) showing column labels: Name, Size, Modified, Type. The header is not inside the `<ul>` — implement as a `<div>` with matching column widths using CSS grid or flex.
- [ ] Header row: `bg-surface-2 border-b border-border px-4 h-10 flex items-center`.
- [ ] Header columns: `text-xs font-semibold uppercase tracking-wide text-text-3`.
- [ ] Column layout (flex, proportional): `[name flex-1] [size w-24 text-right] [modified w-40 text-right] [type w-28 text-right]`. The checkbox column (40px) is present when `canModify` is true.

### FR-005: Folder rows

#### Description

Folder rows use an SVG folder icon (not the 📁 emoji), design-system hover state, and the grid column layout matching the header.

#### Acceptance Criteria

- [ ] Row `<li>`: `h-12 flex items-center border-b border-border-2 last:border-0 hover:bg-surface-2 group`.
- [ ] Row selected: add `bg-accent-soft` (use conditional class — remove hover when selected).
- [ ] Checkbox column (40px, `canModify` only): `<input type="checkbox">` with `accent-color: #4f46e5` via `className="accent-accent"` (Tailwind v4 accent-color utility, or use `style={{ accentColor: 'var(--color-accent)' }}`).
- [ ] Name cell: `flex-1 flex items-center gap-2.5 min-w-0 px-4`.
  - SVG folder icon: 20×20, `text-accent`, filled. Use a simple filled folder SVG: `<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-accent flex-shrink-0">` with a folder path.
  - Folder name: `text-base font-medium text-text truncate`.
- [ ] Size cell: `w-24 text-right text-sm text-text-3 pr-4` — shows `—` (em-dash) for folders.
- [ ] Modified cell: `w-40 text-right text-sm text-text-2 pr-4` — empty for folders.
- [ ] Type cell: `w-28 text-right pr-4` — shows a neutral pill: `<span className="inline-flex items-center rounded-full bg-surface-2 border border-border px-2 py-0.5 text-xs text-text-2">Folder</span>`.
- [ ] Row action buttons (Rename, row-hover reveal): `opacity-0 group-hover:opacity-100 transition-opacity`. Ghost style: `text-sm text-text-2 hover:text-text hover:bg-surface-2 rounded-md px-2 h-7`.
- [ ] The expand arrow `›` is removed — navigation is the click target on the entire name cell, not a separate arrow.

### FR-006: File rows

#### Description

File rows follow the same grid layout and hover pattern as folder rows, with a different icon and additional inline actions.

#### Acceptance Criteria

- [ ] Row structure, column widths, hover/selected states: identical to FR-005.
- [ ] SVG file icon: 20×20, `text-text-3`, outlined. Use a simple document SVG: `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-text-3 flex-shrink-0">` with a page/doc path.
- [ ] File name: `text-base font-medium text-text truncate`.
- [ ] Size: `text-sm text-text-2`.
- [ ] Modified: `text-sm text-text-2`.
- [ ] Type cell: neutral pill as in FR-005 but shows the file extension uppercased (e.g. "PDF", "TXT"). If no extension, shows "File".
- [ ] Row actions (Details, Rename, Download — all group-hover reveal):
  - Details (ghost): `text-sm text-text-2 hover:text-text hover:bg-surface-2 rounded-md px-2 h-7`.
  - Rename (ghost): same.
  - Download (ghost, accent): `text-sm text-accent-text hover:bg-accent-soft rounded-md px-2 h-7`.
  - Downloading busy state: same Download button but shows "…" and is `disabled`.

### FR-007: Selection toolbar

#### Description

When ≥1 row is selected, the standard toolbar is replaced by the `accent-soft` selection bar.

#### Acceptance Criteria

- [ ] Selection bar container: `flex items-center gap-3 mb-4 h-11 px-4 rounded-lg bg-accent-soft border border-accent` (matches design system "Selection bar" pattern).
- [ ] Master checkbox: `accent-accent` (indigo), triggers select-all / clear.
- [ ] Count label: `text-sm font-semibold text-accent-text` — "{N} selected".
- [ ] Spacer: `flex-1`.
- [ ] Move button (ghost): `text-sm font-medium text-text-2 hover:text-text hover:bg-white/60 rounded-md px-3 h-8`.
- [ ] Delete button (danger-ghost): `text-sm font-medium text-danger hover:bg-danger-soft rounded-md px-3 h-8`.
- [ ] Both buttons: `disabled:opacity-45 disabled:cursor-not-allowed`.

### FR-008: Loading, error, and empty states

#### Description

Each state renders a properly styled inline panel.

#### Acceptance Criteria

- [ ] **Loading**: `flex justify-center items-center py-16 text-text-3 text-sm` with a simple "Loading…" text (no spinner component needed yet).
- [ ] **Error**: `rounded-lg border border-danger-soft bg-danger-soft p-4 text-danger` — heading "Failed to load files" in `font-medium`, detail text in `text-sm mt-1`.
- [ ] **Empty**: centered `py-16 text-center` block — an SVG empty-folder icon (40×40, `text-text-3`), then `text-xl font-semibold text-text mt-4`, then `text-sm text-text-2 mt-2 max-w-xs mx-auto`. Text: heading "This folder is empty", subtext "Upload a file or create a folder to get started." (only shown when `writable`; otherwise just "This folder is empty.").

### FR-009: Result banners (delete / move)

#### Description

Post-operation success and partial-failure banners use design-system status colors.

#### Acceptance Criteria

- [ ] **Success** banner (no errors): `rounded-lg border border-success-soft bg-success-soft text-success`.
- [ ] **Partial failure** banner: `rounded-lg border border-warning-soft bg-warning-soft text-warning`.
- [ ] **Systemic error** alert (download/delete/move error): `rounded-lg border border-danger-soft bg-danger-soft text-danger`.
- [ ] Each banner has `p-3 text-sm` and a right-aligned "Dismiss" ghost button: `text-xs font-medium hover:underline opacity-70 hover:opacity-100`.

### FR-010: Load more button

#### Description

The paginated "Load more" button below the table uses the design system's ghost button style.

#### Acceptance Criteria

- [ ] Button: `mt-4 flex justify-center` wrapper; button itself: `rounded-md border border-border px-4 h-9 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:opacity-45 disabled:cursor-not-allowed`.

---

## Data Model

_No new TypeScript types. A helper `fileExtension(name: string): string` can be added inline in FileBrowser.tsx to compute the type pill label._

---

## API / Interface Contract

SVG icons needed (inline, no icon library):

**Folder (filled, 20×20):**
```tsx
<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-accent flex-shrink-0" aria-hidden="true">
  <path d="M2 6a2 2 0 012-2h3.586a1 1 0 01.707.293l1.414 1.414A1 1 0 0010.414 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
</svg>
```

**File (outlined, 20×20):**
```tsx
<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-text-3 flex-shrink-0" aria-hidden="true">
  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 3H7a2 2 0 00-2 2v10a2 2 0 002 2h6a2 2 0 002-2V7.5L13.5 3z" />
  <path strokeLinecap="round" strokeLinejoin="round" d="M13 3v4.5H17.5" />
</svg>
```

**Empty folder (40×40, used in empty state):**
```tsx
<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-10 w-10 text-text-3 mx-auto" aria-hidden="true">
  <path strokeLinecap="round" strokeLinejoin="round" d="M4 12a4 4 0 014-4h7.172a2 2 0 011.414.586l2.828 2.828A2 2 0 0020.828 12H32a4 4 0 014 4v12a4 4 0 01-4 4H8a4 4 0 01-4-4V12z" />
</svg>
```

---

## File & Folder Structure

```
apps/portal/src/
├── features/file-browser/
│   └── FileBrowser.tsx     ← visual update (all sub-components within)
└── routes/
    └── FilesPage.tsx       ← remove h1 heading, update layout classes
```

---

## Implementation Phases

### Phase 1: Table structure and row components

Update `FolderRow` and `FileRow` first — they are the most visually impactful. Add the column header div. Replace emoji with SVG icons.

#### Checkpoint

`npm run dev`: verify folder rows show indigo SVG icons, rows are 48px, hover shows `surface-2`, and the column header shows uppercase labels.

### Phase 2: Toolbar, breadcrumbs, selection bar

Update `SelectionToolbar` (selection bar), the breadcrumb `<nav>`, and the write-controls toolbar.

#### Checkpoint

Select 2 items — the toolbar swaps to the indigo `accent-soft` selection bar with "2 selected" in accent text.

### Phase 3: States and banners

Update loading, error, empty states and all result/error banners. Update `FilesPage.tsx`.

#### Checkpoint

Navigate to an empty folder — the empty state icon + heading renders correctly. `npm run test -w apps/portal` passes.

---

## Open Questions

- [ ] The current upload trigger is an `UploadDropzone` always mounted below the write controls. If a toolbar "Upload" button is added in FR-002, it should toggle the dropzone visibility. Confirm whether toggling the dropzone or always-showing it is the preferred UX before Phase 2 — this spec intentionally defers to SPEC-025 for the dropzone itself.
