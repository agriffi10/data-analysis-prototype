import {useQuery} from '@tanstack/react-query';
import {getQueryResults} from './query.service';
import {queryKeys} from './queryKeys';
import {ROW_COUNT_CEILING, ROW_COUNT_PAGE_SIZE} from './query.constants';

export type UseRowCountResult = {
  /** Exact total once the walk finishes; null while still counting (or on a failed page). */
  total: number | null;
  /** The background walk is in progress. */
  isCounting: boolean;
  /** Stopped at ROW_COUNT_CEILING → the stat should read "{ceiling}+". */
  atCeiling: boolean;
};

type CountResult = {total: number; atCeiling: boolean};

/**
 * Counts a succeeded query's total result rows by walking every GetQueryResults
 * page in the background (SPEC-080). Athena's GetQueryResults calls are free — no
 * extra bytes scanned — so this is exact without a COUNT(*) wrapper. Uses a large
 * page size to minimize round-trips and a separate query key from the visible
 * pager, so counting never disturbs the 20/page cache.
 *
 * Pass the succeeded execution id, or null when there is nothing to count (an
 * in-flight/failed query, or a DDL/no-result statement) — the walk is disabled.
 * The total is cached per execution id (staleTime: Infinity) so tab-switching back
 * to a counted result shows it instantly; a new run recomputes under a fresh id.
 * Never surfaces an error: a failed page throws inside the queryFn and leaves
 * `total` null (pending), so the status bar falls back to the loaded-count form.
 */
export function useResultRowCount(queryExecutionId: string | null): UseRowCountResult {
  const query = useQuery<CountResult>({
    queryKey: queryKeys.rowCount(queryExecutionId ?? '__none__'),
    enabled: queryExecutionId !== null,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    queryFn: async ({signal}): Promise<CountResult> => {
      let total = 0;
      let nextToken: string | undefined;
      do {
        if (signal.aborted) throw new Error('aborted');
        const result = await getQueryResults({
          queryExecutionId: queryExecutionId as string,
          nextToken,
          maxRows: ROW_COUNT_PAGE_SIZE
        });
        if (!result.success) throw new Error(result.error.message);
        total += result.data.rows.length;
        if (total >= ROW_COUNT_CEILING) {
          return {total: ROW_COUNT_CEILING, atCeiling: true};
        }
        nextToken = result.data.nextToken;
      } while (nextToken);
      return {total, atCeiling: false};
    }
  });

  return {
    total: query.data?.total ?? null,
    isCounting: queryExecutionId !== null && !query.data,
    atCeiling: query.data?.atCeiling ?? false
  };
}
