---
type: Spec
id: SPEC-026
title: "Dialogs Visual Polish"
description: "Restyles the five file dialogs (create folder, collision prompt, delete confirm, rename, move) with design-system modals, scrim, button variants, and warning and danger status colors."
spec_status: Completed
depends_on: [SPEC-021]
---

## Overview

The portal has five dialog components built across SPEC-016, SPEC-018, and SPEC-019: `CreateFolderDialog`, `CollisionPrompt`, `DeleteConfirmDialog`, `RenameDialog`, and `MoveDialog`. They currently use mixed, generic Tailwind classes (blue/red/amber) and inconsistent button patterns. This spec aligns all five with the design system's modal and inline-alert patterns: centered `rounded-lg shadow-lg` modals on a 32%-black scrim, design-token button variants, status color schemes (warning for collision, danger for delete), and consistent footer layout.

## Scope

### In Scope

- `apps/portal/src/features/file-browser/CreateFolderDialog.tsx`
- `apps/portal/src/features/file-browser/CollisionPrompt.tsx`
- `apps/portal/src/features/file-browser/DeleteConfirmDialog.tsx`
- `apps/portal/src/features/file-browser/RenameDialog.tsx`
- `apps/portal/src/features/file-browser/MoveDialog.tsx`

All changes are `className` and JSX structure only — logic, keyboard handling, ARIA, and refs are untouched.

### Out of Scope

- The move-collision inline alert inside `FileBrowserContent` — it's part of `FileBrowser.tsx` and was updated in SPEC-024.
- `CollisionPrompt` logic (overwrite / rename flow) — only its visual treatment changes.

---

## Functional Requirements

### FR-001: Shared modal shell pattern

#### Description

Every full-screen modal (`DeleteConfirmDialog`, `RenameDialog`, `MoveDialog`) uses the same scrim-and-card pattern.

#### Acceptance Criteria

- [ ] Scrim: `fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40`.
- [ ] Card: `w-full max-w-md bg-surface rounded-lg shadow-lg` (no `p-5` on the card root — padding lives inside sections).
- [ ] Card header section: `px-5 pt-5 pb-4`.
- [ ] Card footer section: `px-5 py-4 bg-surface-2 border-t border-border rounded-b-lg flex justify-end gap-2`.
- [ ] `onClick` on the scrim calls `onCancel` (existing behaviour preserved).
- [ ] `e.stopPropagation()` on the card (existing behaviour preserved).

### FR-002: Button variants (shared across all dialogs)

#### Description

Every button in every dialog uses one of four standard variants. No one-off colors.

#### Acceptance Criteria

Reusable class strings (inline in components — no shared component needed yet):

- **Primary** (`bg-accent`): `rounded-md bg-accent px-4 h-9 text-base font-medium text-white hover:bg-accent-hover disabled:opacity-45 disabled:cursor-not-allowed`.
- **Default** (secondary): `rounded-md bg-surface border border-border px-4 h-9 text-base font-medium text-text hover:bg-surface-2 disabled:opacity-45 disabled:cursor-not-allowed`.
- **Danger** (destructive primary): `rounded-md bg-danger px-4 h-9 text-base font-medium text-white hover:bg-danger/90 disabled:opacity-45 disabled:cursor-not-allowed`.
- **Ghost** (cancel / back): `rounded-md px-4 h-9 text-base font-medium text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-45 disabled:cursor-not-allowed`.

### FR-003: Input field style (shared)

#### Description

Text inputs in dialogs (new folder name, rename field) use a consistent style.

#### Acceptance Criteria

- [ ] Input: `w-full rounded-md border border-border bg-surface px-3 h-9 text-base text-text placeholder:text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:border-accent disabled:opacity-45`.
- [ ] Validation error message: `mt-1.5 text-xs text-danger` (replaces `text-sm text-red-600`).
- [ ] `aria-invalid` and `aria-describedby` are preserved.

### FR-004: CreateFolderDialog

#### Description

Currently rendered as an inline card (no scrim). It should remain inline — it's an inline form embedded in the write-controls area, not a blocking modal.

#### Acceptance Criteria

- [ ] Container: `rounded-lg border border-border bg-surface p-4 mb-4`.
- [ ] Label: `block text-sm font-medium text-text mb-2`.
- [ ] Input row: `flex items-center gap-2` with the input (`flex-1`, FR-003 style), Create button (primary), and Cancel button (ghost).
- [ ] Error: FR-003 validation error style.
- [ ] Create button: primary variant (FR-002).
- [ ] Cancel button: ghost variant (FR-002).

### FR-005: CollisionPrompt

#### Description

The collision prompt is an inline alert (no scrim) styled with `warning` colors. It warns the user that a file or folder with the same name exists and offers three choices: Keep both (rename), Cancel, or Overwrite.

The current component has two views: the default prompt (Overwrite / Rename / Cancel buttons) and a rename input view. Both need design system styling.

#### Acceptance Criteria

