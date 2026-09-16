import {fileParent, folderParts, leafName} from './fileBrowser.paths';
import type {FileOpItem, FileOpKind, FileOpRequest, FileOpSpace} from './fileOps.types';
import type {SelectableItem} from './selectionContext';
import type {NotificationPayload} from '../notifications';

/** Where a copy or move is going: the space, and the folder inside it. */
export type FileOpDestination = {space: FileOpSpace; prefix: string};

/**
 * One gesture, in the shape the request builder needs.
 *
 * `targetName` is the whole difference between the two `move` shapes and between the two `copy`
 * shapes, and it cannot be expressed as a destination prefix instead: send
 * the parent folder alone and a rename derives a destination equal to its source, reporting
 * success having renamed nothing; send the full new prefix and the folder nests inside itself.
 */
export type FileOpGesture = {
  operation: FileOpKind;
  items: SelectableItem[];
  /** Absent only for a delete, which the plane refuses one on. */
  destination?: FileOpDestination;
  /** The single item's name at the destination — a rename, or a same-folder auto-numbered copy. */
  targetName?: string;
  /** Defaults to `refuse`. `overwrite` is reachable only from the conflict round trip. */
  onConflict?: 'refuse' | 'overwrite';
};

/** The item's own display name — the leaf, whichever kind it is. */
export function itemLabel(item: SelectableItem): string {
  return item.type === 'file' ? leafName(item.key) : folderParts(item.prefix).leaf;
}

/**
 * The folder an item currently sits in — where a rename sends it.
 *
 * A rename and a same-folder copy are the same request shape: the containing folder as the
 * destination prefix, and a different `targetName`.
 *
 * @param item - The item being renamed.
 * @returns Its parent prefix, with the trailing slash S3 keys carry.
 */
export function containingFolder(item: SelectableItem): string {
  return item.type === 'file' ? fileParent(item.key) : folderParts(item.prefix).parent;
}

/**
 * The selection as the plane's contract names it.
 *
 * A folder keeps its TRAILING SLASH: the plane expands a folder by listing that prefix, so
 * without it `alice/report` would match `alice/reports/` as well.
 *
 * @param items - The selected rows.
 * @param targetName - The single item's destination name, for the two single-item shapes.
 * @returns The contract's items.
 */
export function toFileOpItems(items: readonly SelectableItem[], targetName?: string): FileOpItem[] {
  return items.map((item) => ({
    kind: item.type,
    key: item.type === 'file' ? item.key : item.prefix,
    ...(targetName ? {targetName} : {})
  }));
}

/**
 * Builds the envelope for one gesture.
 *
 * **A delete carries no `destination`, no `onConflict` and no `submittedAt`.** The plane rejects
 * unknown top-level fields and rejects `onConflict` on a delete outright, so sending them
 * unconditionally refuses every delete at the front door. The union in `fileOps.types` makes the
 * mistake unconstructable in TypeScript; this keeps it true of the value.
 *
 * **`submittedAt` is stamped by the caller, per submit.** A stale one makes the plane's
 * `LastModified < submittedAt` predicate refuse the very objects the user just agreed to
 * overwrite, so a conflict re-submit must mint a fresh one along with its new `requestId`.
 *
 * @param gesture - What the user did.
 * @param source - The space the items came from.
 * @param ids - The per-submit `requestId` and `submittedAt`.
 * @returns The envelope to enqueue.
 * @throws If a copy or move arrives with no destination. That is a programmer error rather than
 *   an answer: the plane would refuse it as a request-shape error minutes later, by notification.
 */
