/**
 * The space an archive reads from, or a restore writes into.
 *
 * `name` is the username for a personal space and the space name for a shared one — which is
 * also the space's root prefix, in both kinds. The control plane re-derives the bucket and the
 * root from the verified actor and this pair, so the enqueued body never carries either.
 */
export type ArchiveSpace = {
  kind: 'personal' | 'shared';
  name: string;
};

/** One selected file or folder. `key` is the full S3 key, exactly as the browser lists it. */
export type ArchiveItem = {
  kind: 'file' | 'folder';
  key: string;
};

/** An archive request, as the browser enqueues it. */
export type ArchiveRequest = {
  /**
   * Client-minted UUID v4. It becomes the archive's PERMANENT identity — the `{uuid}` segment
   * of both the archive key and the receipt folder — and it is the FIFO deduplication id, so
   * it must be minted per submit rather than per dialog.
   */
  requestId: string;
  space: ArchiveSpace;
  items: ArchiveItem[];
};

/** A restore request, as the browser enqueues it. */
export type RestoreRequest = {
  /** This RUN's id. Never the archive's — a refused restore must be re-submittable. */
  requestId: string;
  /** The space being restored INTO, taken from the route (SPEC-113's rule, SPEC-170 FR-001). */
  space: ArchiveSpace;
  /** The archive being restored, pasted by the user. UUID-validated before enqueue. */
  archiveId: string;
};
