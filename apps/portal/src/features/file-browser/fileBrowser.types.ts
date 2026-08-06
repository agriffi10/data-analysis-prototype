// Feature-scoped types for the file browser.

export type DownloadUrl = {
  /** Presigned GetObject URL. */
  url: string;
};

export type UploadResult = {key: string};
export type CreateFolderResult = {prefix: string};

/**
 * Outcome of a (possibly batched/recursive) delete. Partial failure is
 * reported, never thrown: `errors` includes the marker-guard refusal.
 */
export type DeleteResult = {
  /** Keys S3 confirmed removed. */
  deleted: string[];
  /** Per-key failures. `message` is technical (logged); the surface maps `code`. */
  errors: {key: string; message: string; code?: string}[];
};

/**
 * Outcome of a (possibly recursive) move. Move is non-atomic: a key whose copy
 * failed is left in place and reported in `errors`, never thrown.
 */
export type MoveResult = {
  /** Source keys copied to the destination and then deleted. */
  moved: string[];
  /** Per-key failures. `message` is technical (logged); the surface maps `code`. */
  errors: {key: string; message: string; code?: string}[];
};

/**
 * Outcome of a (possibly recursive) copy. Copy is additive (no source delete)
 * and best-effort: a failed key is recorded, never thrown, with no rollback — a
 * partial folder copy leaves a partial duplicate the user can delete.
 */
export type CopyResult = {
  /** Source keys duplicated to the destination. */
  copied: string[];
  /** Per-key failures. `message` is technical (logged); the surface maps `code`. */
  errors: {key: string; message: string; code?: string}[];
};

/** The fields a single HeadObject call exposes for the read-only metadata panel. */
export type ObjectMetadata = {
  key: string;
  contentType: string;
  /** Bytes (ContentLength). */
  size: number;
  lastModified: Date;
  etag: string;
  /** "STANDARD" when S3 omits it. */
  storageClass: string;
  /** The object's x-amz-meta-* pairs (empty when none were set). */
  userMetadata: Record<string, string>;
};

// Managed-upload tuning. lib-storage uploads a body at/below partSize in a single
// request and switches to automatic multipart above it — so MULTIPART_PART_SIZE
// is also the "multipart threshold". PART_CONCURRENCY is parts in flight per file.
export const MULTIPART_PART_SIZE = 5 * 1024 * 1024; // 5 MiB
export const PART_CONCURRENCY = 4;

// Overall per-file ceiling, default 5 GiB, overridable via env.
const DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;
const envMax = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES);
export const MAX_UPLOAD_BYTES = Number.isFinite(envMax) && envMax > 0 ? envMax : DEFAULT_MAX_UPLOAD_BYTES;

/**
 * One failed item in a bulk operation. `key` is the S3 key or prefix that failed —
 * the RAW path, not a label, so the render site owns how much of it to show.
 *
 * `message` is technical and must never be rendered; the banner maps `code` through
 * `toUserMessage` (SPEC-106).
 */
export type BulkOperationError = {key: string; message: string; code?: string};

/**
 * The feedback surface of a bulk file operation — delete, move, copy.
 *
 * Three hooks had grown near-identical shapes that differed only in the names
 * (`deletedCount`/`movedCount`/`copiedCount`, `errors[].key` vs `errors[].item`), and
 * `FileBrowser` rendered the same four blocks three times to match. One shape, one
 * renderer: `OperationFeedback`.
 *
 * An operation that cannot produce one of these reports it as absent, never as a
 * degenerate value — delete has no progress and no batch collision, so both are `null`.
 */
export type BulkOperationState = {
  isBusy: boolean;
  /** 0..100 while a folder operation runs; `null` when there is nothing to report. */
  progress: number | null;
  /** A systemic failure that stopped the whole operation. Dismissible. */
  error: string | null;
  /** The last completed run: how many succeeded, and which items didn't. */
  summary: {count: number; errors: BulkOperationError[]} | null;
  /** One Overwrite-all/Cancel confirmation covering the batch, where the op has one. */
  collision: {count: number; onOverwriteAll: () => void; onCancel: () => void} | null;
  dismissError: () => void;
  dismissSummary: () => void;
};
