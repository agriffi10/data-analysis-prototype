import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { invalidateListing } from '../../lib/queryClient';
import { moveObject, moveFolder, uploadPercent } from './fileBrowser.service';
import { leafName, fileParent, folderParts } from './fileBrowser.paths';
import type { SelectableItem } from './selectionContext';

// Aggregated outcome of a rename or (possibly multi-item, recursive) move:
// how many objects S3 relocated, and any per-item/per-key failures (FR-004).
export type MoveSummary = {
  movedCount: number;
  errors: { key: string; message: string }[];
};

// A rename hit an existing destination (FR-005). The user picks Overwrite or a
// new name; either re-runs the rename. Single item, so a new name is offered.
type RenameCollision = {
  kind: 'file' | 'folder';
  label: string;
  onOverwrite: () => void;
  onRename: (newName: string) => void;
  onCancel: () => void;
};

// A move hit existing destination objects (FR-005). One confirmation covers the
// whole batch: Overwrite all (re-run just the collided items) or cancel.
type MoveCollision = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

export type UseMoveResult = {
  isBusy: boolean;
  progress: number | null; // 0..100 while a folder operation runs, else null
  error: string | null;
  summary: MoveSummary | null;
  renameCollision: RenameCollision | null;
  moveCollision: MoveCollision | null;
  renameItem: (item: SelectableItem, newName: string) => void;
  moveItems: (items: SelectableItem[], destPrefix: string) => void;
  dismissError: () => void;
  dismissSummary: () => void;
  cancelCollision: () => void;
};

type Acc = { moved: number; errors: MoveSummary['errors'] };

// SPEC-019 Phase 2: orchestrates rename + move (single + multi-select) on top of
// the moveObject/moveFolder service primitives. Mirrors useFileUpload's collision
// warn-and-confirm and useDelete's aggregation. `sourcePrefix` is the current view
// (the items' common parent); both it and any destination prefix are invalidated
// on completion so the moved items appear/disappear. Never throws.
export function useMove(
  bucket: string,
  sourcePrefix: string,
  username?: string,
): UseMoveResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<MoveSummary | null>(null);
  const [renameCollision, setRenameCollision] = useState<RenameCollision | null>(
    null,
  );
  const [moveCollision, setMoveCollision] = useState<MoveCollision | null>(null);

  async function invalidate(prefixes: string[]) {
    const unique = [...new Set(prefixes)];
    await Promise.all(unique.map((p) => invalidateListing(queryClient, bucket, p)));
  }

  // ── Rename ────────────────────────────────────────────────────────────────
  async function runRename(
    item: SelectableItem,
    newName: string,
    overwrite: boolean,
  ) {
    if (!username) {
      setError('You must be signed in to rename files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    // Normalize both primitives' results into a common outcome so the shared
    // failure/collision handling below doesn't re-narrow the union.
    let outcome:
      | { ok: true; moved: number; errors: MoveSummary['errors'] }
      | { ok: false; code?: string; message: string };

    if (item.type === 'file') {
      const r = await moveObject({
        bucket,
        sourceKey: item.key,
        destKey: fileParent(item.key) + newName,
        username,
        overwrite,
      });
      outcome = r.success
        ? { ok: true, moved: 1, errors: [] }
        : { ok: false, code: r.error.code, message: r.error.message };
    } else {
      const { parent } = folderParts(item.prefix);
      const r = await moveFolder({
        bucket,
        sourcePrefix: item.prefix,
        destPrefix: `${parent}${newName}/`,
        username,
        overwrite,
        onProgress: (p, t) => setProgress(uploadPercent(p, t)),
      });
      outcome = r.success
        ? { ok: true, moved: r.data.moved.length, errors: r.data.errors }
        : { ok: false, code: r.error.code, message: r.error.message };
    }

    setProgress(null);

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
          },
        });
        return;
      }
      setError(outcome.message);
      setIsBusy(false);
      return;
    }

    await invalidate([sourcePrefix]);
    setSummary({ movedCount: outcome.moved, errors: outcome.errors });
    setIsBusy(false);
  }

  // ── Move ────────────────────────────────────────────────────────────────
  async function runMove(
    items: SelectableItem[],
    destPrefix: string,
    overwrite: boolean,
    acc: Acc,
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
          overwrite,
        });
        if (r.success) acc.moved += 1;
        else if (r.error.code === 'Collision') collided.push(item);
        else acc.errors.push({ key: item.key, message: r.error.message });
      } else {
        const { leaf } = folderParts(item.prefix);
        const r = await moveFolder({
          bucket,
          sourcePrefix: item.prefix,
          destPrefix: `${destPrefix}${leaf}/`,
          username,
          overwrite,
          onProgress: (p, t) => setProgress(uploadPercent(p, t)),
        });
        if (r.success) {
          acc.moved += r.data.moved.length;
          acc.errors.push(...r.data.errors);
        } else if (r.error.code === 'Collision') {
          collided.push(item);
        } else {
          acc.errors.push({ key: item.prefix, message: r.error.message });
        }
      }
    }

    setProgress(null);

    if (collided.length > 0 && !overwrite) {
      setIsBusy(false);
      setMoveCollision({
        count: collided.length,
        onOverwriteAll: () => {
          setMoveCollision(null);
          void runMove(collided, destPrefix, true, acc);
        },
        onCancel: () => {
          setMoveCollision(null);
          void finalizeMove(acc, destPrefix);
        },
      });
      return;
    }

    await finalizeMove(acc, destPrefix);
  }

  async function finalizeMove(acc: Acc, destPrefix: string) {
    await invalidate([sourcePrefix, destPrefix]);
    setSummary({ movedCount: acc.moved, errors: acc.errors });
    setIsBusy(false);
  }

  return {
    isBusy,
    progress,
    error,
    summary,
    renameCollision,
    moveCollision,
    renameItem: (item, newName) => void runRename(item, newName, false),
    moveItems: (items, destPrefix) =>
      void runMove(items, destPrefix, false, { moved: 0, errors: [] }),
    dismissError: () => setError(null),
    dismissSummary: () => setSummary(null),
    cancelCollision: () => {
      setRenameCollision(null);
      setMoveCollision(null);
      setIsBusy(false);
    },
  };
}
