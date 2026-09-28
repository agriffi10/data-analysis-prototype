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
  /**
   * What the user called the archive, as typed. The service normalises it and sends it as
   * `archiveName` only when something is left; absent or empty means the archive has no name.
   */
  name?: string;
};

/** A restore request, as the browser enqueues it. */
export type RestoreRequest = {
  /** This RUN's id. Never the archive's — a refused restore must be re-submittable. */
  requestId: string;
  /** The space being restored INTO, taken from the route, never derived. */
  space: ArchiveSpace;
  /** The archive being restored, pasted by the user. UUID-validated before enqueue. */
  archiveId: string;
};

/** What an archive's last restore did, as the plane recorded it on the archive's index entry. */
export type ArchiveRestoreRecord = {
  status: 'requested' | 'restored' | 'incomplete';
  /** When the restore was asked for — the restore run's start. */
  requestedAt: string;
  /** When this status was recorded. */
  updatedAt: string;
};

/**
 * One archive's entry in its space's index, `{root}system_settings/archive/index.json`, exactly as
 * `arcommon.index_store` writes it. A label for the restore list, never the record of what exists.
 */
export type ArchiveIndexEntry = {
  archiveId: string;
  name: string | null;
  /** The archive run's start, ISO-8601. */
  archivedAt: string;
  archivedBy: string;
  /** The first few selected items, relative to the space root, a folder's with its slash. */
  items: {kind: 'file' | 'folder'; path: string}[];
  /** How many items were selected. */
  itemCount: number;
  fileCount: number;
  totalBytes: number;
  restore: ArchiveRestoreRecord | null;
};

/** The index document itself. */
export type ArchiveIndexDocument = {version: 1; archives: ArchiveIndexEntry[]};

/**
 * One row of the restore list. Every archive with a receipt folder has one; `details` is null for
 * an archive the index does not label, which is still restored exactly as a labelled one.
 */
export type ArchiveListing = {
  archiveId: string;
  details: Omit<ArchiveIndexEntry, 'archiveId'> | null;
};
