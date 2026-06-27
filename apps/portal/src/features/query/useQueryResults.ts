import { useCallback, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { getQueryResults } from './query.service';
import { queryKeys } from './queryKeys';
import { QUERY_RESULTS_PAGE_SIZE } from './query.constants';
import type { QueryColumn, QueryResultPage } from './query.types';

export type UseQueryResultsResult = {
  // Current page only — never more than one page (≤ pageSize rows) is exposed,
  // so only one page is ever mounted in the DOM (SPEC-038 FR-002).
  columns: QueryColumn[];
  rows: string[][];
  pageIndex: number; // 0-based
  // 1-based inclusive row range of the current page; 0/0 when empty.
  rangeStart: number;
  rangeEnd: number;
  // Total across all loaded pages (drives the status bar count); the definitive
  // total is only known once the last page is loaded (Athena gives no up-front
  // count), exposed as totalRowCount — null until then (FR-002).
  loadedRowCount: number;
  totalRowCount: number | null;
  hasPrev: boolean;
  hasNext: boolean;
  hasMoreServer: boolean; // last loaded page has a NextToken (status bar "+")
  isPending: boolean; // first page loading
  isFetchingNext: boolean;
  isError: boolean;
  error: string | null;
  goPrev: () => void;
  goNext: () => void;
};

// SPEC-038: Prev/Next pager over a succeeded query's results. Built on
// useInfiniteQuery (keyed by executionId; each page = QUERY_RESULTS_PAGE_SIZE data
// rows threading the Athena NextToken), so fetched pages stay cached and paging
// back is instant. A local pageIndex selects which cached page is shown — Next
// fetches forward only when the next page isn't already cached; Prev is always
// served from cache (FR-002/FR-003). Disabled while the id is null.
export function useQueryResults(queryExecutionId: string | null, maxRows?: number): UseQueryResultsResult {
  const pageSize = maxRows ?? QUERY_RESULTS_PAGE_SIZE;
  const [pageIndex, setPageIndex] = useState(0);

  // A new query (new execution id) resets the pager to page 1. Done as a
  // render-phase reset (track the previous id) rather than an effect — React's
  // documented pattern for "reset state when a prop changes", and it avoids the
  // extra render an effect would cause.
  const [prevExecutionId, setPrevExecutionId] = useState(queryExecutionId);
  if (queryExecutionId !== prevExecutionId) {
    setPrevExecutionId(queryExecutionId);
    setPageIndex(0);
  }

  const query = useInfiniteQuery({
    queryKey: queryKeys.results(queryExecutionId ?? '__none__'),
    enabled: queryExecutionId !== null,
    queryFn: async ({ pageParam }): Promise<QueryResultPage> => {
      const result = await getQueryResults({
        queryExecutionId: queryExecutionId as string,
        nextToken: pageParam,
        maxRows: pageSize,
      });
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: QueryResultPage) => lastPage.nextToken,
  });

  const pages = query.data?.pages ?? [];
  const current = pages[pageIndex];
  const lastLoaded = pages[pages.length - 1];

  const hasMoreServer = Boolean(lastLoaded?.nextToken);
  const loadedRowCount = pages.reduce((n, p) => n + p.rows.length, 0);

  const goPrev = useCallback(() => {
    setPageIndex((i) => Math.max(0, i - 1));
  }, []);

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
  }, [pageIndex, pages.length, current?.nextToken, query]);

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
    },
  };
}
