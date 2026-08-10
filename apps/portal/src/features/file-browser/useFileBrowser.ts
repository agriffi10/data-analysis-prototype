import {useCallback, useMemo} from 'react';
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query';
import {listFiles} from './fileBrowser.service';
import {unwrap} from '../../lib/serviceResult';
import {fileBrowserKeys} from './fileBrowserKeys';
import {invalidateListing} from './invalidateListing';
import type {S3FileItem, S3FolderItem, FileListPage} from '../../types/s3.types';

export type UseFileBrowserResult = {
  files: S3FileItem[];
  folders: S3FolderItem[];
  isLoading: boolean;
  /** The raw listing error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  refresh: () => void;
  /** Whether further pages exist — drives the "Load more" control. */
  hasMore: boolean;
  /** Fetches the next listing page. */
  loadMore: () => void;
  /** Disables the "Load more" control mid-fetch. */
  isLoadingMore: boolean;
};

/**
 * Paginated folder listing backed by TanStack Query.
 *
 * @param markerKey - exact key to hide from the listing (the user's root prefix
 *   marker). Matched by exact key, so a like-named file in a subfolder shows.
 */
export function useFileBrowser(bucket: string, prefix?: string, markerKey?: string): UseFileBrowserResult {
  const queryClient = useQueryClient();
  const normalizedPrefix = prefix ?? '';

  // Server state via TanStack Query (SPEC-015 FR-002). Each page is a
  // ListObjectsV2 call (MaxKeys = LISTING_PAGE_SIZE, 25 — SPEC-037) threading the
  // continuation token; pages accumulate in query.data.pages.
  const query = useInfiniteQuery({
    queryKey: fileBrowserKeys.list(bucket, normalizedPrefix),
    queryFn: async ({pageParam, signal}) => {
      // The service never throws; unwrap its ServiceResult and throw here so
      // TanStack Query treats a failed listing as a query error. `signal` is TanStack's
      // own per-query signal — it fires when the query is cancelled (the last observer
      // unmounts, or the key changes), so leaving a folder stops its listing request.
      const result = await listFiles(bucket, prefix, pageParam, signal);
      return unwrap(result);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: FileListPage) => (lastPage.isTruncated ? lastPage.nextContinuationToken : undefined)
  });

  // Merge folders/files across all loaded pages and re-sort globally so the
  // ordering matches the single-page SPEC-002 behavior (folders before files,
  // each alphabetical). The SPEC-014 root marker is filtered by exact key.
  const {folders, files} = useMemo(() => {
    const pages = query.data?.pages ?? [];
    const mergedFolders = pages.flatMap((p) => p.folders).sort((a, b) => a.name.localeCompare(b.name));
    const mergedFiles = pages
      .flatMap((p) => p.files)
      .filter((f) => !markerKey || f.key !== markerKey)
      .sort((a, b) => a.name.localeCompare(b.name));
    return {folders: mergedFolders, files: mergedFiles};
  }, [query.data, markerKey]);

  const refresh = useCallback(() => {
    void invalidateListing(queryClient, bucket, normalizedPrefix);
  }, [queryClient, bucket, normalizedPrefix]);

  const loadMore = useCallback(() => {
    void query.fetchNextPage();
  }, [query]);

  return {
    files,
    folders,
    isLoading: query.isPending,
    error: query.error ?? null,
    refresh,
    hasMore: query.hasNextPage,
    loadMore,
    isLoadingMore: query.isFetchingNextPage
  };
}
