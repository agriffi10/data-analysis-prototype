import { useState, useEffect, useCallback } from 'react';
import { listFiles } from './fileBrowser.service';
import type { S3FileItem, S3FolderItem } from '../../types/s3.types';

export type UseFileBrowserResult = {
  files: S3FileItem[];
  folders: S3FolderItem[];
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
};

export function useFileBrowser(
  bucket: string,
  prefix?: string,
  // SPEC-014 FR-002: exact key to hide from the listing (the user's root prefix
  // marker). Matched by exact key, so a like-named file in a subfolder is shown.
  markerKey?: string,
): UseFileBrowserResult {
  const [files, setFiles] = useState<S3FileItem[]>([]);
  const [folders, setFolders] = useState<S3FolderItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function fetchFiles() {
      setIsLoading(true);
      setError(null);

      const result = await listFiles(bucket, prefix);

      if (cancelled) return;

      if (result.success) {
        setFiles(
          markerKey
            ? result.data.files.filter((f) => f.key !== markerKey)
            : result.data.files,
        );
        setFolders(result.data.folders);
      } else {
        setError(result.error.message);
        setFiles([]);
        setFolders([]);
      }

      setIsLoading(false);
    }

    void fetchFiles();

    return () => {
      cancelled = true;
    };
  }, [bucket, prefix, markerKey, refreshTick]);

  const refresh = useCallback(() => {
    setRefreshTick((n) => n + 1);
  }, []);

  return { files, folders, isLoading, error, refresh };
}
