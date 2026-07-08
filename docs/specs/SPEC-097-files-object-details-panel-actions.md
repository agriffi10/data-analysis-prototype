# Spec: Files — Object Details Panel Gains Download & Rename

**ID:** SPEC-097
**Status:** Completed
**Last Updated:** 2026-07-08
**Depends On:** SPEC-096

## Overview

With Download and Rename removed from the multi-select toolbar (SPEC-096), these **single-item**
actions move to the per-object **details panel** — the right slide-over opened by the always-visible
per-row **Details** button. The panel already shows read-only metadata (type, size, modified, storage
class, full S3 key); this spec adds a **Download + Rename** action pair to it. The file panel gets both
Download and Rename; a folder's details panel gets Rename only (folders aren't downloadable).

> **Design reconciliation (user decision, 2026-07-08):** the Claude Design mockup gated this panel to a
> single selection and rendered it as an inline 340px desktop column. Per the user, the panel is **not
> selection-dependent** — it stays **opened by the per-object "Details" button**, which is **visible at
> all breakpoints at all times**. The panel therefore remains the existing button-triggered `Drawer`
> (right slide-over on desktop; a bottom sheet on mobile via SPEC-095 FR-007). The inline-column and
> `count === 1` gating from the mockup are intentionally not adopted. The only functional change here is
> the action pair inside the panel.

## Scope

### In Scope

- Add a **Download** action to the **file** details panel (`MetadataPanel`) that fetches a presigned
  `GetObject` URL via the existing `getDownloadUrl(...)` and downloads with attachment disposition.
- Add a **Rename** action to both the **file** details panel and the **folder** details panel
  (`FolderDetailsPanel`) that opens `RenameDialog` → `useMove` (rename = move within the same parent).
- Place the actions in the panel header/top region: on desktop, Download + Rename split **50/50**
  (file panel); on the mobile sheet they **stack full-width** (≥44px). The folder panel shows Rename
  full-width (single action).
- Keep the per-object **Details** button on every file and folder row, visible at all breakpoints
  (unchanged trigger; no selection dependency).
- Keep all existing read-only metadata rows and the panel's close (button + Escape + scrim) behavior.

### Out of Scope

- Removing/altering the Details-button trigger or making the panel selection-driven (explicitly not
  done — see reconciliation note).
- The multi-select toolbar (SPEC-096) and the `..` row (SPEC-098).
- The drawer-to-bottom-sheet responsive mechanics themselves (owned by SPEC-095 FR-007; this spec only
  ensures the action layout adapts: 50/50 on desktop → stacked full-width on the mobile sheet).
- Any change to `useMove` / `getDownloadUrl` behavior or S3 operations.
- Read-only browse mode: the panel there shows **Download only** (no Rename), consistent with today's
  no-mutation dev-unauth behavior.

---

## Functional Requirements

### FR-001: Download action in the file details panel

#### Description:

The file `MetadataPanel` shows a primary **Download** button that resolves a presigned URL for the
file and triggers a browser download (attachment disposition), reusing the existing download flow.

#### Acceptance Criteria:

- [ ] The file details panel renders a Download button (primary tone, download-arrow icon) in its
      action region.
- [ ] Activating it calls `getDownloadUrl({ bucket, key, fileName })` and initiates the download; a
      failure surfaces the existing error treatment (no silent failure).
- [ ] The button is present in both authenticated and read-only browse modes (download works without
      auth in dev-unauth, per current behavior).

### FR-002: Rename action in the file and folder details panels

#### Description:

Both the file `MetadataPanel` and the `FolderDetailsPanel` show a **Rename** button that opens
`RenameDialog` for that object; confirming runs `useMove`'s rename path (move within the same parent).

#### Acceptance Criteria:

- [ ] Each panel (file and folder) renders a Rename button (secondary tone, pencil icon).
- [ ] Activating it opens `RenameDialog` pre-scoped to the panel's object; for files the extension is
      locked (existing `RenameDialog` behavior).
- [ ] Confirming a rename invokes `useMove` (rename-in-place) and, on collision, runs the existing
      warn-and-confirm; the listing refreshes on success.
- [ ] Rename is **not** shown in read-only browse mode (no mutations without auth).

### FR-003: Action layout — desktop 50/50, mobile stacked

#### Description:

In the file panel the Download + Rename pair sits in a two-up row, each `flex:1` (50/50), on the
desktop/tablet slide-over; on the mobile bottom sheet the two actions stack full-width in a column.
The folder panel shows the single Rename action full-width at all widths.

#### Acceptance Criteria:

- [ ] On the desktop/tablet drawer, Download and Rename are side-by-side, equal width, ≥38px tall.
- [ ] On the mobile sheet (`< tablet`), the file panel's actions stack in a full-width column, ≥44px tall.
- [ ] The folder panel shows Rename as a single full-width action at every width.
- [ ] Read-only mode's file panel shows Download only, full-width (no empty Rename slot).

### FR-004: Details trigger unchanged and always available

#### Description:

The per-row **Details** button remains on every file and folder row and opens the corresponding panel.
It is not tied to selection state and is present at all breakpoints (its row placement is refined for
mobile in SPEC-099, but availability is guaranteed here).

#### Acceptance Criteria:

- [ ] Every file and folder row exposes a Details affordance (`aria-label="Details for {name}"`).
- [ ] Opening a panel does not require the row to be selected and does not mutate selection.
- [ ] The panel closes via its close button, Escape, and scrim/backdrop tap.

---

## API / Interface Contract

```ts
// src/features/file-browser/MetadataPanel.tsx — additional props/handlers
export type MetadataPanelProps = {
  bucket: string;
  file: FileItem;
  rootPrefix: string;
  onClose: () => void;
  canModify: boolean;          // gates Rename (false in read-only browse)
  onRequestRename: (file: FileItem) => void; // opens RenameDialog
  // Download handled internally via getDownloadUrl(...)
};

// src/features/file-browser/FolderDetailsPanel.tsx — additional props
export type FolderDetailsPanelProps = {
  folder: FolderItem;
  onClose: () => void;
  canModify: boolean;          // gates Rename
  onRequestRename: (folder: FolderItem) => void;
};
```

## File & Folder Structure

```
src/features/file-browser/
├── MetadataPanel.tsx          # + Download + Rename action row (50/50 desktop, stacked mobile)
├── MetadataPanel.test.tsx     # assert actions, download call, rename open, read-only gating
├── FolderDetailsPanel.tsx     # + Rename action (full-width)
├── FolderDetailsPanel.test.tsx
└── FileBrowser.tsx            # pass rename handler + canModify into the panels
```

## Implementation Phases

### Phase 1: File panel actions

- Add the Download (internal `getDownloadUrl`) + Rename (opens `RenameDialog`) action row to
  `MetadataPanel`; desktop 50/50, mobile stacked; gate Rename on `canModify`.
- Wire `FileBrowser` to pass the rename handler + `canModify`.

### Phase 2: Folder panel action

- Add the full-width Rename action to `FolderDetailsPanel`; gate on `canModify`.

### Phase 3: Tests

- Unit-test both panels: actions render; Download triggers `getDownloadUrl`; Rename opens the dialog;
  read-only mode hides Rename and (folder) shows no actions; `vitest-axe` clean.
