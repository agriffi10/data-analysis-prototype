// Feature-scoped types for the multi-file upload queue: client-side queue
// state, bounded file concurrency, per-file progress/status, per-file cancel.

/**
 * queued → uploading → done | failed | cancelled, plus `collision` — a pause
 * awaiting the user's Overwrite/Rename decision before the file is written.
 * `collision` is the only non-`queued` state the concurrency gate must NOT
 * auto-start.
 */
export type UploadStatus = 'queued' | 'uploading' | 'collision' | 'done' | 'failed' | 'cancelled';

export type UploadItem = {
  /** Client-generated, index/name based — no Math.random in shared code. */
  id: string;
  file: File;
  /**
   * Destination bucket, captured at enqueue time — the queue is session-scoped
   * and spans connections, so each item carries its own bucket rather than
   * inheriting one from a provider prop.
   */
  bucket: string;
  /**
   * Destination key (prefix captured at enqueue time, so navigation never
   * re-targets an in-flight upload).
   */
  key: string;
  status: UploadStatus;
  /** Bytes uploaded so far. */
  loaded: number;
  /** File size in bytes. */
  total: number;
  /**
   * Whether the next upload attempt should overwrite an existing object. Set
   * when the user resolves a collision with Overwrite; otherwise the collision
   * guard HEAD-checks and pauses the item in `collision`.
   */
  overwrite: boolean;
  /** Failure / rejection reason (shown in the queue panel). */
  error?: string;
};

/** Files in flight at once; the rest stay `queued` until a slot frees. */
export const UPLOAD_CONCURRENCY = 3;

/** Terminal states — eligible for dismiss / clear-finished (never re-started). */
export const TERMINAL_STATUSES: ReadonlySet<UploadStatus> = new Set<UploadStatus>(['done', 'failed', 'cancelled']);
