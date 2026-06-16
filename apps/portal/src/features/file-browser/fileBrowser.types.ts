// Feature-scoped types for the file browser (SPEC-015).

export type DownloadUrl = {
  url: string; // presigned GetObject URL
  expiresAt: string; // ISO timestamp the URL stops working
};

// ── Upload (SPEC-016) ────────────────────────────────────────────────────────

export type UploadResult = { key: string };
export type CreateFolderResult = { prefix: string };

// ── Delete (SPEC-018) ────────────────────────────────────────────────────────

// The outcome of a (possibly batched/recursive) delete. `deleted` lists the keys
// S3 confirmed removed; `errors` collects per-key failures — including the marker
// guard refusal — so a partial failure is reported, never thrown (FR-002/FR-004).
export type DeleteResult = {
  deleted: string[];
  errors: { key: string; message: string }[];
};

// ── Move / rename (SPEC-019) ─────────────────────────────────────────────────

// The outcome of a (possibly recursive) move. `moved` lists the source keys whose
// object was copied to the destination and then deleted; `errors` collects per-key
// failures. Move is non-atomic: a key whose copy failed is left in place and
// reported here, never thrown (FR-004).
export type MoveResult = {
  moved: string[];
  errors: { key: string; message: string }[];
};

// ── Object metadata (SPEC-017) ───────────────────────────────────────────────

// The fields a single HeadObject call exposes for the read-only metadata panel.
// `storageClass` defaults to "STANDARD" when S3 omits it; `userMetadata` holds
// the object's x-amz-meta-* pairs (empty when none were set).
export type ObjectMetadata = {
  key: string;
  contentType: string;
  size: number; // bytes (ContentLength)
  lastModified: Date;
  etag: string;
  storageClass: string;
  userMetadata: Record<string, string>;
};

// Managed-upload tuning. lib-storage uploads a body at/below partSize in a single
// request and switches to automatic multipart above it — so MULTIPART_PART_SIZE
// is also the "multipart threshold". PART_CONCURRENCY is parts in flight per file.
export const MULTIPART_PART_SIZE = 5 * 1024 * 1024; // 5 MiB
export const PART_CONCURRENCY = 4;

// Overall per-file ceiling (FR-001), default 5 GiB, overridable via env.
const DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024;
const envMax = Number(import.meta.env.VITE_MAX_UPLOAD_BYTES);
export const MAX_UPLOAD_BYTES =
  Number.isFinite(envMax) && envMax > 0 ? envMax : DEFAULT_MAX_UPLOAD_BYTES;
