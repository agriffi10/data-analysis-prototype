# Spec: Multipart Upload (large files) + Upload Queue & Progress

**ID:** SPEC-020
**Status:** Draft
**Last Updated:** 2026-06-11
**Depends On:** SPEC-013 (portal role + bucket), SPEC-015 (data foundation), SPEC-016 (single-file upload UI it supersedes)

## Overview

Lift the 5 MB upload cap from SPEC-016 by uploading large files with S3 multipart
upload, and turn uploading into a proper multi-file experience: a queue with
per-file progress and the ability to cancel an in-flight upload. The AWS SDK's
managed `Upload` (`@aws-sdk/lib-storage`) handles part splitting, concurrency,
and progress events; cancelling aborts the multipart upload so no orphaned parts
are billed, and a bucket lifecycle rule sweeps up any incomplete uploads that
slip through. This spec also expands the portal role's IAM policy with the
multipart actions the single-object grants don't cover.

## Scope

### In Scope

- Multipart upload via `@aws-sdk/lib-storage` `Upload` (auto-multipart above the part-size threshold)
- Multi-file upload **queue** with per-file progress (%), status, and cancel (abort)
- Removal of SPEC-016's 5 MB hard cap; a configurable maximum upload size (default 5 GiB)
- IAM: add `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads`, `s3:ListMultipartUploadParts` to the SPEC-013 portal-role permission policy
- IaC: a bucket lifecycle rule on the user-space bucket aborting incomplete multipart uploads after 7 days; deploy-role permission for lifecycle configuration
- Collision handling per file (warn-and-confirm, reusing SPEC-016)
- Architecture doc + CLAUDE.md updates for the new IAM actions, lifecycle rule, and dependency

### Out of Scope

- Resumable uploads across page reloads / browser restarts (multipart state is in-memory only)
- Recursive directory (folder) upload from the OS
- Download of large files (already handled by the presigned URL in SPEC-015 — no size limit there)
- Server-side virus scanning or post-processing (no backend)

---

## Functional Requirements

### FR-001: IAM — Multipart Actions

#### Description:

The portal role must allow the multipart API calls the single-object grants miss.

#### Acceptance Criteria:

- [ ] `infra/modules/data/policies/portal-role-permissions.json.tftpl` (SPEC-013) is extended with `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads`, and `s3:ListMultipartUploadParts`, scoped to the same `{bucket}/${aws:PrincipalTag/username}/*` resource (and the bucket ARN for the list-uploads action) as the existing object actions
- [ ] `UploadPart`/`CompleteMultipartUpload`/`CreateMultipartUpload` continue to be covered by the existing `s3:PutObject` grant (documented in a comment — no separate action needed)
- [ ] `docs/architecture.md` Authorization Model policy snippet is updated to include these actions
- [ ] `tofu validate` + a `deploy-infra.yml` PR plan pass, showing only the policy change
- [ ] After apply, an `aws iam simulate-principal-policy` (or a real large upload from the app) confirms multipart succeeds within the user's prefix and is denied outside it

### FR-002: Incomplete-Upload Lifecycle Rule

#### Description:

Aborted or abandoned multipart uploads must not accumulate as billable orphaned parts.

#### Acceptance Criteria:

- [ ] `infra/modules/data/s3.tf` adds a lifecycle configuration to the user-space bucket with an `abort_incomplete_multipart_upload` of 7 days
- [ ] The deploy-role policy (`infra/modules/base/policies/`) is extended with `s3:PutLifecycleConfiguration` and `s3:GetLifecycleConfiguration` scoped to the user-space bucket ARN (SPEC-010 did not include these)
- [ ] `aws s3api get-bucket-lifecycle-configuration` after apply returns the expected rule
- [ ] This is noted in `docs/architecture.md` (SPEC-010 explicitly deferred lifecycle rules; this is the first one)

### FR-003: Multipart Upload Service

#### Description:

Upload any-size files using the SDK's managed multipart uploader.

#### Acceptance Criteria:

- [ ] `uploadLargeFile({ bucket, key, body, contentType, overwrite, onProgress, signal })` uses `@aws-sdk/lib-storage` `Upload` with the client from `getS3Client()`; `partSize` 5 MiB, `queueSize` (concurrency) 4
- [ ] Files at or below the part size still upload correctly (single part) — this path supersedes SPEC-016's `uploadFile` for the upload UI
- [ ] `onProgress` reports loaded/total so the UI can show a percentage
- [ ] An `AbortSignal` cancels the upload; on cancel the `Upload` aborts the multipart upload (no orphaned parts) and the service returns a cancelled `ServiceResult` error (not a throw)
- [ ] Files larger than the configured maximum (default 5 GiB, `VITE_MAX_UPLOAD_BYTES`) are rejected client-side before starting
- [ ] Collision is resolved before starting via the SPEC-016 warn-and-confirm path (HEAD-check unless `overwrite`)
- [ ] Credential-expiry mid-upload: the `Upload` surfaces the error; the service attempts one restart with `getS3Client(true)` for not-yet-started uploads and otherwise returns a clear error
- [ ] Unit tests cover progress reporting, the size cap, the abort path, and collision deferral (with `lib-storage` mocked)

