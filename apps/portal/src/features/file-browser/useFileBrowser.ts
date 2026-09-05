import {useCallback, useMemo, useState} from 'react';
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query';
import {listFiles} from './fileBrowser.service';
import {unwrap} from '../../lib/serviceResult';
import {fileBrowserKeys} from './fileBrowserKeys';
import {isMarkerName} from './fileBrowser.constants';
import {invalidateListing} from './invalidateListing';
import type {S3FileItem, S3FolderItem, FileListPage} from '../../types/s3.types';

/**
 * The one server page the browser shows. Each page is exactly what one `ListObjectsV2`
 * call returned — folders first, each alphabetical — so a page never shifts as later
 * pages load, which a slice of the globally re-sorted listing would.
 */
export type ListingPage = {
  /** Zero-based index of the page on screen, clamped to the pages that exist. */
  index: number;
  /** How many pages have loaded so far. */
  count: number;
  /** Further server pages exist beyond the loaded ones, so `count` is not the last. */
  hasMoreServer: boolean;
  folders: S3FolderItem[];
  files: S3FileItem[];
  hasPrev: boolean;
  hasNext: boolean;
  goPrev: () => void;
  /** Advances to a loaded page instantly, or fetches the next one and advances only if it arrived. */
  goNext: () => Promise<void>;
  isFetchingNext: boolean;
};

export type UseFileBrowserResult = {
  /** Every loaded page merged and re-sorted — what a picker renders whole. */
  files: S3FileItem[];
  folders: S3FolderItem[];
  /** The browser's view: one server page at a time. */
  page: ListingPage;
  isLoading: boolean;
  /** The raw listing error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  refresh: () => void;
  /** Whether further pages exist — drives the picker's "Load more" control. */
  hasMore: boolean;
  /** Fetches the next listing page. */
  loadMore: () => void;
  /** Disables the picker's "Load more" control mid-fetch. */
  isLoadingMore: boolean;
};

/**
 * Paginated folder listing backed by TanStack Query — every loaded page merged for a
 * picker, and one server page at a time for the browser.
 *
 * Every `DO_NOT_DELETE.txt` is hidden, at any depth, in either bucket
 * — see `isMarkerName`. There is no caller-supplied key: the basename IS
 * the rule, because that is what the two bucket policies deny deletion on.
 */
export function useFileBrowser(bucket: string, prefix?: string): UseFileBrowserResult {
  const queryClient = useQueryClient();
  const normalizedPrefix = prefix ?? '';

  // Every listing opens at its first page. The position is filed under the listing it was
  // taken in and dropped the moment another listing renders (a render-time adjustment, not
  // an effect) — otherwise leaving a folder on page 2 and coming straight back would land
  // on page 2, while coming back by way of a third folder would not.
  const listingId = `${bucket}\u0000${normalizedPrefix}`;
  const [position, setPosition] = useState<{listingId: string; index: number}>({listingId, index: 0});
  if (position.listingId !== listingId) setPosition({listingId, index: 0});
  const rememberedIndex = position.listingId === listingId ? position.index : 0;
  const setIndex = useCallback((index: number) => setPosition({listingId, index}), [listingId]);

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
    // how many pages it costs; pages only accumulate on an explicit Next or "Load more". Resetting to page
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

  // Each page sorted on its own. The remembered position is CLAMPED to the pages that exist
  // rather than trusted: a refetch can shrink the listing under it, and a Next whose page
  // never arrives records a position one past the end — either way the user stays on the
  // last page that is really there, never on a blank one.
  const pages = query.data?.pages ?? [];
  const pageItems = useMemo(
    () =>
      (query.data?.pages ?? []).map((p) => ({
        folders: [...p.folders].sort((a, b) => a.name.localeCompare(b.name)),
        files: p.files.filter((f) => !isMarkerName(f.key)).sort((a, b) => a.name.localeCompare(b.name))
      })),
    [query.data]
  );
  const pageIndex = pages.length === 0 ? rememberedIndex : Math.min(rememberedIndex, pages.length - 1);
  const current = pageItems[pageIndex];
  const hasMoreServer = Boolean(query.hasNextPage);

  const goPrev = useCallback(() => {
    setIndex(Math.max(0, pageIndex - 1));
  }, [pageIndex, setIndex]);

  const goNext = useCallback(async () => {
    // On the last loaded page, fetch forward first; the clamp above is what keeps a page
    // that never arrived from being shown. The advance is from the position held at the
    // CLICK, and only if it is still the position: Prev stays live during the fetch, and a
    // user who went back meanwhile must not be thrown forward when the page lands.
    if (pageIndex === pages.length - 1 && hasMoreServer) await query.fetchNextPage();
    setPosition((p) => (p.listingId === listingId && p.index === pageIndex ? {listingId, index: pageIndex + 1} : p));
  }, [pageIndex, pages.length, hasMoreServer, query, listingId]);

  const page: ListingPage = {
    index: pageIndex,
    count: pages.length,
    hasMoreServer,
    folders: current?.folders ?? [],
    files: current?.files ?? [],
    hasPrev: pageIndex > 0,
    hasNext: pageIndex < pages.length - 1 || hasMoreServer,
    goPrev,
    goNext,
    isFetchingNext: query.isFetchingNextPage
  };

  return {
    files,
    folders,
    page,
    isLoading: query.isPending,
    error: query.error ?? null,
    refresh,
    hasMore: query.hasNextPage,
    loadMore,
    isLoadingMore: query.isFetchingNextPage
  };
}
