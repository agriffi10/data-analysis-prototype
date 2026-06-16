# Completed Spec - SPEC-026 Dialogs Visual Polish

## What was completed from this spec?

All five file-browser dialogs were restyled onto the design system (styling only):

- **Shared modal shell** (RenameDialog, DeleteConfirmDialog, MoveDialog): `bg-black/40` scrim,
  `bg-surface rounded-lg shadow-lg` card, header section (`px-5 pt-5 pb-4`), and footer section
  (`px-5 py-4 bg-surface-2 border-t border-border rounded-b-lg flex justify-end gap-2`).
- **Button variants** (inline): primary `bg-accent`, default `border-border bg-surface`,
  danger `bg-danger`, ghost `text-text-2 hover:bg-surface-2`.
- **Input** (FR-003): `rounded-md border-border h-9 focus-visible:ring-accent/40`; validation
  errors as `mt-1.5 text-xs text-danger`.
- **CreateFolderDialog**: inline `rounded-lg border-border bg-surface p-4` card; input row with
  primary Create + ghost Cancel.
- **CollisionPrompt**: `warning-soft` inline alert with a warning-triangle SVG; buttons
  reordered to **Rename · Cancel · Overwrite** with Overwrite rightmost and danger-colored.
- **DeleteConfirmDialog**: danger-circle SVG + heading; item list with 16×16 folder/file SVGs;
  red "This can't be undone"; ghost Cancel + danger Delete in the footer.
- **RenameDialog**: modal shell; primary Rename / ghost Cancel.
- **MoveDialog**: `max-w-lg` modal; destination breadcrumb; folder-picker list
  (`max-h-64 rounded-md border-border`) with 16×16 accent folder icons and `h-10` hover rows;
  ghost Cancel + primary Move.

## What has changed?

Styling only — keyboard handling, `onClick`/`stopPropagation` scrim behaviour, refs
(`cancelRef`, `inputRef`), validation logic, and all roles/aria-labels are unchanged.

**Deviation from FR-005 (forced by the test suite):** the spec asked to relabel
CollisionPrompt's rename-toggle button to "Keep both (rename)". `CollisionPrompt.test.tsx`
selects that button by `getByRole('button', { name: /^rename$/i })` (exact accessible name
"Rename"), so relabeling would break the test. The button label was kept as **"Rename"**; the
design intent (warning theme, triangle icon, and the reordering with Overwrite rightmost +
danger-colored) was applied. Likewise MoveDialog's action stays "Move here" / "Moving…" and
DeleteConfirmDialog's stays "Delete" / "Deleting…", matching existing tests.

`lint`, `test` (225), and `build` all green.
