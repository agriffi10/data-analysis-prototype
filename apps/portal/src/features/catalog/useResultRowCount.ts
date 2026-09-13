import {useQuery} from '@tanstack/react-query';
import {getQueryResults, getQueryRowCount} from './athena.service';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import {ROW_COUNT_PAGE_SIZE, ROW_COUNT_PENDING_DELAYS_MS} from './catalog.constants';

export type UseRowCountResult = {
  /** Exact total once known; null while still counting (or after a failed request). */
  total: number | null;
  /** The count is still being worked out. */
  isCounting: boolean;
};

/**
 * Resolves after `ms`, or rejects as soon as `signal` aborts — so leaving the page, or moving to
 * another execution, ends a wait between asks instead of letting it ask again afterwards.
 */
function waitOrAbort(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error('aborted'));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new Error('aborted'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal.addEventListener('abort', onAbort, {once: true});
  });
}

/** Counts every row by fetching every page. Exact, and a billed API call per 1,000 rows. */
async function walkEveryPage(queryExecutionId: string, signal: AbortSignal): Promise<number> {
  let total = 0;
  let nextToken: string | undefined;
  do {
    if (signal.aborted) throw new Error('aborted');
    const page = unwrap(await getQueryResults({queryExecutionId, nextToken, maxRows: ROW_COUNT_PAGE_SIZE}));
    total += page.rows.length;
    nextToken = page.nextToken;
  } while (nextToken);
  return total;
}

/**
 * A succeeded query's exact total row count — never an estimate, never capped.
 *
 * Athena's own count comes first: one API call reads the rows a SELECT returned from Athena's
 * runtime statistics, scanning nothing and shipping no row. Counting by fetching every page is
 * NOT free — each page is a billed API call that ships 1,000 rows only to be counted, so a
 * ten-million-row result would be ten thousand of them. The walk therefore runs only where
 * Athena does not count: a statement that is not a SELECT (a `SHOW`, a `DESCRIBE`, an
 * `EXPLAIN`, whose outputs are small), or a SELECT whose count Athena still has not reported
 * after `ROW_COUNT_PENDING_DELAYS_MS`, which it documents can happen.
 *
 * Pass the succeeded execution id, or null when there is nothing to count (an in-flight or
 * failed query, or a statement with no result set). The total is cached per execution id
 * (staleTime: Infinity), so switching back to a counted tab shows it at once; a new run is a new
 * id. Never surfaces an error: a failed request leaves `total` null, and a failed ask does not
 * fall back to the walk, so a broken route shows as a missing total rather than silently
 * restoring the cost.
 */
export function useResultRowCount(queryExecutionId: string | null): UseRowCountResult {
  const query = useQuery<number>({
    queryKey: catalogKeys.rowCount(queryExecutionId ?? NO_KEY),
    enabled: queryExecutionId !== null,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    queryFn: async ({signal}): Promise<number> => {
      const id = queryExecutionId as string;
      for (let asked = 0; ; asked++) {
        if (signal.aborted) throw new Error('aborted');
        const answer = unwrap(await getQueryRowCount(id));
        if (answer.rowCount !== null) return answer.rowCount;
        if (!answer.pending || asked === ROW_COUNT_PENDING_DELAYS_MS.length) break;
        await waitOrAbort(ROW_COUNT_PENDING_DELAYS_MS[asked], signal);
      }
      return walkEveryPage(id, signal);
    }
  });

  return {
    total: query.data ?? null,
    isCounting: queryExecutionId !== null && query.data === undefined
  };
}
