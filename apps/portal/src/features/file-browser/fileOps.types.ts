/**
 * The file-operations control plane's request contract.
 *
 * One envelope for copy, move and delete. The plane validates every field of it server-side —
 * these types are the browser's half of the agreement, not the enforcement.
 */

export type FileOpKind = 'copy' | 'move' | 'delete';

/** A selected item. `key` is an ABSOLUTE S3 key; folders carry a trailing slash. */
export type FileOpItem = {
  kind: 'file' | 'folder';
  key: string;
  /**
   * The item's name at the destination. Defaults to the item's own leaf name.
   *
   * This is what makes RENAME and same-folder auto-numbered COPY expressible: both send
   * `destination.prefix` = the containing folder and a different name. Without it a rename is
   * inexpressible — send the parent and the derived destination equals the source, so the
   * operation reports success having renamed nothing; send the full new prefix and the folder
   * nests inside itself.
   *
   * An empty string is not a shorthand for "use the item's own name" and the plane refuses it:
   * it would derive to the destination prefix itself, merging a folder's contents into the
   * destination and then, for a move, deleting the source.
   */
  targetName?: string;
};

export type FileOpSpace = {
  kind: 'personal' | 'shared';
  name: string;
};

/** The enqueued envelope. `actor` is added by the service, never by a component. */
export type FileOpRequest = {
  requestId: string;
  operation: FileOpKind;
  source: {space: FileOpSpace; items: FileOpItem[]};
  /** Required for copy/move, rejected for delete. */
  destination?: {space: FileOpSpace; prefix: string};
  /**
   * Required for copy/move, rejected for delete.
   *
   * A FIRST submit always sends `refuse`. `overwrite` is reachable only from the conflict round
   * trip, where the user has been shown what collided — and even then the plane bounds it by
   * `submittedAt`, so an object created at the destination after the confirmation is refused
   * anyway.
   */
  onConflict?: 'refuse' | 'overwrite';
  /**
   * ISO-8601 UTC. Required for copy/move.
   *
   * Bounds `overwrite` to objects that already existed when the user confirmed. A retry therefore
   * needs a FRESH timestamp, or the plane refuses the very objects the user just agreed to
   * overwrite.
   */
  submittedAt?: string;
};
