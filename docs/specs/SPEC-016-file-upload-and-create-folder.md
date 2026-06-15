# Spec: File Upload (managed, auto-multipart + progress) + Create Folder

**ID:** SPEC-016
**Status:** Draft
**Last Updated:** 2026-06-15
**Depends On:** SPEC-013 (write access to own prefix), SPEC-015 (TanStack Query data foundation)

## Overview

Give users the first write operations of the filesystem experience: uploading a
single file into the folder they're viewing, and creating new (empty) folders.

Uploads go through the AWS SDK's managed uploader (`@aws-sdk/lib-storage`
`Upload`), which sends small files in a single `PutObject` and **automatically
switches to multipart upload above a part-size threshold** (5 MiB). The uploader
emits progress events, so the UI shows a **live percentage** of how much of the
file has uploaded. There is no 5 MB cap — uploads are bounded only by a
configurable maximum (default 5 GiB).

Because S3 has no folders, a folder is created as a zero-byte marker object whose
key ends in `/`. Because the user-space bucket has versioning off, writing over
an existing name would destroy the previous object — so any name collision
triggers a **warn-and-confirm** prompt (overwrite or rename) rather than silently
overwriting.

> **Scope split with SPEC-020:** the multipart *engine*, progress reporting, the
> multipart IAM actions, and the abort-incomplete lifecycle rule all live here —
> a single file upload is complete and correct on its own. SPEC-020 builds the
> multi-file **upload queue** (bounded concurrency + per-file cancel) on top of
> this spec's `uploadFile`; it adds no new S3/IAM capability.

## Scope

### In Scope

- Upload a **single** file into the current prefix via `@aws-sdk/lib-storage` `Upload` — single-request below the 5 MiB part-size threshold, **automatic multipart above it** — with `Content-Type` derived from the file
- **Live upload progress (percentage)** for the in-flight file, driven by the uploader's progress events
- A configurable maximum upload size (default 5 GiB, `VITE_MAX_UPLOAD_BYTES`); oversize files rejected client-side before any request
- A file picker plus a drag-and-drop drop zone (single file)
- Create an empty folder (zero-byte object at `{prefix}{name}/`)
- Name-collision handling for both operations: HEAD-check, then warn-and-confirm (overwrite or choose a new name)
- Listing refetch (TanStack Query invalidation) after a successful write
- **IAM**: extend the SPEC-013 portal-role policy with the multipart actions (`s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads`, `s3:ListMultipartUploadParts`) the single-object grants don't cover
- **IaC**: an `abort_incomplete_multipart_upload` lifecycle rule (7 days) on the user-space bucket so interrupted uploads never leave billable orphaned parts; deploy-role permission for lifecycle configuration
- `@aws-sdk/lib-storage` dependency
- Client-side validation: size cap, folder-name rules, clear error messages

### Out of Scope

- Multi-file upload **queue**, bounded concurrency, and per-file **cancel/abort UI** (all **SPEC-020**)
- Resumable uploads across page reloads (multipart state is in-memory only — SPEC-020)
- Recursive directory (folder) upload from the OS
- Move/rename (SPEC-019), delete (SPEC-018), metadata panel (SPEC-017)
- Editing an object's `Content-Type` or metadata after upload

---

## Functional Requirements

### FR-001: Single-File Upload (managed, auto-multipart)

#### Description:

A user uploads one file into the folder currently shown; it appears in the listing on success. Small files upload in one request; large files use multipart automatically.

#### Acceptance Criteria:

- [ ] `uploadFile({ bucket, key, body, contentType, overwrite, onProgress?, signal? })` uses `@aws-sdk/lib-storage` `Upload` with the client from `getS3Client()`; `partSize` 5 MiB, `queueSize` (part concurrency) 4; returns `ServiceResult<{ key: string }>`
- [ ] Files **at or below** the 5 MiB part size upload as a single part; files **above** it upload via automatic multipart — the caller does not choose; the threshold is `MULTIPART_PART_SIZE`
- [ ] The destination key is `currentPrefix + file.name`; `contentType` is `file.type` or `application/octet-stream` when the browser provides none
- [ ] Files larger than the configured maximum (`MAX_UPLOAD_BYTES`, default 5 GiB, overridable via `VITE_MAX_UPLOAD_BYTES`) are rejected client-side before any request, with a message naming the limit
- [ ] On a failed/aborted upload the `Upload` aborts its multipart upload so no orphaned parts are left (backed by the FR-005 IAM + FR-006 lifecycle safety net); the service returns a `ServiceResult` error and never throws
- [ ] On success, the listing for `currentPrefix` is invalidated and refetched so the new file shows without a manual refresh
- [ ] Credential-expiry before the upload starts triggers one transparent retry via `getS3Client(true)`; mid-flight expiry surfaces a clear error
- [ ] Both a file-picker button and a drag-and-drop drop zone trigger the same upload path

