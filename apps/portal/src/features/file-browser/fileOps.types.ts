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

/**
 * What the plane says it did to ONE item.
 *
 * Thirteen members, and the browser does not choose them: `focommon.outcomes` is the authority
 * and `focommon.messages` words them. This union exists so the surfaces that group and label
 * them cannot invent a fourteenth.
 *
 * `cleared` is a GATE verdict, not a terminal one — the plane's terminals refuse to emit it — so
 * it never reaches the browser. It is listed because the union is the plane's vocabulary, and a
 * reader who finds it absent would reasonably conclude the gate had been removed.
 */
export type FileOpOutcome =
  | 'cleared'
  | 'conflict'
  | 'noop'
  | 'source_missing'
  | 'source_empty'
  | 'protected'
  | 'copy_failed'
  | 'delete_failed'
  | 'duplicate'
  | 'refused'
  | 'moved'
  | 'copied'
  | 'deleted';

/**
 * One item's outcome as a surface renders it.
 *
 * `sample` is the colliding keys the producer named, already shortened for display, and `more`
 * says the list was cut — both are bounded at the producer by BYTES as well as count, so a
 * renderer must never present either as complete.
 */
export type FileOpItemResult = {
  itemKey: string;
  /** The item as the user named it — a leaf, never a whole key. */
  label: string;
  outcome: FileOpOutcome;
  reason?: string;
  sample?: string[];
  more?: boolean;
};

/**
 * One operation this session handed to the plane. Session-scoped and NOT persisted.
 *
 * The notification is the durable channel; a persisted queue would be a second writer to state
 * the plane owns, and it would outlive the only thing that can settle it.
 *
 * `destinationSpace` is carried because a cross-space copy or move takes TWO locks: a gate keyed
 * on the source alone leaves the destination open to a second submit from this same session,
 * which is the collision the plane's acceptance of unordered lock waiters leans on the browser
 * to make rare.
 */
export type InFlightOperation = {
  requestId: string;
  operation: FileOpKind;
  itemCount: number;
  /** The one item's name when there is one, for a surface that would rather not say "1 item". */
  label?: string;
  sourceSpace: FileOpSpace;
  destinationSpace?: FileOpSpace;
  destinationPrefix?: string;
  /** ISO-8601, browser clock — what the surface counts "since when" from. */
  submittedAt: string;
  state: 'submitted' | 'settled' | 'refused' | 'expired';
};