### FR-004: Upload Queue UI

#### Description:

Users add multiple files and watch them upload.

#### Acceptance Criteria:

- [ ] Selecting/dropping multiple files enqueues them; the queue shows each file's name, size, status (queued / uploading / done / failed / cancelled), and a progress bar
- [ ] Uploads run with a small concurrency limit (e.g. 3 files at once); the rest wait queued
- [ ] Each in-flight item has a Cancel control that aborts just that upload; a completed/failed item can be dismissed
- [ ] As each upload completes, the current prefix's listing invalidates so finished files appear
- [ ] A per-file collision prompt (SPEC-016) appears before that file starts; cancelling it removes the file from the queue
- [ ] The queue is non-blocking — the user can still browse while uploads run

---

## Data Model

```ts
// src/features/file-browser/upload.types.ts (NEW)

export type UploadStatus =
  | 'queued' | 'uploading' | 'done' | 'failed' | 'cancelled';

export type UploadItem = {
  id: string;          // client-generated (index/name based — no Math.random in shared code)
  file: File;
  key: string;         // destination key
  status: UploadStatus;
  loaded: number;      // bytes uploaded
  total: number;       // file size
  error?: string;
};

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024; // 5 GiB default (VITE override)
export const MULTIPART_PART_SIZE = 5 * 1024 * 1024;     // 5 MiB
export const UPLOAD_CONCURRENCY = 3;                    // files in flight
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (addition)
uploadLargeFile(params: {
  bucket: string;
  key: string;
  body: File | Blob;
  contentType: string;
  overwrite?: boolean;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}): Promise<ServiceResult<{ key: string }>>;
```

## Environment Variables

Add to `.env.example`:
```
# Maximum single-file upload size in bytes (default 5368709120 = 5 GiB)
VITE_MAX_UPLOAD_BYTES=5368709120
```

## File & Folder Structure

```
infra/modules/data/
├── s3.tf                                  ← + abort-incomplete-multipart lifecycle rule
└── policies/portal-role-permissions.json.tftpl  ← + multipart actions

infra/modules/base/policies/               ← + s3:Put/GetLifecycleConfiguration (deploy role)

apps/portal/src/features/file-browser/
├── fileBrowser.service.ts                 ← + uploadLargeFile
├── fileBrowser.service.test.ts            ← + multipart/abort/progress tests
├── upload.types.ts                        ← NEW
├── uploadQueueContext.ts                  ← NEW
├── UploadQueueProvider.tsx                ← NEW: queue state + concurrency
├── UploadQueueProvider.test.tsx           ← NEW
├── UploadQueuePanel.tsx                   ← NEW: progress UI
└── UploadDropzone.tsx                     ← updated: multi-file → queue
```

## Implementation Phases

### Phase 1: IaC — IAM actions + lifecycle rule

- FR-001, FR-002 (and the deploy-role + architecture-doc updates)

#### Checkpoint

`deploy-infra.yml` PR plan shows the policy + lifecycle change and nothing else. After apply: `get-bucket-lifecycle-configuration` returns the abort rule; a large upload via a real STS session (or `simulate-principal-policy`) is allowed in-prefix and denied out-of-prefix.

### Phase 2: Multipart service + queue UI

- `@aws-sdk/lib-storage`, `uploadLargeFile`, the upload-queue provider and panel, multi-file dropzone, cancel/progress, collision per file (FR-003, FR-004)

#### Checkpoint

Signed in: uploading a >5 MB file succeeds with a visible progress bar; multiple files queue and upload with bounded concurrency; cancelling an in-flight upload stops it and leaves no listed object; each finished file appears via listing invalidation; `npm run test` and `npm run lint` pass. Deployed app verified with a real large file.

## Open Questions

None — all resolved before drafting:
- Multipart via **`@aws-sdk/lib-storage` `Upload`** (managed parts/concurrency/progress/abort).
- Max upload size configurable, **default 5 GiB**; part size 5 MiB; file concurrency 3.
- Incomplete uploads swept by a **7-day abort lifecycle rule** (first lifecycle rule on the data bucket; SPEC-010 deferred these).
