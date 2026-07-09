import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from '../../lib/queryClient';
import {toUserMessage} from '../../lib/errorMessages';
import {deleteObjects, deleteFolder} from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';

/**
 * The outcome surfaced to the UI after a (possibly mixed file + folder) delete:
 * how many objects S3 removed, and any per-item failures to report.
 */
export type DeleteSummary = {
  deletedCount: number;
  /** `message` is technical; the summary banner maps `code` (SPEC-106). */
  errors: {key: string; message: string; code?: string}[];
};

export type UseDeleteResult = {
  isDeleting: boolean;
  /** Last completed delete (success or partial). */
  summary: DeleteSummary | null;
  /** Systemic failure (e.g. not signed in). */
  error: string | null;
  runDelete: (items: SelectableItem[]) => Promise<DeleteSummary | null>;
  dismissSummary: () => void;
  dismissError: () => void;
};

/**
 * Orchestrates deleting a selection of files and folders. Loose files go in one
 * batched deleteObjects call; each folder is deleted recursively. Results
 * aggregate across all operations — a failure on one folder never aborts the
 * rest. On completion the current prefix listing is invalidated so removed
 * items disappear; the caller clears the selection. Never throws.
 */
export function useDelete(bucket: string, prefix: string, username?: string): UseDeleteResult {
  const queryClient = useQueryClient();
  const [isDeleting, setIsDeleting] = useState(false);
  const [summary, setSummary] = useState<DeleteSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runDelete(items: SelectableItem[]): Promise<DeleteSummary | null> {
    if (!username) {
      setError('You must be signed in to delete files.');
      return null;
    }
    if (items.length === 0) return null;

    setIsDeleting(true);
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
        setError(toUserMessage(result.error).message);
        setIsDeleting(false);
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
        username
      });
      if (!result.success) {
        errors.push({key: folder.prefix, message: result.error.message, code: result.error.code});
        continue;
      }
      deleted.push(...result.data.deleted);
      errors.push(...result.data.errors);
    }

    await invalidateListing(queryClient, bucket, prefix);

    const result: DeleteSummary = {deletedCount: deleted.length, errors};
    setSummary(result);
    setIsDeleting(false);
    return result;
  }

  return {
    isDeleting,
    summary,
    error,
    runDelete,
    dismissSummary: () => setSummary(null),
    dismissError: () => setError(null)
  };
}
