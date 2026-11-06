import {createContext, useContext} from 'react';
import type {QueryRunsEngine} from './useQueryRunsEngine';

/** What `QueryRunsProvider` hands down: the engine without its pollers, which the provider renders. */
export type QueryRunsContextValue = Omit<QueryRunsEngine, 'pollers'>;

export const QueryRunsContext = createContext<QueryRunsContextValue | null>(null);

/**
 * The Query workspace's run engine, from the `QueryRunsProvider` at the signed-in shell.
 *
 * @returns The run state and its operations, keyed by tab id.
 * @throws Error when no `QueryRunsProvider` is above the caller.
 *
 * @example
 * const {runs, submitBatch} = useQueryRuns();
 */
export function useQueryRuns(): QueryRunsContextValue {
  const ctx = useContext(QueryRunsContext);
  if (ctx === null) {
    throw new Error('useQueryRuns must be used within a QueryRunsProvider');
  }
  return ctx;
}
