# Completed Spec — SPEC-098: Parent-Folder (`..`) Row

## What was completed?

A familiar `..` parent-folder row at the top of the file listing when below the space root.

- **Path helpers** in `fileBrowser.paths.ts`: `isAtRoot(currentPrefix, rootPrefix)` and `parentPrefix(currentPrefix, rootPrefix)` (drops the last segment, clamps to the root) + tests.
- **`ParentFolderRow.tsx`** — a non-selectable `<li>` whose whole body is a button (keyboard-activatable): filled-accent folder icon + `..` label, size cell `—`, empty checkbox/type/actions cells for column alignment. No checkbox, no Details, no type pill.
- **`FileBrowser`** renders it as the **first listing row** when `!isAtRoot`, wiring `onNavigateUp → setPrefix(parentPrefix(...))`. It's never added to `allItems`, so select-all / count already exclude it. Navigating up from one level below root lands exactly at the root (row then disappears).
- Empty **non-root** folders now still render the list (so the `..` row stays reachable); the "This folder is empty" message is gated to the space root.

Single (current flex-row) presentation only — the mobile 56px two-line card variant belongs to the responsive table→card-list swap in **SPEC-099** (this spec's out-of-scope explicitly defers that).

## What changed from earlier specs?

- `FileBrowser`'s empty-state gate changed: the empty-folder message now shows at the root only; a non-root empty folder renders the list container with just the `..` row.

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1071, +10). Unit tests: path helpers (root detection, parent clamp), `ParentFolderRow` (renders/navigates/non-selectable), and `FileBrowser` integration (shown below root + navigates up + hidden at root + shown in empty non-root + excluded from select-all).