- [ ] Container: `rounded-lg border border-warning-soft bg-warning-soft p-4 mb-4 text-sm`.
- [ ] Warning icon (add): a 20×20 warning-triangle SVG in `text-warning` inline before the message text.
- [ ] Heading: `font-medium text-warning` — existing "A {kind} named "{name}" already exists." copy.
- [ ] Default view buttons (`mt-3 flex flex-wrap gap-2`):
  - "Keep both (rename)" → default button variant (FR-002) but smaller: `h-8 px-3 text-sm`.
  - "Cancel" → ghost variant, `h-8 px-3 text-sm`.
  - "Overwrite" → danger variant, `h-8 px-3 text-sm`.
  - **Note:** Reorder to match design system: Keep both · Cancel · Overwrite — "Overwrite" always rightmost and danger-colored so it's visually distinct.
- [ ] Rename input view: FR-003 input style; "Save as new name" button = primary (h-8 px-3 text-sm); "Back" = ghost (h-8 px-3 text-sm).
- [ ] The warning-triangle SVG (inline):

```tsx
<svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5 text-warning shrink-0" aria-hidden="true">
  <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
</svg>
```

### FR-006: DeleteConfirmDialog

#### Description

The delete dialog follows the shared modal shell (FR-001) with a danger-themed footer.

#### Acceptance Criteria

- [ ] Modal shell per FR-001.
- [ ] Header section: icon + heading. Add a 24×24 danger-circle SVG (`text-danger` on `bg-danger-soft rounded-full p-1`) inline before the heading text — or place it on its own line above the heading.
- [ ] Heading: `text-md font-semibold text-text` (the existing conditional heading logic is preserved).
- [ ] Item list (`count > 1`): `mt-3 max-h-36 overflow-auto rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text`.
  - List items use the same SVG folder/file icons from SPEC-024 (16×16), `text-text-3`.
  - "…and N more": `text-text-3`.
- [ ] Folder warning `<p>`: `mt-3 text-sm text-text-2`.
- [ ] "This can't be undone" `<p>`: `mt-2 text-sm font-medium text-danger`.
- [ ] Footer per FR-001:
  - Cancel → ghost variant.
  - Delete → danger variant. Busy label: "Deleting…".

### FR-007: RenameDialog

#### Description

The rename dialog follows the shared modal shell (FR-001).

#### Acceptance Criteria

- [ ] Modal shell per FR-001.
- [ ] Heading: `text-md font-semibold text-text` — existing copy.
- [ ] Label `<label>`: `mt-4 block text-sm font-medium text-text`.
- [ ] Input: FR-003 style, `mt-1.5`.
- [ ] Validation error: FR-003 error style.
- [ ] Footer per FR-001:
  - Cancel → ghost variant.
  - Rename → primary variant. Busy label: "Renaming…".

### FR-008: MoveDialog

#### Description

`MoveDialog` is the most complex — it contains a folder-picker tree, a breadcrumb path, and a footer with Move / Cancel. The folder browser inside is a minimal sub-list, not a full file browser.

#### Acceptance Criteria

- [ ] Modal shell per FR-001, but `max-w-lg` (wider than other dialogs to fit the folder tree).
- [ ] Heading: `text-md font-semibold text-text` — e.g. "Move {N} item(s)".
- [ ] Current destination breadcrumb below heading: `text-sm text-text-2 mt-1`.
- [ ] Folder picker list: inside the card body (`px-5 py-4`), with a `max-h-64 overflow-y-auto rounded-md border border-border bg-surface` container.
  - Folder items: `flex items-center gap-2 px-3 h-10 cursor-pointer hover:bg-surface-2 text-sm text-text` with the filled indigo SVG folder icon (16×16, from SPEC-024) and the folder name.
  - Selected/active destination row: `bg-accent-soft text-accent-text`.
  - ".." (parent folder) row if applicable: `text-text-2`.
- [ ] Empty folder state inside picker: `py-4 text-center text-sm text-text-3`.
- [ ] Loading state inside picker: same muted treatment.
- [ ] Footer per FR-001:
  - Cancel → ghost variant.
  - Move → primary variant. Disabled when the destination equals the current prefix. Busy label: "Moving…".

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── CreateFolderDialog.tsx    ← visual update
├── CollisionPrompt.tsx       ← visual update
├── DeleteConfirmDialog.tsx   ← visual update
├── RenameDialog.tsx          ← visual update
└── MoveDialog.tsx            ← visual update
```

---

## Implementation Phases

### Phase 1: Shared patterns — inputs and buttons

Decide on the class strings for the four button variants and the input field (FR-002, FR-003) and write them as constants or comments at the top of each file. Apply to `CreateFolderDialog` and `RenameDialog` first (simplest structure).

#### Checkpoint

Open the files page, create a new folder — the inline form shows a hairline-bordered card with correct input and button styles. Click Rename on a row — the modal shows with the correct card/footer split.

### Phase 2: CollisionPrompt and DeleteConfirmDialog

Apply warning/danger color schemes and add the icon SVGs. Reorder CollisionPrompt buttons per FR-005.

#### Checkpoint

Upload a file that collides — the yellow warning inline alert appears with a triangle icon and the three buttons in the correct order (Keep both · Cancel · Overwrite). Select files and delete — the modal shows the red "This can't be undone" line and a red Delete button.

### Phase 3: MoveDialog

Apply the modal shell and folder-picker list styling.

#### Checkpoint

Select a file or folder and trigger Move — the wider modal opens with the folder picker list; selecting a folder highlights it in `accent-soft`.

### Phase 4: Tests

`npm run test -w apps/portal` — all dialog tests pass (they check structure and ARIA, not class names).

---

## Open Questions

_None._
