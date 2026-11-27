import {useCallback, useState} from 'react';
import {useInfiniteQuery} from '@tanstack/react-query';
import {getQueryResults} from './athena.service';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {QueryColumn, QueryResultPage} from './catalog.types';

export type UseQueryResultsResult = {
  columns: QueryColumn[];
  /**
   * Current page only — never more than one page is exposed, so only one page is ever
   * mounted in the DOM. A `null` cell is SQL NULL, `''` an empty string.
   */
  rows: (string | null)[][];
  /** 0-based. */
  pageIndex: number;
  /** 1-based inclusive start of the current page's row range; 0 when empty. */
  rangeStart: number;
  /** 1-based inclusive end of the current page's row range; 0 when empty. */
  rangeEnd: number;
  /** Total across all loaded pages (drives the status bar count). */
  loadedRowCount: number;
  /** Definitive total, known only once the last page is loaded (Athena gives no up-front count); null until then. */
  totalRowCount: number | null;
  hasPrev: boolean;
  hasNext: boolean;
  /** Last loaded page has a NextToken (status bar "+"). */
  hasMoreServer: boolean;
  /** First page loading. */
  isPending: boolean;
  isFetchingNext: boolean;
  isError: boolean;
  /**
   * The read failed before any page loaded — the one error that stands in for the answer. A failed
   * RE-read keeps the pages it had (an empty result included), and `isError` is true for it too.
   */
  isLoadError: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  goPrev: () => void;
  goNext: () => void;
};

/**
 * Prev/Next pager over a succeeded query's results. Built on useInfiniteQuery
 * (keyed by executionId; each page threads the Athena NextToken), so fetched
 * pages stay cached and paging back is instant. A local pageIndex selects
 * which cached page is shown — Next fetches forward only when the next page
 * isn't already cached; Prev is always served from cache. Disabled while the
 * id is null.
 *
 * `pageSize` is the workspace-global "Rows per page" value. The
 * query is keyed by it, so a size change drops stale-sized cached pages and
 * refetches page 1 at the new size for every result tab.
 *
 * The pages never go stale: an execution's rows cannot change, and a stale infinite query reads
 * every page it holds again each time the result is shown, eight requests to come back to page
 * eight. A read that failed is still read again, since a failed query is refetched whatever its
 * stale time.
 */
export function useQueryResults(queryExecutionId: string | null, pageSize: number): UseQueryResultsResult {
  // The page position is kept PER execution id (each result
  // tab owns its own pager) — switching between executions restores each one's
  // page, mirroring how useInfiniteQuery already caches the pages per id. A new
  // run is a new execution id with no entry yet, so it starts on page 1.
  // Entries are tiny and session-scoped, so never pruned (same stance as
  // useColumnWidths).
  const [pageIndexByExecution, setPageIndexByExecution] = useState<Record<string, number>>({});

  // a page-size change resets EVERY execution to page 1 —
  // remembered positions were positions in the old page geometry. Render-time
  // state adjustment (the React "derive state from props" pattern), so the
  // reset lands in the same render as the new size.
  const [prevPageSize, setPrevPageSize] = useState(pageSize);
  if (prevPageSize !== pageSize) {
    setPrevPageSize(pageSize);
    setPageIndexByExecution({});
  }

  const rememberedPageIndex = (queryExecutionId !== null ? pageIndexByExecution[queryExecutionId] : undefined) ?? 0;
  const setPageIndex = useCallback(
    (index: number) => {
      if (queryExecutionId === null) return;
      setPageIndexByExecution((m) => ({...m, [queryExecutionId]: index}));
    },
    [queryExecutionId]
  );

  const query = useInfiniteQuery({
    queryKey: catalogKeys.results(queryExecutionId ?? NO_KEY, pageSize),
    enabled: queryExecutionId !== null,
    staleTime: Infinity,
    queryFn: async ({pageParam}): Promise<QueryResultPage> => {
      const result = await getQueryResults({
        queryExecutionId: queryExecutionId as string,
        nextToken: pageParam,
        maxRows: pageSize
      });
      return unwrap(result);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: QueryResultPage) => lastPage.nextToken
  });

  const pages = query.data?.pages ?? [];

  // The remembered position can outlive the pages it pointed at: an execution nobody is
  // looking at loses its cached pages once `gcTime` elapses (switch tabs, come back), and
  // the refetch starts again from page 1. Read raw, that index selects a page that is no
  // longer there — and an undefined page is indistinguishable from an empty one, so a
  // result WITH rows renders as "No rows returned". Clamped only while pages exist; with
  // none loaded yet the position is still the right one to restore to.
  const pageIndex = pages.length === 0 ? rememberedPageIndex : Math.min(rememberedPageIndex, pages.length - 1);
  const current = pages[pageIndex];
  const lastLoaded = pages[pages.length - 1];

  const hasMoreServer = Boolean(lastLoaded?.nextToken);
  const loadedRowCount = pages.reduce((n, p) => n + p.rows.length, 0);

  const goPrev = useCallback(() => {
    setPageIndex(Math.max(0, pageIndex - 1));
  }, [pageIndex, setPageIndex]);

  const goNext = useCallback(async () => {
    // Next page already cached → just advance (instant, no refetch).
    if (pageIndex < pages.length - 1) {
      setPageIndex(pageIndex + 1);
      return;
    }
    // On the last loaded page: fetch forward via NextToken, then advance only if
    // a new page was actually appended (don't advance on a failed fetch).
    if (current?.nextToken) {
      const res = await query.fetchNextPage();
      if ((res.data?.pages.length ?? 0) > pages.length) {
        setPageIndex(pageIndex + 1);
      }
    }
  }, [pageIndex, setPageIndex, pages.length, current?.nextToken, query]);

  // Row numbering derives from the ACTUAL loaded page lengths, not
  // pageIndex * pageSize: at the 1000 cap the first page nets 999 data rows
  // (Athena's MaxResults ceiling absorbs the header row, see getQueryResults),
  // so assuming uniform pages would drift the numbering.
  const rowCount = current?.rows.length ?? 0;
  const rowsBefore = pages.slice(0, pageIndex).reduce((n, p) => n + p.rows.length, 0);
  const rangeStart = rowCount === 0 ? 0 : rowsBefore + 1;
  const rangeEnd = rowCount === 0 ? 0 : rowsBefore + rowCount;

  return {
    columns: current?.columns ?? pages[0]?.columns ?? [],
    rows: current?.rows ?? [],
    pageIndex,
    rangeStart,
    rangeEnd,
    loadedRowCount,
    totalRowCount: hasMoreServer ? null : loadedRowCount,
    hasPrev: pageIndex > 0,
    hasNext: pageIndex < pages.length - 1 || Boolean(current?.nextToken),
    hasMoreServer,
    isPending: query.isPending,
    isFetchingNext: query.isFetchingNextPage,
    isError: query.isError,
    isLoadError: query.isLoadingError,
    error: query.error ?? null,
    goPrev,
    goNext: () => {
      void goNext();
    }
  };
}
