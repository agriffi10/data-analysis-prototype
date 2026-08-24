import {useCallback, useMemo} from 'react';
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query';
import {listFiles} from './fileBrowser.service';
import {unwrap} from '../../lib/serviceResult';
import {fileBrowserKeys} from './fileBrowserKeys';
import {isMarkerName} from './fileBrowser.constants';
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
 * Every `DO_NOT_DELETE.txt` is hidden, at any depth, in either bucket
 * — see `isMarkerName`. There is no caller-supplied key: the basename IS
 * the rule, because that is what the two bucket policies deny deletion on.
 */
export function useFileBrowser(bucket: string, prefix?: string): UseFileBrowserResult {
  const queryClient = useQueryClient();
  const normalizedPrefix = prefix ?? '';

  // Server state via TanStack Query. Each page is a
  // ListObjectsV2 call (MaxKeys = LISTING_PAGE_SIZE, 25) threading the
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
    getNextPageParam: (lastPage: FileListPage) => (lastPage.isTruncated ? lastPage.nextContinuationToken : undefined),
    // ON, against the app-wide default — this listing is no longer the only thing that changes
    // it. File operations run on a control plane now and finish minutes after the browser stops
    // watching, so a listing that only refetches on navigation is stale for as long as the user
    // stays on the folder.
    //
    // THE NOTIFICATION IS DELIBERATELY NOT THE MECHANISM, and the reason is measurable: its poll
    // is 60 s, the interval is paused while the tab is hidden, and it is disabled outright on the
    // notifications page — so reconciling from it would be up to a minute late and would never
    // fire on a backgrounded tab, which is precisely when a long operation finishes.
    //
    // The accepted cost, named: this is an INFINITE query, so a focus refetch re-reads every page
    // the user has loaded, sequentially. `staleTime` bounds how often that happens (30 s) and not
    // how many pages it costs; pages only accumulate on an explicit "Load more". Resetting to page
    // one instead would be cheaper and would lose the user's place.
    refetchOnWindowFocus: true
  });

  // Merge folders/files across all loaded pages and re-sort globally so the
  // ordering matches the original single-page behavior (folders before files,
  // each alphabetical). Prefix markers are filtered out by basename.
  const {folders, files} = useMemo(() => {
    const pages = query.data?.pages ?? [];
    const mergedFolders = pages.flatMap((p) => p.folders).sort((a, b) => a.name.localeCompare(b.name));
    const mergedFiles = pages
      .flatMap((p) => p.files)
      .filter((f) => !isMarkerName(f.key))
      .sort((a, b) => a.name.localeCompare(b.name));
    return {folders: mergedFolders, files: mergedFiles};
  }, [query.data]);

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
