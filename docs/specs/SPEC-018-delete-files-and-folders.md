# Spec: Delete Files and Folders (single + multi-select, recursive)

**ID:** SPEC-018
**Status:** Draft
**Last Updated:** 2026-06-11
**Depends On:** SPEC-013 (`s3:DeleteObject` + marker IAM deny), SPEC-014 (service-layer marker guard), SPEC-015 (data foundation)

## Overview

Let users delete their files and folders. Deletion is destructive and there is
no versioning or recycle bin (SPEC-010 disabled versioning), so every delete is
confirmed and irreversible. Files and folders can be deleted, individually or in
a multi-select batch. Deleting a folder recursively removes every object under
its prefix, batched within S3's 1,000-key `DeleteObjects` limit. The
`DO_NOT_DELETE.txt` prefix marker is protected on three levels — hidden from the
UI, rejected by the service layer (SPEC-014 FR-003), and denied by IAM (SPEC-013
FR-001) — so a user can never remove it through the portal.

## Scope

### In Scope

- Multi-select in the file browser (row checkboxes) backed by a Context + reducer UI-state store
- Delete a single file, multiple selected items, or a folder (recursively)
- Confirmation dialog stating exactly what (and how many objects) will be deleted, and that it is irreversible
- `DeleteObjects` batching (≤1,000 keys/request, paginated for larger folders)
- Recursive folder delete: list all keys under the prefix (all pages), then batch-delete
- Marker protection: never delete `{root}/DO_NOT_DELETE.txt`; surface partial failures
- Listing refetch (TanStack Query invalidation) after delete

### Out of Scope

- Trash / recycle bin / undo / restore (no versioning to restore from)
- Move/rename (SPEC-019)
- Cross-user or shared-space deletes (Bucket 2 is a separate arc)
- Any IAM change — `s3:DeleteObject` + the marker deny already exist (SPEC-013)

---

## Functional Requirements

### FR-001: Multi-Select State

#### Description:

The browser supports selecting multiple items for a bulk action.

#### Acceptance Criteria:

- [ ] A `SelectionProvider` (React Context + `useReducer`) tracks the set of selected keys/prefixes for the current view
- [ ] Per-row checkboxes toggle selection; a header checkbox selects/clears all loaded items; the count of selected items is shown
- [ ] Selection clears on prefix navigation and after a completed delete
- [ ] The hidden marker is never selectable
- [ ] Reducer logic is unit-tested (toggle, select-all, clear, navigate-clears)

### FR-002: Delete Service (files + batch)

#### Description:

The service deletes one or many objects, honoring the marker guard and S3 limits.

#### Acceptance Criteria:

- [ ] `deleteObjects({ bucket, keys })` uses `DeleteObjectsCommand`, chunking `keys` into batches of ≤1,000; returns `ServiceResult<{ deleted: string[]; errors: { key: string; message: string }[] }>`
- [ ] Any key equal to `{root}/DO_NOT_DELETE.txt` is refused before the request with a descriptive error (SPEC-014 FR-003 guard); it is never sent to S3
- [ ] Per-key errors returned by S3 are collected into `errors` (the call does not throw on partial failure)
- [ ] Credential-expiry triggers one transparent retry via `getS3Client(true)`
- [ ] Unit tests cover single delete, >1,000-key chunking, the marker guard, and partial-failure aggregation

### FR-003: Recursive Folder Delete

#### Description:

Deleting a folder removes everything beneath it.

#### Acceptance Criteria:

- [ ] `deleteFolder({ bucket, prefix })` lists **all** keys under `prefix` (paginating `ListObjectsV2` past 1,000) and deletes them via `deleteObjects`
- [ ] The operation reports total objects deleted and any per-key failures; a failure on some keys does not abort the rest
- [ ] If the listing under a folder is empty (just the folder marker object), that marker object is itself deleted so the folder disappears
- [ ] The user-root marker (`{root}/DO_NOT_DELETE.txt`) is excluded from any recursive delete (it only lives at the root, which is never itself a delete target)
- [ ] Unit-tested with a mocked multi-page listing

### FR-004: Confirmation + Result UX

#### Description:

Deletes are explicit and their outcome is visible.

#### Acceptance Criteria:

- [ ] A confirmation dialog precedes every delete, naming the item(s) and count (for a folder: "this folder and its N items") and warning the action cannot be undone
- [ ] Nothing is deleted unless the user confirms; cancel performs no request
- [ ] On success the listing invalidates and selection clears; a brief success indication shows the count removed
- [ ] On partial failure, the dialog/toast lists which items failed and why; successfully deleted items still disappear from the listing
- [ ] The marker is never offered for deletion in any path

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type DeleteResult = {
  deleted: string[];
  errors: { key: string; message: string }[];
};
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (additions)
deleteObjects(params: {
  bucket: string;
  keys: string[];
}): Promise<ServiceResult<DeleteResult>>;

deleteFolder(params: {
  bucket: string;
  prefix: string;
}): Promise<ServiceResult<DeleteResult>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + deleteObjects, deleteFolder
├── fileBrowser.service.test.ts   ← + delete/marker/recursive tests
├── selectionContext.ts           ← NEW: context object
├── SelectionProvider.tsx         ← NEW: reducer-backed provider
├── SelectionProvider.test.tsx    ← NEW
├── useDelete.ts                  ← NEW: delete mutations + invalidation
├── DeleteConfirmDialog.tsx       ← NEW
└── FileBrowser.tsx               ← + checkboxes, bulk delete bar, per-item delete
```

## Implementation Phases

### Phase 1: Selection state + delete service

- `SelectionProvider`/reducer (FR-001) and `deleteObjects`/`deleteFolder` with marker guard, chunking, recursion (FR-002, FR-003)

#### Checkpoint

Unit tests pass: selection reducer; single/batch/recursive delete; marker guard; >1,000-key chunking; partial-failure aggregation. `npm run lint` clean.

### Phase 2: UI — checkboxes, confirm, results

- Row/header checkboxes, bulk-action bar, confirmation dialog, success/partial-failure feedback, invalidation (FR-001 UI, FR-004)

#### Checkpoint

Signed in: selecting several files and confirming removes them and the listing updates; deleting a folder with nested files removes all of them; the marker never appears as deletable; cancelling deletes nothing.

## Open Questions

None — all resolved before drafting:
- No trash/undo (versioning is off); deletes are confirmed and irreversible.
- Folder delete is **recursive** (matches the locked "files + folders" scope).
- Marker is protected at UI + service (SPEC-014) + IAM (SPEC-013) layers.
