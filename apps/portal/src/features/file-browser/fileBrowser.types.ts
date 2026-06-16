// Feature-scoped types for the file browser (SPEC-015).

export type DownloadUrl = {
  url: string; // presigned GetObject URL
  expiresAt: string; // ISO timestamp the URL stops working
};

// ── Upload (SPEC-016) ────────────────────────────────────────────────────────

export type UploadResult = { key: string };
export type CreateFolderResult = { prefix: string };

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
