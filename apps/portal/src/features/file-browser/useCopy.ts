import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {copyObject, firstFreeName, validateFolderName} from './fileBrowser.service';
import {leafName, folderParts} from './fileBrowser.paths';
import type {SelectableItem} from './selectionContext';
import type {BulkOperationState} from './fileBrowser.types';

/**
 * Aggregated outcome of a (possibly multi-item) copy: how many objects S3 duplicated, and any
 * per-item failures.
 */
export type CopySummary = NonNullable<BulkOperationState['summary']>;

// A copy into a different folder hit existing destination objects. One
// confirmation covers the whole batch: Overwrite all (re-run just the collided
// items) or cancel.
type CopyCollision = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

/**
 * A same-folder copy: the source name necessarily collides, so the app proposes an auto-numbered
 * name the user can edit before the copy runs.
 *
 * DATA ONLY — no `onConfirm`, no `onCancel`. The probe's result is the `targetName` of whichever
 * request follows, and only the dispatcher knows whether that is the synchronous copy (a single
 * file) or an enqueued one (a single folder). Owning the callbacks here would have meant deciding
 * that before the probe had resolved, which is the one ordering this flow cannot take.
 */
export type SameFolderPrompt = {
  kind: 'file' | 'folder';
  /** The editable, pre-filled non-colliding name. */
  proposedName: string;
  /** Create-folder/rename rules. */
  validate: (name: string) => string | null;
};

export type UseCopyResult = BulkOperationState & {
  sameFolderPrompt: SameFolderPrompt | null;
  /**
   * Asks the API for the first free `{name} (N)` and opens the prompt. Single item only — the
   * destination is its own parent, and the prompt names one thing.
   */
  startSameFolderCopy: (item: SelectableItem, destPrefix: string) => void;
  /** Runs the synchronous same-folder copy under an already-chosen, already-validated name. */
  runSameFolderCopy: (item: SelectableItem, destPrefix: string, name: string) => void;
  clearSameFolderPrompt: () => void;
  /**
   * Copies into a DIFFERENT folder. `destBucket` defaults to the source bucket; pass a different
   * connection's bucket to copy across connections.
   *
   * There is no same-folder branch here: the probe runs once, at
   * {@link UseCopyResult.startSameFolderCopy}, before the routing decision that needs its answer.
   * A second branch would ask again and could propose a different name from the one the user just
   * confirmed.
   */
  copyItems: (items: SelectableItem[], destPrefix: string, destBucket?: string) => void;
  cancelCollision: () => void;
};

type Acc = {copied: number; errors: CopySummary['errors']};

/**
 * Orchestrates copy (single + multi-select) on top of `copyObject`.
 *
 * **Files copy; folders are refused.** The recursive primitive is gone — an operation whose cost
 * grows with object count belongs on the file-operations plane. With the plane on, no folder
 * reaches here; with it off, a folder copy is unavailable rather than synchronous.
 *
 * Mirrors useMove, but copy is additive (no source delete)
 * so ONLY the destination prefix is invalidated — the source listing is
 * unchanged. Supplies the same-folder auto-number probe and the copy that follows it as separate
 * steps, because the caller decides between them on the probe's own answer. Never throws.
 *
 * It takes no source prefix. It used to, only to recognise "the destination is where these items
 * already are" — a question the caller now has to answer BEFORE it calls anything here, since the
 * probed name is what the routing decision is made with.
 */
