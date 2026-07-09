// Feature-scoped types for the file browser.

export type DownloadUrl = {
  /** Presigned GetObject URL. */
  url: string;
  /** ISO timestamp the URL stops working. */
  expiresAt: string;
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
