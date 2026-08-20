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

/** What every operation carries, whichever it is. */
type FileOpCommon = {
  requestId: string;
  source: {space: FileOpSpace; items: FileOpItem[]};
};

/**
 * The enqueued envelope. `actor` is added by the service, never by a component.
 *
 * **A discriminated union rather than three optional fields**, because the plane REJECTS
 * `destination`, `onConflict` and `submittedAt` on a delete rather than ignoring them — so a
 * delete carrying one is not a slightly-wrong request, it is a refused request. Independent
 * optionals type-check `{operation: 'delete', destination}` and leave the mistake to be found at
 * runtime, minutes later, by notification.
 */
export type FileOpRequest =
  | (FileOpCommon & {
      operation: 'delete';
      destination?: never;
      onConflict?: never;
      submittedAt?: never;
    })
  | (FileOpCommon & {
      operation: 'copy' | 'move';
      destination: {space: FileOpSpace; prefix: string};
      /**
       * A FIRST submit always sends `refuse`. `overwrite` is reachable only from the conflict
       * round trip, where the user has been shown what collided — and even then the plane bounds
       * it by `submittedAt`, so an object created at the destination after the confirmation is
       * refused anyway.
       */
      onConflict: 'refuse' | 'overwrite';
      /**
       * ISO-8601 UTC. Bounds `overwrite` to objects that already existed when the user confirmed.
       * A retry therefore needs a FRESH timestamp, or the plane refuses the very objects the user
       * just agreed to overwrite.
       */
      submittedAt: string;
    });
