# Spec: File Upload (single, ≤5 MB) + Create Folder

**ID:** SPEC-016
**Status:** Draft
**Last Updated:** 2026-06-11
**Depends On:** SPEC-013 (write access to own prefix), SPEC-015 (TanStack Query data foundation)

## Overview

Give users the first write operations of the filesystem experience: uploading a
single file into the folder they're viewing, and creating new (empty) folders.
Because S3 has no folders, a folder is created as a zero-byte marker object whose
key ends in `/`. Uploads are capped at 5 MB in this spec; larger files arrive
with multipart upload in SPEC-020. Because the user-space bucket has versioning
off, writing over an existing name would destroy the previous object — so any
name collision triggers a **warn-and-confirm** prompt (overwrite or rename)
rather than silently overwriting.

## Scope

### In Scope

- Upload a **single** file (≤5 MB) into the current prefix via `PutObject`, with `Content-Type` derived from the file
- A file picker plus a drag-and-drop drop zone (single file)
- Create an empty folder (zero-byte object at `{prefix}{name}/`)
- Name-collision handling for both operations: HEAD-check, then warn-and-confirm (overwrite or choose a new name)
- Listing refetch (TanStack Query invalidation) after a successful write
- Client-side validation: size cap, folder-name rules, clear error messages

### Out of Scope

- Files larger than 5 MB / multipart upload, upload progress bars, and multi-file upload **queues** (all SPEC-020)
- Recursive directory (folder) upload from the OS
- Move/rename (SPEC-019), delete (SPEC-018), metadata panel (SPEC-017)
- Editing an object's `Content-Type` or metadata after upload
- Any IAM change — `s3:PutObject` from SPEC-013 already covers both operations

---

## Functional Requirements

### FR-001: Single-File Upload

#### Description:

A user uploads one file into the folder currently shown; it appears in the listing on success.

#### Acceptance Criteria:

- [ ] `uploadFile({ bucket, key, body, contentType, overwrite })` issues `PutObject` with `Body` and `ContentType`, using the client from `getS3Client()`; returns `ServiceResult<{ key: string }>`
- [ ] The destination key is `currentPrefix + file.name`; `contentType` is `file.type` or `application/octet-stream` when the browser provides none
- [ ] Files larger than **5 MB** (5 \* 1024 \* 1024 bytes) are rejected client-side before any request, with a message naming the limit and pointing to large-file support (SPEC-020)
- [ ] On success, the listing for `currentPrefix` is invalidated and refetched so the new file shows without a manual refresh
- [ ] Credential-expiry mid-upload triggers one transparent retry via `getS3Client(true)` before surfacing an error
- [ ] Both a file-picker button and a drag-and-drop drop zone trigger the same upload path

### FR-002: Name-Collision Handling (Warn and Confirm)

#### Description:

Writing over an existing object is prevented unless the user explicitly confirms.

#### Acceptance Criteria:

- [ ] `objectExists({ bucket, key })` issues `HeadObject` and returns `ServiceResult<boolean>` (NotFound/404 → `false`, not an error)
- [ ] Upload and create-folder both call `objectExists` first; when the target exists, the user is prompted with two choices: **Overwrite** or **Rename** (enter a new name)
- [ ] Choosing Overwrite re-issues the write with `overwrite: true` (skips the existence check); choosing Rename re-runs the collision check against the new name
- [ ] No write occurs while the prompt is open; cancelling the prompt performs no write
- [ ] The collision check and both branches are unit-tested

### FR-003: Create Folder

#### Description:

A user creates a new, empty folder in the current prefix.

#### Acceptance Criteria:

- [ ] `createFolder({ bucket, prefix, name })` issues `PutObject` of a zero-byte body at key `{prefix}{name}/` with `Content-Type` `application/x-directory`; returns `ServiceResult<{ prefix: string }>`
- [ ] Folder name validation (client-side, before any request): non-empty after trimming, no `/`, no leading/trailing whitespace, no control characters; invalid names show a specific error and issue no request
- [ ] An existing folder of the same name triggers the FR-002 collision prompt (Overwrite is a no-op-safe re-put; Rename asks for a new name)
- [ ] On success the new (empty) folder appears in the listing via query invalidation
- [ ] The new folder is navigable and shows the empty state when opened

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type UploadResult = { key: string };
export type CreateFolderResult = { prefix: string };

export const MAX_SINGLE_UPLOAD_BYTES = 5 * 1024 * 1024; // 5 MB (SPEC-020 lifts this)
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (additions)
objectExists(params: { bucket: string; key: string }): Promise<ServiceResult<boolean>>;

uploadFile(params: {
  bucket: string;
  key: string;
  body: Blob | File;
  contentType: string;
  overwrite?: boolean; // default false → caller must resolve collisions first
}): Promise<ServiceResult<UploadResult>>;

createFolder(params: {
  bucket: string;
  prefix: string;
  name: string;
  overwrite?: boolean;
}): Promise<ServiceResult<CreateFolderResult>>;
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + objectExists, uploadFile, createFolder
├── fileBrowser.service.test.ts   ← + upload/folder/collision tests
├── useFileUpload.ts              ← NEW: upload + create-folder mutations (TanStack useMutation)
├── useFileUpload.test.ts         ← NEW
├── UploadDropzone.tsx            ← NEW: picker + drag-and-drop
├── CreateFolderDialog.tsx        ← NEW
├── CollisionPrompt.tsx           ← NEW: overwrite / rename
└── FileBrowser.tsx               ← + upload + new-folder entry points
```

## Implementation Phases

### Phase 1: Service layer + collision logic

- `objectExists`, `uploadFile`, `createFolder`, with collision-aware mutations (FR-001 service parts, FR-002, FR-003 service parts)

#### Checkpoint

Unit tests pass for upload, create-folder, the 5 MB cap, and both collision branches. `npm run lint` clean.

### Phase 2: UI (dropzone, dialogs, wiring)

- Drop zone + picker, create-folder dialog, collision prompt; query invalidation on success (FR-001/003 UI)

#### Checkpoint

Signed in: dragging a ≤5 MB file uploads it and it appears without manual refresh; a >5 MB file is rejected with the limit message; creating a folder shows it and it opens empty; uploading a name that exists prompts Overwrite/Rename and neither path loses data unexpectedly.

## Open Questions

None — all resolved before drafting:
- Collision policy = **warn and confirm** (Overwrite or Rename), HEAD-checked.
- Single-file, ≤5 MB in this spec; multi-file queues, progress, and large files are **SPEC-020**.
- Folder = zero-byte `{name}/` object; folder-name rules locked in FR-003.