export function buildFileOpRequest(
  gesture: FileOpGesture,
  source: FileOpSpace,
  ids: {requestId: string; submittedAt: string}
): FileOpRequest {
  const items = toFileOpItems(gesture.items, gesture.targetName);
  if (gesture.operation === 'delete') {
    return {requestId: ids.requestId, operation: 'delete', source: {space: source, items}};
  }
  if (!gesture.destination) {
    throw new Error(`a ${gesture.operation} needs a destination`);
  }
  return {
    requestId: ids.requestId,
    operation: gesture.operation,
    source: {space: source, items},
    destination: gesture.destination,
    onConflict: gesture.onConflict ?? 'refuse',
    submittedAt: ids.submittedAt
  };
}

/**
 * A space as the notification payload carries it, or nothing.
 *
 * The payload is data read back out of S3, so every field of it is optional at the type level
 * and `kind` is a bare string. A space that does not narrow yields no re-submit at all, which is
 * the honest answer — the alternative is a request enqueued against a space nobody named.
 *
 * @param space - The payload's space fragment.
 * @returns The space, or undefined.
 */
function payloadSpace(space: {kind?: string; name?: string} | undefined): FileOpSpace | undefined {
  if (!space?.name) return undefined;
  if (space.kind !== 'personal' && space.kind !== 'shared') return undefined;
  return {kind: space.kind, name: space.name};
}

/**
 * The kind of one conflicted item, as a re-submit sends it.
 *
 * A key ending in `/` is a folder wherever the producer's own `kind` did not survive the reader's
 * field-by-field rebuild. Guessing the kind is safe in a way that omitting it is not: the plane
 * derives a folder's destination by listing the prefix, and a folder sent as a file plants a
 * zero-byte object where the folder should be.
 *
 * @param conflict - One entry of the payload's `conflicts`.
 * @returns `file` or `folder`.
 */
export function conflictKind(conflict: NonNullable<NotificationPayload['conflicts']>[number]): FileOpItem['kind'] {
  if (conflict.kind === 'file' || conflict.kind === 'folder') return conflict.kind;
  return conflict.itemKey.endsWith('/') ? 'folder' : 'file';
}

/**
 * Builds the re-submit of the items a run could not place, from the notification alone.
 *
 * **BOTH spaces come from the payload, never from the browser the user happens to be standing
 * in.** The conflict view is reachable from a tab that never submitted, and the control's own
 * href falls back to a bare `/files` whenever the row carries no usable prefix — at which point
 * the page resolves the user's PERSONAL space. A source space taken from the mount would then
 * hash to the wrong FIFO group, take the wrong per-space lock, and be refused by the plane's
 * authorization for a space the items were never in.
 *
 * Only the conflicted items are re-sent. The rest already happened, and re-sending them would
 * copy them a second time.
 *
 * @param payload - The producer's structured field.
 * @param ids - The per-submit `requestId` and `submittedAt`, both fresh.
 * @param choice - `overwrite` for the confirmed overwrite; a `targetName` for the rename's
 *   "or type a new name", which re-submits as a `refuse` and is strictly the safer of the two.
 * @returns The envelope, or undefined when the payload cannot describe a request.
 */
export function buildResubmitRequest(
  payload: NotificationPayload,
  ids: {requestId: string; submittedAt: string},
  choice: {onConflict: 'refuse' | 'overwrite'; targetName?: string}
): FileOpRequest | undefined {
  const operation = payload.operation;
  if (operation !== 'copy' && operation !== 'move') return undefined;

  const source = payloadSpace(payload.source);
  const destinationSpace = payloadSpace(payload.destination);
  const prefix = payload.destination?.prefix;
  const conflicts = payload.conflicts ?? [];
  if (!source || !destinationSpace || !prefix || conflicts.length === 0) return undefined;

  return {
    requestId: ids.requestId,
    operation,
    source: {
      space: source,
      items: conflicts.map((conflict) => {
        const targetName = choice.targetName ?? conflict.targetName;
        return {
          kind: conflictKind(conflict),
          key: conflict.itemKey,
          ...(targetName ? {targetName} : {})
        };
      })
    },
    destination: {space: destinationSpace, prefix},
    onConflict: choice.onConflict,
    submittedAt: ids.submittedAt
  };
}
