import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {deleteObject} from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';
import type {BulkOperationState} from './fileBrowser.types';

/**
 * The outcome surfaced to the UI after a delete: how many objects S3 removed, and any per-item
 * failures to report.
 */
export type DeleteSummary = NonNullable<BulkOperationState['summary']>;

/**
 * Delete's `BulkOperationState` plus the one action only it has. `progress` and
 * `collision` are always `null`: a delete reports no percentage and has no overwrite
 * confirmation to make — the warn-and-confirm happens before it starts.
 */
export type UseDeleteResult = BulkOperationState & {
  runDelete: (items: SelectableItem[]) => Promise<DeleteSummary | null>;
};

/**
 * Orchestrates deleting a selection of files.
 *
 * **Files loop; folders are refused.** The recursive primitive this hook used to call is gone: an
 * operation whose cost grows with object count belongs on the file-operations plane, and building
 * it a second time in the browser is the loop that plane exists to remove. No real gesture brings
 * a folder here, or more than one item: with the plane taking work — the shipped default — such a
 * selection is enqueued, and with it switched off the Delete control refuses it before the
 * confirm. The per-item refusal below is the backstop for a caller that skips that gate, and it
 * still deletes the files beside a folder and names the folders it did not touch.
 *
 * Results aggregate across all items — one failure never aborts the rest. On completion the
 * current prefix listing is invalidated so removed items disappear; the caller clears the
 * selection. Never throws.
 *
 * @param prefix - the folder currently being viewed (what gets invalidated).
 */
export function useDelete(bucket: string, prefix: string, username: string | undefined): UseDeleteResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [summary, setSummary] = useState<DeleteSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runDelete(items: SelectableItem[]): Promise<DeleteSummary | null> {
    if (!username) {
      setError('You must be signed in to delete files.');
      return null;
    }
    if (items.length === 0) return null;

    setIsBusy(true);
    setError(null);
    setSummary(null);

    const deleted: string[] = [];
    const errors: DeleteSummary['errors'] = [];

    for (const item of items) {
      if (item.type === 'folder') {
        errors.push({
          key: item.prefix,
          message: 'Folders are deleted by the file operations service.',
          code: 'PlaneRequired'
        });
        continue;
      }
      const result = await deleteObject({bucket, key: item.key, username});
      if (result.success) deleted.push(result.data.key);
      else errors.push({key: item.key, message: result.error.message, code: result.error.code});
    }

    await invalidateListing(queryClient, bucket, prefix);

    const outcome: DeleteSummary = {count: deleted.length, errors};
    setSummary(outcome);
    setIsBusy(false);
    return outcome;
  }

  return {
    isBusy,
    progress: null,
    error,
    summary,
    collision: null,
    runDelete,
    dismissSummary: () => setSummary(null),
    dismissError: () => setError(null)
  };
}