### FR-002: Live Upload Progress (percentage)

#### Description:

While a file uploads, the user sees how much of it has been sent, as a percentage — so a large multipart upload isn't an opaque wait.

#### Acceptance Criteria:

- [ ] `uploadFile` accepts an `onProgress(loaded: number, total: number)` callback and invokes it from the uploader's `httpUploadProgress` events
- [ ] The UI shows a progress indicator for the in-flight upload: a percentage (`Math.round(loaded / total * 100)`) and a progress bar; it reaches 100% only on completion
- [ ] `total` falls back to the file size when the event omits it; progress never displays `NaN`/`Infinity` (guard divide-by-zero for a 0-byte file → treat as 100%)
- [ ] The indicator clears on success and is replaced by an error message on failure
- [ ] The progress mapping (loaded/total → percent, with the zero-byte guard) is unit-tested

### FR-003: Name-Collision Handling (Warn and Confirm)

#### Description:

Writing over an existing object is prevented unless the user explicitly confirms.

#### Acceptance Criteria:

- [ ] `objectExists({ bucket, key })` issues `HeadObject` and returns `ServiceResult<boolean>` (NotFound/404 → `false`, not an error)
- [ ] Upload and create-folder both call `objectExists` first; when the target exists, the user is prompted with two choices: **Overwrite** or **Rename** (enter a new name)
- [ ] Choosing Overwrite re-issues the write with `overwrite: true` (skips the existence check); choosing Rename re-runs the collision check against the new name
- [ ] No write occurs while the prompt is open; cancelling the prompt performs no write
- [ ] The collision check and both branches are unit-tested

### FR-004: Create Folder

#### Description:

A user creates a new, empty folder in the current prefix.

#### Acceptance Criteria:

- [ ] `createFolder({ bucket, prefix, name })` issues `PutObject` of a zero-byte body at key `{prefix}{name}/` with `Content-Type` `application/x-directory`; returns `ServiceResult<{ prefix: string }>`
- [ ] Folder name validation (client-side, before any request): non-empty after trimming, no `/`, no leading/trailing whitespace, no control characters; invalid names show a specific error and issue no request
- [ ] An existing folder of the same name triggers the FR-003 collision prompt (Overwrite is a no-op-safe re-put; Rename asks for a new name)
- [ ] On success the new (empty) folder appears in the listing via query invalidation
- [ ] The new folder is navigable and shows the empty state when opened

### FR-005: IAM — Multipart Actions

#### Description:

Because uploads now use multipart, the portal role must allow the multipart API calls the single-object grants miss.

#### Acceptance Criteria:

- [ ] `infra/modules/data/policies/portal-role-permissions.json.tftpl` (SPEC-013) is extended with `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads`, and `s3:ListMultipartUploadParts`, scoped to the same `{bucket}/${aws:PrincipalTag/username}/*` resource (and the bucket ARN for the list-uploads action) as the existing object actions
- [ ] `CreateMultipartUpload`/`UploadPart`/`CompleteMultipartUpload` continue to be covered by the existing `s3:PutObject` grant (documented in a comment — no separate action needed)
- [ ] `docs/architecture.md` Authorization Model policy snippet is updated to include these actions
- [ ] `tofu validate` + a `deploy-infra.yml` PR plan pass, showing only the policy change
- [ ] After apply, an `aws iam simulate-principal-policy` (or a real large upload from the app) confirms multipart succeeds within the user's prefix and is denied outside it
- [ ] No deploy-role change needed for this FR — `iam:PutRolePolicy` was granted in SPEC-010/011 (the lifecycle permission is FR-006)

### FR-006: Incomplete-Upload Lifecycle Rule

#### Description:

Aborted or abandoned multipart uploads (e.g. the browser is closed mid-upload) must not accumulate as billable orphaned parts.

#### Acceptance Criteria:

- [ ] `infra/modules/data/s3.tf` adds a lifecycle configuration to the user-space bucket with an `abort_incomplete_multipart_upload` of 7 days (the first lifecycle rule on this bucket; SPEC-010 deferred these)
- [ ] The deploy-role policy (`infra/modules/base/policies/`) is extended with `s3:PutLifecycleConfiguration` and `s3:GetLifecycleConfiguration` scoped to the user-space bucket ARN (SPEC-010 did not include these)
- [ ] `aws s3api get-bucket-lifecycle-configuration` after apply returns the expected rule
- [ ] This is noted in `docs/architecture.md`

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type UploadResult = { key: string };
export type CreateFolderResult = { prefix: string };

