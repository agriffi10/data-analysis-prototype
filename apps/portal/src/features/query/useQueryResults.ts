import {useCallback, useState} from 'react';
import {useInfiniteQuery} from '@tanstack/react-query';
import {getQueryResults} from './query.service';
import {queryKeys} from './queryKeys';
import {QUERY_RESULTS_PAGE_SIZE} from './query.constants';
import type {QueryColumn, QueryResultPage} from './query.types';

export type UseQueryResultsResult = {
  columns: QueryColumn[];
  /** Current page only — never more than one page is exposed, so only one page is ever mounted in the DOM. */
  rows: string[][];
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
  error: string | null;
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
 */
export function useQueryResults(queryExecutionId: string | null, maxRows?: number): UseQueryResultsResult {
  const pageSize = maxRows ?? QUERY_RESULTS_PAGE_SIZE;

  // The page position is kept PER execution id (SPEC-078 FR-007: each result
  // tab owns its own pager) — switching between executions restores each one's
  // page, mirroring how useInfiniteQuery already caches the pages per id. A new
  // run is a new execution id with no entry yet, so it starts on page 1.
  // Entries are tiny and session-scoped, so never pruned (same stance as
  // useColumnWidths).
  const [pageIndexByExecution, setPageIndexByExecution] = useState<Record<string, number>>({});
  const pageIndex = (queryExecutionId !== null ? pageIndexByExecution[queryExecutionId] : undefined) ?? 0;
  const setPageIndex = useCallback(
    (index: number) => {
      if (queryExecutionId === null) return;
      setPageIndexByExecution((m) => ({...m, [queryExecutionId]: index}));
    },
    [queryExecutionId]
  );

  const query = useInfiniteQuery({
    queryKey: queryKeys.results(queryExecutionId ?? '__none__'),
    enabled: queryExecutionId !== null,
    queryFn: async ({pageParam}): Promise<QueryResultPage> => {
      const result = await getQueryResults({
        queryExecutionId: queryExecutionId as string,
        nextToken: pageParam,
        maxRows: pageSize
      });
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: QueryResultPage) => lastPage.nextToken
  });

  const pages = query.data?.pages ?? [];
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

  const rowCount = current?.rows.length ?? 0;
  const rangeStart = rowCount === 0 ? 0 : pageIndex * pageSize + 1;
  const rangeEnd = rowCount === 0 ? 0 : pageIndex * pageSize + rowCount;

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
    error: query.isError ? (query.error as Error).message : null,
    goPrev,
    goNext: () => {
      void goNext();
    }
  };
}
