import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {moveObject} from './fileBrowser.service';
import {leafName, fileParent} from './fileBrowser.paths';
import type {SelectableItem} from './selectionContext';
import type {BulkOperationState} from './fileBrowser.types';

// Aggregated outcome of a rename or (possibly multi-item) move: how many objects S3 relocated,
// and any per-item failures.
export type MoveSummary = NonNullable<BulkOperationState['summary']>;

// A rename hit an existing destination. The user picks Overwrite or a
// new name; either re-runs the rename. Single item, so a new name is offered.
type RenameCollision = {
  kind: 'file' | 'folder';
  label: string;
  onOverwrite: () => void;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

// A move hit existing destination objects. One confirmation covers the
// whole batch: Overwrite all (re-run just the collided items) or cancel.
type MoveCollision = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

export type UseMoveResult = BulkOperationState & {
  /** A rename hit an existing name: single item, so a NEW NAME is offered as well
   *  as Overwrite — which is why it is not the shared `collision`. */
  renameCollision: RenameCollision | null;
  renameItem: (item: SelectableItem, newName: string) => void;
  // `destBucket` defaults to the source bucket; pass a different connection's
  // bucket to move across connections (feedback 2026-06-30).
  moveItems: (items: SelectableItem[], destPrefix: string, destBucket?: string) => void;
  cancelCollision: () => void;
};

type Acc = {moved: number; errors: MoveSummary['errors']};

/**
 * Orchestrates rename + move (single + multi-select) on top of `moveObject`.
 *
 * **Files move; folders are refused.** A folder rename is one `CopyObject` per contained object,
 * so its cost cannot be bounded without listing the folder first — which is exactly the work the
 * file-operations plane exists to take off the browser. With the plane off, the Move and Rename
 * controls refuse a folder before this is reached. With it on, one gesture still lands a folder
 * here: a move whose chosen destination resolves to no known space, which the dispatcher runs in
 * the browser. That folder is refused per item, and the files beside it still move.
 *
 * A move is ONE route now, not a copy call followed by a delete call: two calls put a closed tab
 * between them, and versioning is off.
 *
 * Mirrors useFileUpload's collision warn-and-confirm and useDelete's aggregation. `sourcePrefix`
 * is the current view (the items' common parent); both it and any destination prefix are
 * invalidated on completion so the moved items appear/disappear. Never throws.
 */
export function useMove(bucket: string, sourcePrefix: string, username: string | undefined): UseMoveResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<MoveSummary | null>(null);
  const [renameCollision, setRenameCollision] = useState<RenameCollision | null>(null);
  const [moveCollision, setMoveCollision] = useState<MoveCollision | null>(null);

  async function invalidate(prefixes: string[]) {
    const unique = [...new Set(prefixes)];
    await Promise.all(unique.map((p) => invalidateListing(queryClient, bucket, p)));
  }

  // After a move, the source listing (always in `bucket`) and the destination
  // listing (in `destBucket`, possibly another connection) both changed.
  async function invalidateMove(destPrefix: string, destBucket: string) {
    const tasks = [invalidateListing(queryClient, bucket, sourcePrefix)];
    if (!(destBucket === bucket && destPrefix === sourcePrefix)) {
      tasks.push(invalidateListing(queryClient, destBucket, destPrefix));
    }
    await Promise.all(tasks);
  }

  // ── Rename ────────────────────────────────────────────────────────────────
  async function runRename(item: SelectableItem, newName: string, overwrite: boolean) {
    if (!username) {
      setError('You must be signed in to rename files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    // Normalize both primitives' results into a common outcome so the shared
    // failure/collision handling below doesn't re-narrow the union.
    let outcome: {ok: true; moved: number; errors: MoveSummary['errors']} | {ok: false; code?: string; message: string};

    if (item.type === 'file') {
      const r = await moveObject({
        bucket,
        sourceKey: item.key,
        destKey: fileParent(item.key) + newName,
        username,
        overwrite
      });
      outcome = r.success
        ? {ok: true, moved: 1, errors: []}
        : {ok: false, code: r.error.code, message: r.error.message};
    } else {
      outcome = {ok: false, code: 'PlaneRequired', message: 'Folders are renamed by the file operations service.'};
    }

    if (!outcome.ok) {
      if (outcome.code === 'Collision') {
        setIsBusy(false);
        setRenameCollision({
          kind: item.type,
          label: newName,
          onOverwrite: () => {
            setRenameCollision(null);
            void runRename(item, newName, true);
          },
          onRename: (n) => {
            setRenameCollision(null);
            void runRename(item, n, false);
          },
          onCancel: () => {
            setRenameCollision(null);
            setIsBusy(false);
          }
        });
        return;
      }
      setError(toUserText({code: outcome.code, message: outcome.message}));
      setIsBusy(false);
      return;
    }

    await invalidate([sourcePrefix]);
    setSummary({count: outcome.moved, errors: outcome.errors});
    setIsBusy(false);
  }

  // ── Move ────────────────────────────────────────────────────────────────
  async function runMove(
    items: SelectableItem[],
    destPrefix: string,
    destBucket: string,
    overwrite: boolean,
    acc: Acc
  ) {
    if (!username) {
      setError('You must be signed in to move files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    const collided: SelectableItem[] = [];

    // Collision is checked before any write, so a collided item did nothing — it
    // can be safely re-run with overwrite after confirmation.
    for (const item of items) {
      if (item.type === 'file') {
        const r = await moveObject({
          bucket,
          sourceKey: item.key,
          destKey: destPrefix + leafName(item.key),
          username,
          destBucket,
          overwrite
        });
        if (r.success) acc.moved += 1;
        else if (r.error.code === 'Collision') collided.push(item);
        else acc.errors.push({key: item.key, message: r.error.message, code: r.error.code});
      } else {
        acc.errors.push({
          key: item.prefix,
          message: 'Folders are moved by the file operations service.',
          code: 'PlaneRequired'
        });
      }
    }

    if (collided.length > 0 && !overwrite) {
      setIsBusy(false);
      setMoveCollision({
        count: collided.length,
        onOverwriteAll: () => {
          setMoveCollision(null);
          void runMove(collided, destPrefix, destBucket, true, acc);
        },
        onCancel: () => {
          setMoveCollision(null);
          void finalizeMove(acc, destPrefix, destBucket);
        }
      });
      return;
    }

    await finalizeMove(acc, destPrefix, destBucket);
  }

  async function finalizeMove(acc: Acc, destPrefix: string, destBucket: string) {
    await invalidateMove(destPrefix, destBucket);
    setSummary({count: acc.moved, errors: acc.errors});
    setIsBusy(false);
  }

  return {
    isBusy,
    progress: null,
    error,
    summary,
    renameCollision,
    collision: moveCollision,
    renameItem: (item, newName) => void runRename(item, newName, false),
    moveItems: (items, destPrefix, destBucket = bucket) =>
      void runMove(items, destPrefix, destBucket, false, {moved: 0, errors: []}),
    dismissError: () => setError(null),
    dismissSummary: () => setSummary(null),
    cancelCollision: () => {
      setRenameCollision(null);
      setMoveCollision(null);
      setIsBusy(false);
    }
  };
}