export function useCopy(bucket: string, username?: string): UseCopyResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<CopySummary | null>(null);
  const [copyCollision, setCopyCollision] = useState<CopyCollision | null>(null);
  const [sameFolderPrompt, setSameFolderPrompt] = useState<SameFolderPrompt | null>(null);

  async function invalidateDest(destPrefix: string, destBucket: string) {
    await invalidateListing(queryClient, destBucket, destPrefix);
  }

  // ── Same-folder copy ───────────────────────────────────────────────────────
  // Runs a same-folder copy of a single FILE to an explicit (already-validated, non-colliding)
  // name within `destPrefix`. A folder is refused: the plane owns recursive work.
  async function runSameFolderCopy(item: SelectableItem, destPrefix: string, name: string) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    let outcome:
      {ok: true; copied: number; errors: CopySummary['errors']} | {ok: false; code?: string; message: string};

    if (item.type === 'file') {
      const r = await copyObject({
        bucket,
        sourceKey: item.key,
        destKey: `${destPrefix}${name}`,
        username,
        // The name came back free from the free-name route (or the user picked it), but a genuine
        // collision still gets a clear failure rather than a silent clobber.
        overwrite: false
      });
      outcome = r.success
        ? {ok: true, copied: 1, errors: []}
        : {ok: false, code: r.error.code, message: r.error.message};
    } else {
      outcome = {ok: false, code: 'PlaneRequired', message: 'Folders are copied by the file operations service.'};
    }

    if (!outcome.ok) {
      setError(toUserText({code: outcome.code, message: outcome.message}));
      setIsBusy(false);
      return;
    }

    // Same-folder copy is always within the source bucket.
    await invalidateDest(destPrefix, bucket);
    setSummary({count: outcome.copied, errors: outcome.errors});
    setIsBusy(false);
  }

  // Opens the editable same-folder prompt with a freshly-computed non-colliding
  // name. Single item only (the destination is its own parent).
  async function startSameFolderCopy(item: SelectableItem, destPrefix: string) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    const isFile = item.type === 'file';
    const baseName = isFile ? leafName(item.key) : folderParts(item.prefix).leaf;
    const proposed = await firstFreeName({
      bucket,
      prefix: destPrefix,
      baseName,
      kind: isFile ? 'file' : 'folder'
    });
    setIsBusy(false);

    if (!proposed.success) {
      setError(toUserText(proposed.error));
      return;
    }

    setSameFolderPrompt({kind: item.type, proposedName: proposed.data, validate: validateFolderName});
  }

  // ── Copy to a different folder ─────────────────────────────────────────────
  async function runCopy(
    items: SelectableItem[],
    destPrefix: string,
    destBucket: string,
    overwrite: boolean,
    acc: Acc
  ) {
    if (!username) {
      setError('You must be signed in to copy files.');
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
        const r = await copyObject({
          bucket,
          sourceKey: item.key,
          destKey: destPrefix + leafName(item.key),
          username,
          destBucket,
          overwrite
        });
        if (r.success) acc.copied += 1;
        else if (r.error.code === 'Collision') collided.push(item);
        else acc.errors.push({key: item.key, message: r.error.message, code: r.error.code});
      } else {
        acc.errors.push({
          key: item.prefix,
          message: 'Folders are copied by the file operations service.',
          code: 'PlaneRequired'
        });
      }
    }

    if (collided.length > 0 && !overwrite) {
      setIsBusy(false);
      setCopyCollision({
        count: collided.length,
        onOverwriteAll: () => {
          setCopyCollision(null);
          void runCopy(collided, destPrefix, destBucket, true, acc);
        },
        onCancel: () => {
          setCopyCollision(null);
          void finalizeCopy(acc, destPrefix, destBucket);
        }
      });
      return;
    }

    await finalizeCopy(acc, destPrefix, destBucket);
  }

  async function finalizeCopy(acc: Acc, destPrefix: string, destBucket: string) {
    // Copy is additive: only the DESTINATION listing changed.
    await invalidateDest(destPrefix, destBucket);
    setSummary({count: acc.copied, errors: acc.errors});
    setIsBusy(false);
  }

  // Entry point for a copy into a DIFFERENT folder, possibly in another connection's bucket. The
  // same-folder case never arrives here: its destination is the items' own parent, so it needs
  // the auto-number probe FIRST — the caller runs that and then decides where the copy goes.
  function copyItems(items: SelectableItem[], destPrefix: string, destBucket: string = bucket) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    if (items.length === 0) return;

    void runCopy(items, destPrefix, destBucket, false, {copied: 0, errors: []});
  }

  return {
    isBusy,
    progress: null,
    error,
    summary,
    collision: copyCollision,
    sameFolderPrompt,
    startSameFolderCopy: (item, destPrefix) => void startSameFolderCopy(item, destPrefix),
    runSameFolderCopy: (item, destPrefix, name) => void runSameFolderCopy(item, destPrefix, name),
    clearSameFolderPrompt: () => setSameFolderPrompt(null),
    copyItems,
    dismissError: () => setError(null),
    dismissSummary: () => setSummary(null),
    cancelCollision: () => {
      setCopyCollision(null);
      setSameFolderPrompt(null);
      setIsBusy(false);
    }
  };
}
