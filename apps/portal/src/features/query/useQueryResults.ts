import { useInfiniteQuery } from '@tanstack/react-query';
import { getQueryResults } from './query.service';
import { queryKeys } from './queryKeys';
import type { QueryResultPage } from './query.types';

// SPEC-034 FR-004: paginated results for a succeeded query, via useInfiniteQuery
// (each page is a GetQueryResults call threading NextToken). Disabled while the id
// is null. The page size (maxRows) and the Prev/Next pager UX are set by SPEC-038
// (20 rows/page); this hook just provides the paginated fetch.
export function useQueryResults(
  queryExecutionId: string | null,
  maxRows?: number,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.results(queryExecutionId ?? '__none__'),
    enabled: queryExecutionId !== null,
    queryFn: async ({ pageParam }): Promise<QueryResultPage> => {
      const result = await getQueryResults({
        queryExecutionId: queryExecutionId as string,
        nextToken: pageParam,
        maxRows,
      });
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage: QueryResultPage) => lastPage.nextToken,
  });
}
