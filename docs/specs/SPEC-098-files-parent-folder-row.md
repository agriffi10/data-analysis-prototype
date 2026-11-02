---
type: Spec
id: SPEC-098
title: "Files — Parent-Folder (`..`) Row"
description: "Adds a parent-folder (..) row at the top of every file-browser listing that navigates up one level, hidden at the space root and excluded from selection and select-all."
spec_status: Completed
depends_on: []
arc: responsive-and-files-ux
arc_order: 4
---

## Overview

The file browser currently offers only breadcrumb links to move up the tree. The Claude Design mockups
add a familiar filesystem affordance: a **`..` parent-folder row** at the top of every listing that
navigates up one level. It appears as the first row at all breakpoints and is hidden only at the space
root. It is navigation, not an item — it has no checkbox and is excluded from selection and select-all.

## Scope

### In Scope

- Render a `..` row as the **first listing row** whenever the current prefix is **not** the space root.
- Clicking it navigates to the parent prefix (drop the last path segment of the current prefix).
- Make it non-selectable: no checkbox, excluded from `useSelection().selectAll(...)` and from `count`.
- Style it per the mockup at each breakpoint (desktop/tablet grid row 48px; mobile 56px two-line row).
- Omit the row at the space root (personal `{username}/` root, or a shared space's root prefix).

### Out of Scope

- Breadcrumbs (unchanged; the `..` row is additive, not a replacement).
- The details panel (SPEC-097) — the `..` row has no Details affordance.
- Responsive table/list markup swap itself (SPEC-099); this spec styles the row within whichever markup
  is active but does not own the table→list swap.
- Any change to `useFileBrowser` data fetching or S3 listing.

---

## Functional Requirements

### FR-001: Render `..` as the first row when not at root

#### Description:

When the current prefix is below the space root, a `..` row renders above all folders/files. At the
space root it is omitted.

#### Acceptance Criteria:

- [ ] In any non-root prefix, the first listing row is the `..` row (above folders and files).
- [ ] At the space root (personal `{username}/` or a shared space's root prefix), no `..` row renders.
- [ ] Root detection uses the active space's root prefix from `useFileSpace(...)`, not a hardcoded path.

### FR-002: Navigate up on activation

#### Description:

Activating the `..` row navigates to the parent prefix (the current prefix minus its last path
segment). Selection clears on the prefix change (existing `SelectionProvider` behavior).

#### Acceptance Criteria:

- [ ] Clicking (or keyboard-activating) the row navigates to the immediate parent prefix.
- [ ] After navigation, the listing reflects the parent and the selection is cleared.
- [ ] The row is keyboard-focusable and activatable (Enter/Space), with a visible focus ring.
- [ ] Navigating up from one level below root lands exactly at the root (where the `..` row then
      disappears).

### FR-003: Non-selectable and excluded from selection

#### Description:

The `..` row carries no checkbox and is never part of the selection set; select-all ignores it and it
never contributes to `count`.

#### Acceptance Criteria:

- [ ] The row's checkbox grid cell is empty (no checkbox rendered).
- [ ] `selectAll` over the listing does not add the `..` row; `count` never includes it.
- [ ] Toggling select-all with a `..` row present selects only the real files/folders.

### FR-004: Per-breakpoint styling

#### Description:

The row matches the mockup: a filled indigo (`accent`) folder icon + `..` label; a size cell of `—` on
grid layouts; a two-line `..` / "Up one level" presentation on the mobile list.

#### Acceptance Criteria:

- [ ] Desktop/tablet (grid): 48px row, `accent`-fill folder icon + `..` label (`text-2`, weight 500),
      size cell shows `—` (`text-3`), other cells empty, `cursor: pointer`.
- [ ] Mobile (list): 56px row, folder icon + two lines — `..` over "Up one level" (`text-3`), no
      trailing chevron.
- [ ] The row visually reads as navigation (no selection checkbox, no type pill, no Details button).

---

## API / Interface Contract

```ts
// Parent-prefix helper (co-located util or existing path util)
// "alice/docs/reports/" -> "alice/docs/"; returns rootPrefix when one level below root.
export function parentPrefix(currentPrefix: string, rootPrefix: string): string;

// isAtRoot(currentPrefix, rootPrefix) -> boolean  (drives whether the row renders)
```

## File & Folder Structure

```
src/features/file-browser/
├── ParentFolderRow.tsx        # new (grid + list presentations, or a variant prop)
├── ParentFolderRow.test.tsx   # new
├── FileBrowser.tsx            # render the row first when !isAtRoot; wire navigate-up
└── (path util)                # parentPrefix / isAtRoot helper + test
```

## Implementation Phases

### Phase 1: Helper + row

- Add `parentPrefix` / `isAtRoot` helpers with unit tests.
- Build `ParentFolderRow` (grid + mobile-list presentations) with keyboard support.

### Phase 2: Integrate

- Render the row as the first listing row in `FileBrowser` when not at root; wire navigate-up.
- Ensure `selectAll`/`count` exclude it (adjust the items passed to `selectAll`).

### Phase 3: Tests

- Root vs non-root rendering; navigate-up lands correctly (incl. one-below-root → root); select-all
  excludes the row; keyboard activation; `vitest-axe` clean.
