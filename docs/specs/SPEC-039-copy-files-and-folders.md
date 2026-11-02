---
type: Spec
id: SPEC-039
title: "Copy Files and Folders (recursive)"
description: "Adds a copy action for files and folders, single or multi-select and recursive, that leaves the original in place, with warn-and-confirm collisions and a suggested new name when copying into the same folder."
spec_status: Completed
depends_on: [SPEC-013, SPEC-014, SPEC-015, SPEC-018, SPEC-019]
arc: file-operations
arc_order: 7
---

**Dependency notes:** SPEC-013 (`s3:GetObject` + `s3:PutObject` on own prefix), SPEC-014 (marker), SPEC-015 (data foundation + invalidation), SPEC-018 (selection state), SPEC-019 (`copyObject`, destination picker, collision flow — reused)
## Overview

Add **copy** to the file browser. Move and rename shipped in SPEC-019 (as copy-then-delete), but a plain copy — duplicate a file or folder, leaving the original in place — was never exposed. This spec surfaces copy as a first-class action (single-row and multi-select), for both files and folders, reusing the `copyObject` primitive SPEC-019 already built. A folder copy is recursive over every contained key. Copy is strictly additive (no source delete), so its failure semantics are simpler than move's — but it shares move's collision handling (warn-and-confirm) and adds one new case: copying into the **same folder**, where the name necessarily collides with the source, so the app proposes a suffixed name (e.g. `report copy.pdf`).

## Scope

### In Scope

