---
type: Spec
id: SPEC-019
title: "Move & Rename (files and folders, recursive)"
description: "Lets users move and rename files and folders recursively, implemented as copy-then-delete with safe partial-failure handling and a warn-and-confirm prompt for name collisions."
spec_status: Completed
depends_on: [SPEC-013, SPEC-014, SPEC-015, SPEC-018]
arc: file-operations
arc_order: 5
---

**Dependency notes:** SPEC-013 (`s3:GetObject` + `s3:PutObject` + `s3:DeleteObject` on own prefix), SPEC-014 (marker), SPEC-015 (data foundation), SPEC-018 (selection state)
## Overview

Present **move** and **rename** as first-class filesystem actions, even though
S3 has neither. Both are implemented under the hood as **copy-then-delete**:
`CopyObject` to the destination key, then delete the source only after the copy
succeeds. Rename is simply a move within the same parent folder. Files and
folders are both supported; a folder move/rename copies and deletes every object
under its prefix recursively. Because this is non-atomic, the spec defines exactly
what happens on partial failure (sources whose copy failed are never deleted) and
how name collisions are handled (warn-and-confirm: overwrite or pick a new name).

## Scope

### In Scope

- Rename a file or folder (move within the same parent under a new leaf name)
- Move a file or folder to a different destination folder within the user's own space
- `copyObject` service (same-bucket `CopyObject`), and a `moveObject` = copy-then-delete-source
- Recursive folder move/rename: enumerate all keys under the source prefix, copy each to the destination prefix, then delete the originals
- Collision handling at the destination: HEAD-check, warn-and-confirm (Overwrite or Rename)
- Partial-failure semantics and user-visible reporting
- Multi-select move (reusing the SPEC-018 selection store)
- Listing refetch (TanStack Query invalidation) for both source and destination prefixes

### Out of Scope

- Cross-user or cross-bucket (shared-space) moves — Bucket 2 is a separate arc
- Drag-and-drop move UI — moves are driven by an action menu + destination picker here (drag-and-drop is a later UX-polish spec)
- Server-side atomic rename (impossible on S3) — non-atomic copy+delete is the model
- Any IAM change — copy uses the existing `s3:GetObject` (source) + `s3:PutObject` (destination), both within the user's own prefix

---

## Functional Requirements

### FR-001: Copy/Move Service (single object)

#### Description:

The primitive both actions build on: copy an object, then delete the source.

#### Acceptance Criteria:

- [ ] `copyObject({ bucket, sourceKey, destKey })` issues `CopyObjectCommand` with `CopySource` = `bucket/sourceKey` (URL-encoded); returns `ServiceResult<{ destKey: string }>`
- [ ] `moveObject({ bucket, sourceKey, destKey })` calls `copyObject`, and **only on success** issues `DeleteObject` on `sourceKey`; if the copy fails, the source is left intact and an error is returned
- [ ] A `sourceKey === destKey` request is a no-op success (renaming to the same name)
- [ ] The user-root marker (`{root}/DO_NOT_DELETE.txt`) is never a valid source or destination (rejected with a descriptive error)
- [ ] Credential-expiry triggers one transparent retry via `getS3Client(true)`
- [ ] Unit tests cover copy, move (delete-after-copy), copy-failure-leaves-source, and same-key no-op

### FR-002: Rename

#### Description:

Rename changes an item's leaf name within its current parent.

#### Acceptance Criteria:

- [ ] Renaming a **file** moves `{parent}{old}` → `{parent}{new}` via `moveObject`
- [ ] Renaming a **folder** moves every key under `{parent}{old}/` → `{parent}{new}/` (FR-004 recursion)
- [ ] The new name is validated with the same rules as create-folder/upload (non-empty trimmed, no `/`, no leading/trailing whitespace, no control chars)
- [ ] A destination-name collision triggers the FR-005 prompt
- [ ] The user's root folder (their username prefix) cannot be renamed (the action is not offered at the root)

### FR-003: Move

#### Description:

Move relocates an item under a different destination folder in the user's space.

