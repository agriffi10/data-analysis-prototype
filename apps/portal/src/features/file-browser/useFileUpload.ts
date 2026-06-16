import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { invalidateListing } from '../../lib/queryClient';
import {
  uploadFile,
  createFolder,
  uploadPercent,
} from './fileBrowser.service';

// What the user is being asked to confirm when a name already exists (FR-003).
// `retry` re-runs the write with overwrite, or with a new name on rename.
type CollisionDecision = { overwrite: true } | { rename: string };

type PendingCollision = {
  kind: 'file' | 'folder';
  label: string; // display name, e.g. "report.pdf"
  retry: (decision: CollisionDecision) => void;
};

export type UseFileUploadResult = {
  progress: number | null; // 0..100 while a file uploads, else null
  pendingCollision: PendingCollision | null;
  error: string | null;
  isBusy: boolean;
  uploadOne: (file: File) => void;
  createNewFolder: (name: string) => void;
  cancelCollision: () => void;
  dismissError: () => void;
};

// SPEC-016 Phase 3: orchestrates single-file upload + create-folder against the
// service, tracking progress, surfacing collisions for warn-and-confirm, and
// invalidating the current prefix's listing on success so the new item appears.
//
// runUpload/runCreateFolder are hoisted function declarations (not useCallback)
// because each references itself in its collision-retry closure; the returned
// callbacks are only used in event handlers, so their identity churn is harmless.
export function useFileUpload(
  bucket: string,
  prefix: string,
): UseFileUploadResult {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<number | null>(null);
  const [pendingCollision, setPendingCollision] =
    useState<PendingCollision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function runUpload(file: File, overwrite: boolean, name: string) {
    setIsBusy(true);
    setError(null);
    setProgress(0);
    const result = await uploadFile({
      bucket,
      key: prefix + name,
      body: file,
      contentType: file.type || 'application/octet-stream',
      overwrite,
      onProgress: (loaded, total) => setProgress(uploadPercent(loaded, total)),
    });
    setProgress(null);
    setIsBusy(false);

    if (result.success) {
      await invalidateListing(queryClient, bucket, prefix);
    } else if (result.error.code === 'Collision') {
      setPendingCollision({
        kind: 'file',
        label: name,
        retry: (decision) =>
          runUpload(
            file,
            'overwrite' in decision,
            'rename' in decision ? decision.rename : name,
          ),
      });
    } else {
      setError(result.error.message);
    }
  }

  async function runCreateFolder(name: string, overwrite: boolean) {
    setIsBusy(true);
    setError(null);
    const result = await createFolder({ bucket, prefix, name, overwrite });
    setIsBusy(false);

    if (result.success) {
      await invalidateListing(queryClient, bucket, prefix);
    } else if (result.error.code === 'Collision') {
      setPendingCollision({
        kind: 'folder',
        label: name,
        retry: (decision) =>
          'overwrite' in decision
            ? runCreateFolder(name, true)
            : runCreateFolder(decision.rename, false),
      });
    } else {
      setError(result.error.message);
    }
  }

  // Resolving a collision clears the prompt, then re-runs the stored retry.
  const wrappedCollision: PendingCollision | null = pendingCollision && {
    ...pendingCollision,
    retry: (decision) => {
      setPendingCollision(null);
      pendingCollision.retry(decision);
    },
  };

  return {
    progress,
    pendingCollision: wrappedCollision,
    error,
    isBusy,
    uploadOne: (file) => void runUpload(file, false, file.name),
    createNewFolder: (name) => void runCreateFolder(name, false),
    cancelCollision: () => setPendingCollision(null),
    dismissError: () => setError(null),
  };
}
