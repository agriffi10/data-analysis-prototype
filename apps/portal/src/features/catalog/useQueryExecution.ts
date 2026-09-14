import {useEffect, useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {getQueryStatus, isTerminalState} from './athena.service';
import {apiRetryPolicy} from '../../lib/apiClient';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import {POLL_INTERVAL_MS, MAX_POLL_DURATION_MS} from './catalog.constants';
import type {QueryStatus} from './catalog.types';

/** How a caller treats a status request that has failed. */
export type UseQueryExecutionOptions = {
  /**
   * Disable the query once a status request has failed, so nothing asks about that execution
   * again: not the poll interval, not a reconnect, not a remount.
   *
   * Disabling rather than only ending the interval is the point. A failed query is stale, so a
   * reconnect would refetch it, and an answer landing then would contradict a caller that has
   * already treated the failure as final. Off, the hook keeps polling after a failure until the
   * watch's ceiling, and a later successful poll clears the error.
   */
  stopOnError?: boolean;
  /**
   * Who is watching, beside which execution. A change starts a new watch even when the id stays
   * the same, as when two Data Explorer tabs share one cached execution. It must be stable across
   * renders, because the watch resets during render whenever it changes.
   */
  watchKey?: string;
};

/**
 * What a watch that outlived {@link MAX_POLL_DURATION_MS} reports, shaped for `toUserMessage`.
 *
 * Not a failed request: the execution was still queued or running when it was last read, and
 * the browser has stopped watching it. `params` carries what the sentence names.
 */
export type QueryStillRunning = {
  code: 'QueryStillRunning';
  /** Developer text for the dev-only log. Never rendered. */
  message: string;
  params: {limit: number; queryExecutionId: string};
};

/** One watch of an execution, as its caller reads it. */
export type QueryExecutionWatch = {
  /** The latest status read for the execution. Undefined until the first one arrives. */
  status: QueryStatus | undefined;
  /** A status request that failed after its retry, or null. */
  error: Error | null;
  /** Set once a status read after the ceiling was still queued or running, or null. */
  stillRunning: QueryStillRunning | null;
};

const STILL_RUNNING_CODE = 'QueryStillRunning';

/**
 * Whether `value` is the verdict a watch reports when it outlives its ceiling.
 *
 * For a surface that shows that verdict through an error slot, and has to word, colour or
 * remember it apart from a failure.
 *
 * @param value - Anything a surface holds as its error.
 * @returns True for a {@link QueryStillRunning}.
 */
export function isQueryStillRunning(value: unknown): value is QueryStillRunning {
  return typeof value === 'object' && value !== null && (value as {code?: unknown}).code === STILL_RUNNING_CODE;
}

/**
 * Whether a status read after the ceiling found the execution still queued or running.
 *
 * `readUpdatedAt` is a function so that the render-side caller reads `dataUpdatedAt` only once
 * the ceiling is set. Read earlier, TanStack tracks it and every poll re-renders the host.
 */
function outlived(ceilingAt: number | null, data: QueryStatus | undefined, readUpdatedAt: () => number): boolean {
  return ceilingAt !== null && data !== undefined && !isTerminalState(data.state) && readUpdatedAt() > ceilingAt;
}

/**
 * Polls a running query to a terminal state, for at most one watch's ceiling. Disabled while
 * the id is null.
 *
 * Refetches every POLL_INTERVAL_MS until a terminal state is read. A timer marks
 * MAX_POLL_DURATION_MS, and the first read after that mark decides: a terminal status is
 * delivered as usual, one still queued or running ends the watch with `stillRunning`, and a
 * failed read ends it with `error`. Never the clock alone, because TanStack skips interval
 * fetches while the page is hidden: a tab hidden past the mark decides on its first read after
 * it is shown again. The query keeps running in Athena after the watch ends.
 *
 * The verdict belongs to the watch, not to the execution, so it lives here rather than in the
 * shared cache. A new watch of the same id looks again: after a remount, after the id changes
 * away and back, or when `watchKey` changes.
 *
 * A failed status request is retried as many times as the route's contract allows, which for an
 * idempotent read is once, before the hook reports the error.
 *
 * @param queryExecutionId - The execution to poll, or null to poll nothing.
 * @param options - How a failed status request is treated; see {@link UseQueryExecutionOptions}.
 * @returns The latest status, a failed read, and the verdict that the watch outlived its ceiling.
 *
 * @example
 * const execution = useQueryExecution(executionId, {stopOnError: true});
 * if (execution.stillRunning) settle(toUserMessage(execution.stillRunning));
 */
export function useQueryExecution(
  queryExecutionId: string | null,
  {stopOnError = false, watchKey}: UseQueryExecutionOptions = {}
): QueryExecutionWatch {
  // Reset during render when the id or the watcher changes, so a watch never inherits another's mark.
  const [watch, setWatch] = useState<{id: string | null; key: string | undefined; ceilingAt: number | null}>({
    id: queryExecutionId,
    key: watchKey,
    ceilingAt: null
  });
  const current = watch.id === queryExecutionId && watch.key === watchKey;
  if (!current) setWatch({id: queryExecutionId, key: watchKey, ceilingAt: null});
  const ceilingAt = current ? watch.ceilingAt : null;

  const query = useQuery({
    // A stable placeholder key keeps the hook order constant while disabled.
    queryKey: catalogKeys.execution(queryExecutionId ?? NO_KEY),
    // Evaluated against the query, so it turns false the moment the retries are spent: the
    // status stays pending or success while a retry is in flight. The two ceiling clauses gate
    // the interval, a reconnect and a remount at once, as a stop must.
    enabled: (q) =>
      queryExecutionId !== null &&
      !(stopOnError && q.state.status === 'error') &&
      !outlived(ceilingAt, q.state.data, () => q.state.dataUpdatedAt) &&
      !(ceilingAt !== null && q.state.status === 'error' && q.state.errorUpdatedAt > ceilingAt),
    retry: apiRetryPolicy('athena.status'),
    queryFn: async (): Promise<QueryStatus> => {
      const result = await getQueryStatus(queryExecutionId as string);
      return unwrap(result);
    },
    refetchInterval: (q) => (q.state.data && isTerminalState(q.state.data.state) ? false : POLL_INTERVAL_MS)
  });

  const settled = query.data !== undefined && isTerminalState(query.data.state);
  useEffect(() => {
    if (queryExecutionId === null || settled) return;
    const timer = setTimeout(() => {
      const at = Date.now();
      setWatch((w) => (w.id === queryExecutionId && w.key === watchKey ? {...w, ceilingAt: at} : w));
    }, MAX_POLL_DURATION_MS);
    return () => clearTimeout(timer);
  }, [queryExecutionId, watchKey, settled]);

  const expired = outlived(ceilingAt, query.data, () => query.dataUpdatedAt);
  const stillRunning = useMemo(
    (): QueryStillRunning | null =>
      expired && queryExecutionId !== null
        ? {
            code: STILL_RUNNING_CODE,
            message: `Execution ${queryExecutionId} was still running when the watch reached its ceiling.`,
            params: {limit: MAX_POLL_DURATION_MS / 60_000, queryExecutionId}
          }
        : null,
    [expired, queryExecutionId]
  );

  return {status: query.data, error: query.error, stillRunning};
}