- Copy a file or folder to **any destination folder within the user's own space** — this is the primary case; the original is always left intact
- Copy in place (destination = the item's current folder) → auto-numbered name (`{name} (1)`, then `{name} (2)`, …) since the source name would otherwise collide
- `copyFolder` service: recursive copy of every key under a source prefix (the copy-only counterpart to SPEC-019's `moveFolder`)
- Reuse SPEC-019's single-object `copyObject` primitive, and a **shared destination picker** (`DestinationPicker`) used by both Move and Copy — extracted from SPEC-019's `MoveDialog`
- Collision handling at the destination: HEAD-check, warn-and-confirm (Overwrite or Rename) — reusing SPEC-019's `CollisionPrompt`
- Multi-select copy (reusing the SPEC-018 selection store)
- Listing refetch (TanStack Query invalidation) for the **destination** prefix only (the source is unchanged)
- A **Copy** action in the row hover-actions and the multi-select selection bar

### Out of Scope

- Cross-user or cross-bucket (shared-space) copies — Bucket 2 is a separate arc
- Drag-and-drop / copy-paste-keyboard UX — copy is driven by an action menu + destination picker here (consistent with SPEC-019)
- Copying **into** the protected `athenaresults/` folder — that folder is UI-locked (SPEC-032); copying *out of* it (duplicating a result elsewhere) is allowed since `GetObject` is permitted
- Any IAM change — copy uses the existing `s3:GetObject` (source) + `s3:PutObject` (destination), both within the user's own prefix (SPEC-013); no `DeleteObject` is involved at all

---

## Functional Requirements

### FR-001: Copy Service (single object)

#### Description:

Reuse the SPEC-019 primitive; copy never deletes the source.

#### Acceptance Criteria:

- [ ] `copyObject({ bucket, sourceKey, destKey, username, overwrite? })` (already exists, SPEC-019) is used as-is: same-bucket `CopyObjectCommand`, URL-encoded `CopySource`, marker guard, collision guard; returns `ServiceResult<{ destKey: string }>`
- [ ] Copy performs **no** `DeleteObject` under any circumstance (the distinction from `moveObject`)
- [ ] A `sourceKey === destKey` request is rejected/normalized into the same-folder suffix flow (FR-003), never a silent no-op that would appear to do nothing
- [ ] The user-root marker (`{root}/DO_NOT_DELETE.txt`) is never a valid source or destination (descriptive error) — inherited from `copyObject`
- [ ] Credential-expiry triggers one transparent retry via `getS3Client(true)` — inherited
- [ ] Unit tests cover copy success, no-delete invariant, marker rejection, and the credential-retry path

### FR-002: Recursive Folder Copy + Partial Failure

#### Description:

Folder copy processes every contained object and degrades safely.

#### Acceptance Criteria:

- [ ] `copyFolder({ bucket, sourcePrefix, destPrefix, username, overwrite?, onProgress? })` lists **all** keys under `sourcePrefix` (paginating past 1,000), computing each destination key by replacing the `sourcePrefix` portion with `destPrefix`
- [ ] Each object is copied (no deletes); the result reports `{ copied: string[]; errors: { key: string; message: string }[] }` (`CopyResult`)
- [ ] A copy that fails for one key does **not** abort the remaining keys (best-effort, like `moveFolder`); there is no rollback of already-copied keys (a comment notes this — a partial folder copy leaves a partial duplicate, which the user can delete)
- [ ] Copying a folder **into itself or its own subtree** is prevented (same guard as `moveFolder`) — a folder can't be its own copy destination
- [ ] Progress (objects processed / total) is surfaced to the UI for large folders via `onProgress`
- [ ] After a fully successful folder copy, the source subtree is **unchanged** and an identical subtree exists under the destination (verified in tests with a mocked multi-page listing)

### FR-003: Copy Into the Same Folder (auto-number)

#### Description:

Copying to a **different** folder uses the item's existing name (FR-004). Only when the chosen destination is the item's **current** parent would the name collide with the source — in that case the app appends a number to the name so the duplicate sits beside the original.

#### Acceptance Criteria:

- [ ] When the chosen destination equals the item's current parent, the app generates a non-colliding name by appending a number at the end of the name: for a file, before the extension (`report.pdf` → `report (1).pdf`); for a folder, on the leaf (`docs/` → `docs (1)/`)
- [ ] If `{name} (1)` also exists, increment: `{name} (2)`, `{name} (3)`, … (HEAD-checked until free)
- [ ] The proposed name is shown to the user (editable) before the copy runs, so they can override it
- [ ] The generated name is validated with the same rules as create-folder/rename (non-empty trimmed, no `/`, no control chars)
- [ ] This auto-number flow applies **only** to same-folder copies; copying to a different folder keeps the original name (and only prompts on a genuine destination collision, FR-005)

### FR-004: Copy UI (row + multi-select) + Destination Picker

#### Acceptance Criteria:

- [ ] A **Copy** action appears in the row hover-actions (per file/folder) and in the multi-select selection bar (alongside Download, Rename, Move, Delete from SPEC-018/019)
- [ ] Copy opens the **shared `DestinationPicker`** (FR-006) listing any folder within the user's own space; the protected `athenaresults/` folder is **not** selectable as a destination
- [ ] Choosing a **different** folder (the primary case) copies to `{destPrefix}{name}` (file) or `{destPrefix}{name}/` (folder subtree), keeping the original name; choosing the **current parent** triggers the FR-003 auto-number flow
- [ ] Destination collisions (other than the same-folder case) trigger the FR-005 prompt (per-item for a multi-select copy)
- [ ] On success, **only the destination-prefix** listing is invalidated (the source listing is unchanged — unlike move, which invalidates both)
- [ ] A multi-select copy reports an aggregated `CopySummary` (`copiedCount` + per-item `errors`), mirroring SPEC-019's `MoveSummary`

### FR-006: Shared Destination Picker (Move + Copy)

#### Description:

Extract one reusable destination-folder picker used by both Move (SPEC-019) and Copy, instead of two parallel implementations.

#### Acceptance Criteria:

- [ ] A `DestinationPicker` component is extracted from SPEC-019's `MoveDialog`: it lists folders within the user's own space, excludes invalid targets (the item's own subtree for a folder op; the protected `athenaresults/` folder), and returns the chosen destination prefix
- [ ] SPEC-019's `MoveDialog` is **refactored** to consume `DestinationPicker` (no behavior change to move); Copy uses the same component. A note records this refactor of the completed SPEC-019 UI
- [ ] `DestinationPicker` is added to `apps/portal/info/component-inventory/INDEX.md` as a shared file-browser component
- [ ] Existing move tests still pass after the refactor; new copy tests use the same picker

### FR-005: Collision Handling (Warn and Confirm)

#### Description:

A copy never silently overwrites an existing destination object (reuses SPEC-019's flow).

#### Acceptance Criteria:

- [ ] Before writing, the destination key is HEAD-checked (`objectExists`, SPEC-016); if present, the user chooses **Overwrite** or **Rename** (new name) via the existing `CollisionPrompt`
- [ ] For a folder copy, the check is applied per destination key; the user is told how many destination objects already exist and confirms once (Overwrite all) or cancels
- [ ] Cancelling performs no copy
- [ ] The collision branches are unit-tested

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type CopyResult = {
  copied: string[];
  errors: { key: string; message: string }[];
};
```

```ts
// src/features/file-browser/useCopy.ts (additions)
export type CopySummary = {
  copiedCount: number;
  errors: { item: string; message: string }[];
};
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (additions)
// copyObject already exists (SPEC-019); copyFolder is new:
copyFolder(params: {
  bucket: string;
  sourcePrefix: string;
  destPrefix: string;
  username: string;
  overwrite?: boolean;
  onProgress?: (done: number, total: number) => void;
}): Promise<ServiceResult<CopyResult>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + copyFolder (copyObject already present)
├── fileBrowser.service.test.ts   ← + folder-copy / no-delete / collision tests
├── useCopy.ts                    ← NEW: copy mutations + dest invalidation + progress + same-folder auto-number
├── useCopy.test.ts               ← NEW
├── DestinationPicker.tsx         ← NEW: shared folder picker (extracted from MoveDialog; used by Move + Copy)
├── CopyDialog.tsx                ← NEW: thin wrapper over DestinationPicker for the copy flow
├── MoveDialog.tsx                ← refactored to consume DestinationPicker (SPEC-019; no behavior change)
└── FileBrowser.tsx               ← + Copy action (row + selection bar)
```

## Implementation Phases

### Phase 1: Copy service + recursion + same-folder suffix + collision

- `copyFolder`, the no-delete invariant, into-itself guard, FR-003 suffix logic, collision checks (FR-001, FR-002, FR-003, FR-005 service parts)

#### Checkpoint

Unit tests pass: single copy leaves the source and creates the destination; recursive folder copy over a mocked multi-page listing duplicates the subtree with the source intact; copy-into-itself is prevented; same-folder copy yields `{name} copy` (then ` copy 2`); collision branches (Overwrite/Rename/Cancel) behave; marker rejection holds. `npm run lint` clean.

### Phase 2: Copy UI

- Copy row + selection-bar actions, destination picker (reuse/generalize `MoveDialog`), same-folder suffix prompt, multi-select copy, progress, destination-only invalidation (FR-004, FR-003/FR-005 UI)

#### Checkpoint

Signed in: copying a file into another folder duplicates it (original stays); copying a file in place produces `… copy`; copying a folder duplicates its whole subtree (source unchanged); copying a folder into itself is prevented; a destination collision prompts Overwrite/Rename; `athenaresults/` is not offered as a destination; a forced mid-operation failure reports which keys failed and leaves a partial duplicate (no source change). Deployed app verified with a real user.

## Open Questions

- [x] **Resolved (2026-06-17, user decision):** same-folder copies append a **number at the end of the name** — `{name} (1)`, `{name} (2)`, … (file: before the extension; folder: on the leaf). Copying to a **different** folder is the primary case and keeps the original name (FR-003/FR-004).
- [x] **Resolved (2026-06-17, user decision):** **one shared `DestinationPicker`** component serves both Move and Copy; SPEC-019's `MoveDialog` is refactored to use it (FR-006).
- [x] **Resolved (2026-06-17):** copy is **additive** — never deletes the source; only the **destination** listing is invalidated. Reuses SPEC-019's `copyObject`, collision flow, and destination picker; folder copy is recursive and best-effort (partial failure leaves a partial duplicate, no rollback), mirroring `moveFolder` minus the deletes.
- [x] **Resolved (2026-06-17):** copying **into** `athenaresults/` is disallowed (UI-locked, SPEC-032); copying **out of** it is allowed (`GetObject` permitted).
