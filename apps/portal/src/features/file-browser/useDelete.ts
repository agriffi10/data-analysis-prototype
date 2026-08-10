import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {deleteObjects, deleteFolder} from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';
import type {BulkOperationState} from './fileBrowser.types';

/**
 * The outcome surfaced to the UI after a (possibly mixed file + folder) delete:
 * how many objects S3 removed, and any per-item failures to report.
 */
export type DeleteSummary = NonNullable<BulkOperationState['summary']>;

/**
 * Delete's `BulkOperationState` plus the one action only it has. `progress` and
 * `collision` are always `null`: a delete reports no percentage (it is one batched
 * call plus a recursive walk, not a per-object stream) and has no overwrite
 * confirmation to make — the warn-and-confirm happens before it starts.
 */
export type UseDeleteResult = BulkOperationState & {
  runDelete: (items: SelectableItem[]) => Promise<DeleteSummary | null>;
};

/**
 * Orchestrates deleting a selection of files and folders. Loose files go in one
 * batched deleteObjects call; each folder is deleted recursively. Results
 * aggregate across all operations — a failure on one folder never aborts the
 * rest. On completion the current prefix listing is invalidated so removed
 * items disappear; the caller clears the selection. Never throws.
 *
 * @param prefix - the folder currently being viewed (what gets invalidated).
 * @param rootPrefix - the SPACE root, which `deleteFolder` needs to recognise a
 *   protected root folder. REQUIRED, not defaulted to `prefix`: a caller that fell
 *   back to the browsed folder while sitting in `alice/reports/` would make
 *   `alice/reports/athenaresults/` falsely undeletable.
 */
export function useDelete(
  bucket: string,
  prefix: string,
  username: string | undefined,
  rootPrefix: string
): UseDeleteResult {
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

    const fileKeys = items
      .filter((i): i is Extract<SelectableItem, {type: 'file'}> => i.type === 'file')
      .map((i) => i.key);
    const folders = items.filter((i): i is Extract<SelectableItem, {type: 'folder'}> => i.type === 'folder');

    const deleted: string[] = [];
    const errors: DeleteSummary['errors'] = [];

    // Loose files: one batched (chunked) DeleteObjects call. A systemic failure
    // here (e.g. credentials gone) affects everything, so abort and surface it.
    if (fileKeys.length > 0) {
      const result = await deleteObjects({bucket, keys: fileKeys, username});
      if (!result.success) {
        setError(toUserText(result.error));
        setIsBusy(false);
        return null;
      }
      deleted.push(...result.data.deleted);
      errors.push(...result.data.errors);
    }

    // Folders: recursive delete each. A whole-folder failure (e.g. listing that
    // folder was denied) is recorded against the folder and the rest continue.
    for (const folder of folders) {
      const result = await deleteFolder({
        bucket,
        prefix: folder.prefix,
        username,
        rootPrefix
      });
      if (!result.success) {
        errors.push({key: folder.prefix, message: result.error.message, code: result.error.code});
        continue;
      }
      deleted.push(...result.data.deleted);
      errors.push(...result.data.errors);
    }

    await invalidateListing(queryClient, bucket, prefix);

    const result: DeleteSummary = {count: deleted.length, errors};
    setSummary(result);
    setIsBusy(false);
    return result;
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
