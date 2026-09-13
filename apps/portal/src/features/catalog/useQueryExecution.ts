import {useEffect, useRef} from 'react';
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
   * already treated the failure as final. Off, the hook keeps polling after a failure, and a
   * later successful poll clears the error.
   */
  stopOnError?: boolean;
};

/**
 * Polls a running query to a terminal state. Disabled while the id is null.
 * Refetches every POLL_INTERVAL_MS until a terminal state is observed, or
 * until MAX_POLL_DURATION_MS as a guard against a stuck execution (the query
 * keeps running server-side — only the UI polling stops).
 *
 * A failed status request is retried as many times as the route's contract allows, which for an
 * idempotent read is once, before the hook reports the error.
 *
 * @param queryExecutionId - The execution to poll, or null to poll nothing.
 * @param options - How a failed status request is treated; see {@link UseQueryExecutionOptions}.
 * @returns The TanStack query over the execution's status.
 *
 * @example
 * const execution = useQueryExecution(executionId, {stopOnError: true});
 * if (execution.error) settle(toUserText(execution.error));
 */
export function useQueryExecution(
  queryExecutionId: string | null,
  {stopOnError = false}: UseQueryExecutionOptions = {}
) {
  // When polling for the current id started (max-duration guard). Set in an
  // effect, not during render; 0 = no query in flight.
  const startedAtRef = useRef(0);
  useEffect(() => {
    startedAtRef.current = queryExecutionId !== null ? Date.now() : 0;
  }, [queryExecutionId]);

  return useQuery({
    // A stable placeholder key keeps the hook order constant while disabled.
    queryKey: catalogKeys.execution(queryExecutionId ?? NO_KEY),
    // Evaluated against the query, so it turns false the moment the retries are spent: the
    // status stays pending or success while a retry is in flight.
    enabled: (query) => queryExecutionId !== null && !(stopOnError && query.state.status === 'error'),
    retry: apiRetryPolicy('athena.status'),
    queryFn: async (): Promise<QueryStatus> => {
      const result = await getQueryStatus(queryExecutionId as string);
      return unwrap(result);
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && isTerminalState(data.state)) return false;
      const startedAt = startedAtRef.current;
      if (startedAt !== 0 && Date.now() - startedAt > MAX_POLL_DURATION_MS) {
        return false;
      }
      return POLL_INTERVAL_MS;
    }
  });
}
