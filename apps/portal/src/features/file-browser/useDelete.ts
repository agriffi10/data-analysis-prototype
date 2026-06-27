import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from '../../lib/queryClient';
import {deleteObjects, deleteFolder} from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';

// The outcome surfaced to the UI after a (possibly mixed file + folder) delete:
// how many objects S3 removed, and any per-item failures to report (FR-004).
export type DeleteSummary = {
  deletedCount: number;
  errors: {key: string; message: string}[];
};

export type UseDeleteResult = {
  isDeleting: boolean;
  summary: DeleteSummary | null; // last completed delete (success or partial)
  error: string | null; // systemic failure (e.g. not signed in)
  runDelete: (items: SelectableItem[]) => Promise<DeleteSummary | null>;
  dismissSummary: () => void;
  dismissError: () => void;
};

// SPEC-018 Phase 2: orchestrates deleting a selection of files and folders. Loose
// files go in one batched deleteObjects call; each folder is deleted recursively
// via deleteFolder. Results aggregate across all operations — a failure on one
// folder never aborts the rest (FR-003/FR-004). On completion the current prefix
// listing is invalidated so successfully removed items disappear; the caller
// clears the selection. Never throws.
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
        setError(result.error.message);
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
        errors.push({key: folder.prefix, message: result.error.message});
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
