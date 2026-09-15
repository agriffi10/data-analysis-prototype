import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {createFolder} from './fileBrowser.service';

// What the user is being asked to confirm when a name already exists.
// `retry` re-runs the write with overwrite, or with a new name on rename.
type CollisionDecision = {overwrite: true} | {rename: string};

type PendingCollision = {
  kind: 'folder';
  label: string; // display name, e.g. "photos"
  retry: (decision: CollisionDecision) => void;
};

export type UseCreateFolderResult = {
  pendingCollision: PendingCollision | null;
  error: string | null;
  isBusy: boolean;
  createNewFolder: (name: string) => void;
  cancelCollision: () => void;
  dismissError: () => void;
};

/**
 * Orchestrates create-folder in the folder being viewed: surfaces a folder-name
 * collision for warn-and-confirm, maps a failure to user text, and invalidates the
 * current prefix's listing on success so the new folder appears.
 *
 * runCreateFolder is a hoisted function declaration (not useCallback) because it
 * references itself in its collision-retry closure; the returned callbacks are only
 * used in event handlers, so their identity churn is harmless.
 *
 * @example
 * const {createNewFolder, pendingCollision, error, isBusy} = useCreateFolder(bucket, prefix);
 */
export function useCreateFolder(bucket: string, prefix: string): UseCreateFolderResult {
  const queryClient = useQueryClient();
  const [pendingCollision, setPendingCollision] = useState<PendingCollision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function runCreateFolder(name: string, overwrite: boolean) {
    setIsBusy(true);
    setError(null);
    const result = await createFolder({bucket, prefix, name, overwrite});
    setIsBusy(false);

    if (result.success) {
      await invalidateListing(queryClient, bucket, prefix);
    } else if (result.error.code === 'Collision') {
      setPendingCollision({
        kind: 'folder',
        label: name,
        retry: (decision) =>
          'overwrite' in decision ? runCreateFolder(name, true) : runCreateFolder(decision.rename, false)
      });
    } else {
      setError(toUserText(result.error));
    }
  }

  // Resolving a collision clears the prompt, then re-runs the stored retry.
  const wrappedCollision: PendingCollision | null = pendingCollision && {
    ...pendingCollision,
    retry: (decision) => {
      setPendingCollision(null);
      pendingCollision.retry(decision);
    }
  };

  return {
    pendingCollision: wrappedCollision,
    error,
    isBusy,
    createNewFolder: (name) => void runCreateFolder(name, false),
    cancelCollision: () => setPendingCollision(null),
    dismissError: () => setError(null)
  };
}
