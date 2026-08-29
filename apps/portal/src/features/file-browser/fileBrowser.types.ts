// Feature-scoped types for the file browser.

export type DownloadUrl = {
  /** Presigned GetObject URL. A bearer token: whoever holds it can read the object. */
  url: string;
  /**
   * When it dies, ISO-8601 UTC — never later than the signing session's own expiry.
   *
   * Returned so a caller can tell an expired link from a denial: both present as a 403 from S3,
   * and only one of them is worth retrying.
   */
  expiresAt: string;
};

export type UploadResult = {key: string};
export type CreateFolderResult = {prefix: string};

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

/**
 * One failed item in a bulk operation. `key` is the S3 key or prefix that failed —
 * the RAW path, not a label, so the render site owns how much of it to show.
 *
 * `message` is technical and must never be rendered; the banner maps `code` through
 * `toUserMessage`.
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
