// Feature-scoped types for the upload queue (SPEC-020).
//
// SPEC-020 builds a multi-file upload *queue* on top of SPEC-016's single-file
// `uploadFile` (managed lib-storage upload — single request ≤5 MiB, auto-multipart
// above). It adds no new S3/IAM capability: just client-side queue state, bounded
// file concurrency, per-file progress/status, and per-file cancel.

export type UploadStatus =
  // queued → uploading → done | failed | cancelled, plus `collision` (a pause
  // awaiting the user's Overwrite/Rename decision before the file is written —
  // SPEC-016 warn-and-confirm, FR-003). `collision` is the only non-`queued`
  // state the concurrency gate must NOT auto-start.
  'queued' | 'uploading' | 'collision' | 'done' | 'failed' | 'cancelled';

export type UploadItem = {
  id: string; // client-generated, index/name based — no Math.random in shared code
  file: File;
  key: string; // destination key (prefix captured at enqueue time, so navigation
  //              never re-targets an in-flight upload)
  status: UploadStatus;
  loaded: number; // bytes uploaded so far
  total: number; // file size in bytes
  // Whether the next upload attempt should overwrite an existing object. Set when
  // the user resolves a collision with Overwrite; otherwise the SPEC-016 collision
  // guard HEAD-checks and pauses the item in `collision`.
  overwrite: boolean;
  error?: string; // failure / rejection reason (shown in the queue panel)
};

// Files in flight at once; the rest stay `queued` until a slot frees (FR-001).
export const UPLOAD_CONCURRENCY = 3;

// Terminal states — eligible for dismiss / clear-finished (never re-started).
export const TERMINAL_STATUSES: ReadonlySet<UploadStatus> = new Set<UploadStatus>(['done', 'failed', 'cancelled']);
