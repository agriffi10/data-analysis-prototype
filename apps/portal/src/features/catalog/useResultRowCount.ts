import {useQuery} from '@tanstack/react-query';
import {getQueryResults} from './athena.service';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import {ROW_COUNT_PAGE_SIZE} from './catalog.constants';

export type UseRowCountResult = {
  /** Exact total once the walk finishes; null while still counting (or on a failed page). */
  total: number | null;
  /** The background walk is in progress. */
  isCounting: boolean;
};

/**
 * Counts a succeeded query's total result rows by walking every GetQueryResults
 * page in the background. Athena's GetQueryResults calls are free — no
 * extra bytes scanned — so this is the exact total (no ceiling, no "+"), without a
 * COUNT(*) wrapper. Uses the largest page size to minimize round-trips and a
 * separate query key from the visible pager, so counting never disturbs the
 * 20/page cache.
 *
 * Pass the succeeded execution id, or null when there is nothing to count (an
 * in-flight/failed query, or a DDL/no-result statement) — the walk is disabled.
 * The total is cached per execution id (staleTime: Infinity) so tab-switching back
 * to a counted result shows it instantly; a new run recomputes under a fresh id.
 * Never surfaces an error: a failed page throws inside the queryFn and leaves
 * `total` null (pending), so the status bar falls back to the loaded-count form.
 */
export function useResultRowCount(queryExecutionId: string | null): UseRowCountResult {
  const query = useQuery<number>({
    queryKey: catalogKeys.rowCount(queryExecutionId ?? NO_KEY),
    enabled: queryExecutionId !== null,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    queryFn: async ({signal}): Promise<number> => {
      let total = 0;
      let nextToken: string | undefined;
      do {
        if (signal.aborted) throw new Error('aborted');
        const result = await getQueryResults({
          queryExecutionId: queryExecutionId as string,
          nextToken,
          maxRows: ROW_COUNT_PAGE_SIZE
        });
        const page = unwrap(result);
        total += page.rows.length;
        nextToken = page.nextToken;
      } while (nextToken);
      return total;
    }
  });

  return {
    total: query.data ?? null,
    isCounting: queryExecutionId !== null && query.data === undefined
  };
}