// Files at/below the part size upload in one request; above it, lib-storage
// switches to automatic multipart. This is the "multipart threshold".
export const MULTIPART_PART_SIZE = 5 * 1024 * 1024; // 5 MiB
export const PART_CONCURRENCY = 4;                  // parts in flight per file

// Overall ceiling, configurable via VITE_MAX_UPLOAD_BYTES (SPEC-020 reuses this).
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024; // 5 GiB default
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
  overwrite?: boolean;            // default false → caller must resolve collisions first
  onProgress?: (loaded: number, total: number) => void; // FR-002
  signal?: AbortSignal;           // optional cancel; the cancel *UI* is SPEC-020
}): Promise<ServiceResult<UploadResult>>;

createFolder(params: {
  bucket: string;
  prefix: string;
  name: string;
  overwrite?: boolean;
}): Promise<ServiceResult<CreateFolderResult>>;
```

## Environment Variables

Add to `apps/portal/.env.example`:
```
# Maximum single-file upload size in bytes (default 5368709120 = 5 GiB)
VITE_MAX_UPLOAD_BYTES=5368709120
```

## File & Folder Structure

```
infra/modules/data/
├── s3.tf                                          ← + abort-incomplete-multipart lifecycle rule (FR-006)
└── policies/portal-role-permissions.json.tftpl    ← + multipart actions (FR-005)

infra/modules/base/policies/                       ← + s3:Put/GetLifecycleConfiguration (deploy role, FR-006)

apps/portal/src/features/file-browser/
├── fileBrowser.service.ts        ← + objectExists, uploadFile (lib-storage), createFolder
├── fileBrowser.service.test.ts   ← + upload/progress/folder/collision tests
├── fileBrowser.types.ts          ← + upload constants/types
├── useFileUpload.ts              ← NEW: upload + create-folder mutations (TanStack useMutation) + progress state
├── useFileUpload.test.ts         ← NEW
├── UploadDropzone.tsx            ← NEW: picker + drag-and-drop + progress indicator
├── CreateFolderDialog.tsx        ← NEW
├── CollisionPrompt.tsx           ← NEW: overwrite / rename
└── FileBrowser.tsx               ← + upload + new-folder entry points
```

## Implementation Phases

### Phase 1: IaC — multipart IAM + lifecycle rule

- FR-005, FR-006 (portal-role policy, lifecycle rule, deploy-role lifecycle perms, architecture-doc update)

#### Checkpoint

`deploy-infra.yml` PR plan shows the policy + lifecycle change and nothing else. After apply: `get-bucket-lifecycle-configuration` returns the abort rule; a multipart upload via a real STS session (or `simulate-principal-policy`) is allowed in-prefix and denied out-of-prefix.

### Phase 2: Service layer + collision logic

- `objectExists`, `uploadFile` (lib-storage `Upload` with `onProgress`), `createFolder`, with collision-aware mutations (FR-001 service parts, FR-002 progress mapping, FR-003, FR-004 service parts)

#### Checkpoint

Unit tests pass for upload (single-part + multipart paths with `lib-storage` mocked), the progress mapping, the size cap, create-folder, and both collision branches. `npm run lint` clean.

### Phase 3: UI (dropzone, progress, dialogs, wiring)

- Drop zone + picker, a progress indicator (% + bar), create-folder dialog, collision prompt; query invalidation on success (FR-001/002/004 UI)

#### Checkpoint

Signed in: dragging a file uploads it and it appears without manual refresh; a large (>5 MiB) file uploads via multipart with a **visible, advancing percentage**; an oversize (> max) file is rejected with the limit message; creating a folder shows it and it opens empty; uploading a name that exists prompts Overwrite/Rename and neither path loses data unexpectedly.

## Open Questions

None — all resolved before drafting:
- Upload engine = **`@aws-sdk/lib-storage` `Upload`** (managed parts/concurrency/progress; single request below the 5 MiB part size, **automatic multipart above it**).
- Progress = uploader `httpUploadProgress` → `onProgress(loaded, total)` → percentage in the UI.
- Max upload size configurable, **default 5 GiB** (`VITE_MAX_UPLOAD_BYTES`); part size 5 MiB.
- Collision policy = **warn and confirm** (Overwrite or Rename), HEAD-checked.
- Multi-file **queue** + per-file **cancel UI** are **SPEC-020** (built on this spec's `uploadFile`, which already accepts `onProgress` + `signal`).
- Folder = zero-byte `{name}/` object; folder-name rules locked in FR-004.
```
