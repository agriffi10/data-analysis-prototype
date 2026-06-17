# Spec: Upload Queue — multi-file, concurrency, cancel

**ID:** SPEC-020
**Status:** Completed
**Last Updated:** 2026-06-17
**Depends On:** SPEC-013 (portal role + bucket), SPEC-015 (data foundation), SPEC-016 (`uploadFile` — managed/auto-multipart upload with `onProgress` + `signal`)

## Overview

SPEC-016 made a **single** upload a complete, correct operation: managed by
`@aws-sdk/lib-storage` `Upload`, automatically multipart above the 5 MiB part-size
threshold, reporting progress, with the multipart IAM actions and an
abort-incomplete lifecycle rule already in place. This spec turns uploading into
a proper **multi-file experience**: a queue with bounded file concurrency,
per-file progress, and the ability to **cancel** an in-flight upload.

This spec adds **no new S3 or IAM capability** — `uploadFile` from SPEC-016
already accepts `onProgress` and an `AbortSignal`, the multipart actions are
already granted, and the lifecycle rule already sweeps up aborted parts. SPEC-020
is purely client-side state + UI on top of that service.

## Scope

### In Scope

- Multi-file upload **queue**: selecting/dropping multiple files enqueues them
- Bounded **file concurrency** (default 3 files at once; the rest wait queued)
- Per-file **progress** (%, from SPEC-016's `onProgress`), **status**, and a progress bar
- Per-file **cancel** that aborts just that upload via the `AbortSignal` passed to `uploadFile` (the `Upload` aborts its multipart upload; no orphaned parts)
- Dismiss a completed / failed / cancelled item from the queue
- Per-file collision handling (warn-and-confirm, reusing SPEC-016) before each file starts
- Listing invalidation as each upload completes, so finished files appear
- Non-blocking: the user can keep browsing while uploads run
- Multi-file `UploadDropzone` (upgraded from SPEC-016's single-file dropzone)

### Out of Scope

- The multipart **engine**, progress reporting, multipart **IAM**, and the abort-incomplete **lifecycle rule** — all delivered in **SPEC-016**
- Resumable uploads across page reloads / browser restarts (multipart state is in-memory only)
- Recursive directory (folder) upload from the OS
- Download of large files (already handled by the presigned URL in SPEC-015 — no size limit there)
- Server-side virus scanning or post-processing (no backend)

---

## Functional Requirements

### FR-001: Upload Queue State + Concurrency

#### Description:

A client-side queue manages multiple uploads with a small concurrency limit.

#### Acceptance Criteria:

- [ ] An upload-queue context (`UploadQueueProvider`, Context + `useReducer`) holds the list of `UploadItem`s and drives them through `queued → uploading → done | failed | cancelled`
- [ ] Selecting or dropping multiple files enqueues one `UploadItem` per file (id is index/name-based — **no `Math.random` in shared code**)
- [ ] At most `UPLOAD_CONCURRENCY` (default 3) files upload at once; the rest stay `queued` until a slot frees
- [ ] Each item uploads via SPEC-016's `uploadFile`, wiring `onProgress` into the item's `loaded`/`total`
- [ ] As each upload reaches `done`, the current prefix's listing is invalidated so the finished file appears
- [ ] The reducer transitions and the concurrency gate are unit-tested

### FR-002: Per-File Cancel (Abort)

#### Description:

A user can cancel an upload that is queued or in flight.

#### Acceptance Criteria:

- [ ] Each in-flight item has a Cancel control that aborts **just that upload** via an `AbortController` whose `signal` was passed to `uploadFile`
- [ ] On cancel, the `Upload` aborts its multipart upload (no orphaned parts billed) and the item moves to `cancelled`; no listed object remains for a cancelled upload
- [ ] Cancelling a still-`queued` item removes it without starting; cancelling does not disturb other items
- [ ] A completed / failed / cancelled item can be dismissed from the queue
- [ ] The abort path is unit-tested (with `lib-storage` / the service mocked)

### FR-003: Upload Queue UI

#### Description:

Users see and manage their uploads in a queue panel.

#### Acceptance Criteria:

- [ ] The queue panel shows each file's name, size, status, and a progress bar (% from `loaded/total`)
- [ ] A per-file collision prompt (SPEC-016 warn-and-confirm) appears before that file starts; cancelling it removes the file from the queue
- [ ] The panel is non-blocking — the user can still browse and navigate while uploads run
- [ ] Files larger than `MAX_UPLOAD_BYTES` (SPEC-016) are rejected on enqueue with the limit message and never enter the active queue

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

export const UPLOAD_CONCURRENCY = 3; // files in flight at once

// Size cap + part size live in fileBrowser.types.ts (SPEC-016):
//   MAX_UPLOAD_BYTES, MULTIPART_PART_SIZE
```

---

## API / Interface Contract

No new service function. The queue calls SPEC-016's:

```ts
uploadFile(params: {
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

None new (`VITE_MAX_UPLOAD_BYTES` was added in SPEC-016).

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── upload.types.ts                  ← NEW: UploadItem, UploadStatus, UPLOAD_CONCURRENCY
├── uploadQueueContext.ts            ← NEW
├── UploadQueueProvider.tsx          ← NEW: queue state + concurrency gate
├── UploadQueueProvider.test.tsx     ← NEW
├── UploadQueuePanel.tsx             ← NEW: per-file progress / status / cancel / dismiss
└── UploadDropzone.tsx               ← updated: multi-file → enqueue
```

## Implementation Phases

### Phase 1: Queue state + concurrency + cancel

- `upload.types.ts`, `UploadQueueProvider` (reducer + concurrency gate calling SPEC-016 `uploadFile`), per-file abort (FR-001, FR-002)

#### Checkpoint

Unit tests pass for queue transitions, the concurrency gate (≤ 3 in flight), and the abort path. `npm run lint` clean.

### Phase 2: Queue UI + dropzone

- `UploadQueuePanel` (progress/status/cancel/dismiss), multi-file `UploadDropzone`, per-file collision prompt, listing invalidation per completion (FR-003)

#### Checkpoint

Signed in: dropping several files queues them and they upload with bounded concurrency and visible per-file progress; cancelling an in-flight upload stops it and leaves no listed object; each finished file appears via listing invalidation; browsing stays responsive during uploads; `npm run test` and `npm run lint` pass. Deployed app verified with multiple/large files.

## Open Questions

None — all resolved before drafting:
- Multipart engine, progress, IAM, and the abort lifecycle rule are **SPEC-016**; this spec is queue + concurrency + cancel only.
- File concurrency **default 3**; per-file cancel via `AbortSignal` → `uploadFile` → `Upload.abort()`.
- Queue/UI state = **React Context + `useReducer`** (UI state), per the state-management decision.
```
