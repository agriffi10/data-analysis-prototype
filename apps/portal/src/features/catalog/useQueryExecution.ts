import {useEffect, useRef} from 'react';
import {useQuery} from '@tanstack/react-query';
import {getQueryStatus, isTerminalState} from './athena.service';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import {POLL_INTERVAL_MS, MAX_POLL_DURATION_MS} from './catalog.constants';
import type {QueryStatus} from './catalog.types';

/**
 * Polls a running query to a terminal state. Disabled while the id is null.
 * Refetches every POLL_INTERVAL_MS until a terminal state is observed, or
 * until MAX_POLL_DURATION_MS as a guard against a stuck execution (the query
 * keeps running server-side — only the UI polling stops).
 */
export function useQueryExecution(queryExecutionId: string | null) {
  // When polling for the current id started (max-duration guard). Set in an
  // effect, not during render; 0 = no query in flight.
  const startedAtRef = useRef(0);
  useEffect(() => {
    startedAtRef.current = queryExecutionId !== null ? Date.now() : 0;
  }, [queryExecutionId]);

  return useQuery({
    // A stable placeholder key keeps the hook order constant while disabled.
    queryKey: catalogKeys.execution(queryExecutionId ?? NO_KEY),
    enabled: queryExecutionId !== null,
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