#### Acceptance Criteria:

- [ ] A destination-folder picker lists only folders within the user's own space; the current parent and (for a folder) the item's own subtree are not selectable as destinations (no moving a folder into itself)
- [ ] Moving a file places it at `{destPrefix}{name}`; moving a folder places its subtree under `{destPrefix}{name}/` (FR-004 recursion)
- [ ] Destination collisions trigger the FR-005 prompt (per-item for a multi-select move)
- [ ] On success both the source-prefix and destination-prefix listings are invalidated

### FR-004: Recursive Folder Move/Rename + Partial Failure

#### Description:

Folder operations process every contained object and degrade safely.

#### Acceptance Criteria:

- [ ] `moveFolder({ bucket, sourcePrefix, destPrefix })` lists **all** keys under `sourcePrefix` (paginating past 1,000), computing each destination key by replacing the `sourcePrefix` portion with `destPrefix`
- [ ] Each object is copied then its source deleted; the result reports `{ moved: string[]; errors: { key: string; message: string }[] }`
- [ ] A copy that fails for one key does **not** delete that source and does **not** abort the remaining keys
- [ ] After a fully successful folder move, no objects remain under the old prefix (verified in tests with a mocked multi-page listing)
- [ ] Progress (objects processed / total) is surfaced to the UI for large folders

### FR-005: Collision Handling (Warn and Confirm)

#### Description:

A move/rename never silently overwrites an existing destination object.

#### Acceptance Criteria:

- [ ] Before writing, the destination key is HEAD-checked (`objectExists`, SPEC-016); if present, the user chooses **Overwrite** or **Rename** (new name)
- [ ] For a folder operation, the check is applied per destination key; the user is told how many destination objects already exist and confirms once (Overwrite all) or cancels
- [ ] Cancelling performs no copy and no delete
- [ ] The collision branches are unit-tested

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type MoveResult = {
  moved: string[];
  errors: { key: string; message: string }[];
};
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (additions)
copyObject(params: { bucket: string; sourceKey: string; destKey: string }):
  Promise<ServiceResult<{ destKey: string }>>;

moveObject(params: { bucket: string; sourceKey: string; destKey: string }):
  Promise<ServiceResult<{ destKey: string }>>;

moveFolder(params: { bucket: string; sourcePrefix: string; destPrefix: string }):
  Promise<ServiceResult<MoveResult>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + copyObject, moveObject, moveFolder
├── fileBrowser.service.test.ts   ← + copy/move/recursive/collision tests
├── useMove.ts                    ← NEW: move/rename mutations + invalidation + progress
├── RenameDialog.tsx              ← NEW
├── MoveDialog.tsx                ← NEW: destination-folder picker
└── FileBrowser.tsx               ← + rename + move actions (row + bulk)
```

## Implementation Phases

### Phase 1: Copy/move service + recursion + collision

- `copyObject`, `moveObject`, `moveFolder`, collision checks, partial-failure semantics (FR-001, FR-004, FR-005 service parts)

#### Checkpoint

Unit tests pass: single move (copy then delete), copy-failure leaves source, recursive folder move over a mocked multi-page listing, same-key no-op, marker rejection, collision branches. `npm run lint` clean.

### Phase 2: Rename + move UI

- Rename dialog, move dialog with destination picker, multi-select move, progress, dual-prefix invalidation (FR-002, FR-003, FR-005 UI)

#### Checkpoint

Signed in: renaming a file and a folder works and the old name disappears; moving items into another folder relocates them (source emptied); moving a folder into itself is prevented; a destination collision prompts Overwrite/Rename; a forced mid-operation failure leaves the un-copied source intact and reports it. Deployed app verified with a real user.

## Open Questions

None — all resolved before drafting:
- Move/rename are **presented as first-class** but implemented as copy-then-delete (per your direction).
- Folder ops are **recursive** (files + folders); partial-failure rule = never delete a source whose copy failed.
- Collisions = **warn and confirm**; no drag-and-drop in this spec (action menu + picker).
