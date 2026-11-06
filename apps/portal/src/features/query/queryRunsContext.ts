import {createContext, useContext, type Dispatch, type RefObject, type SetStateAction} from 'react';
import type {QueryRunsEngine} from './useQueryRunsEngine';
import type {MobileHomeTab, MobileQueryView, MobileRun} from './query.types';

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

/** The mobile surface's state, held beside the runs so it outlives the Query page with them. */
export type MobileSurfaceStore = {
  view: MobileQueryView;
  setView: Dispatch<SetStateAction<MobileQueryView>>;
  homeTab: MobileHomeTab;
  setHomeTab: Dispatch<SetStateAction<MobileHomeTab>>;
  run: MobileRun | null;
  setRun: Dispatch<SetStateAction<MobileRun | null>>;
  /** The last token issued this session. */
  tokenRef: RefObject<number>;
};

export const MobileSurfaceContext = createContext<MobileSurfaceStore | null>(null);

/**
 * The mobile query surface's state, from the `QueryRunsProvider` at the signed-in shell.
 *
 * @returns The view, the home list, the run the view submitted, and the token counter.
 * @throws Error when no `QueryRunsProvider` is above the caller.
 *
 * @example
 * const {view, setView} = useMobileSurfaceStore();
 */
export function useMobileSurfaceStore(): MobileSurfaceStore {
  const ctx = useContext(MobileSurfaceContext);
  if (ctx === null) {
    throw new Error('useMobileSurfaceStore must be used within a QueryRunsProvider');
  }
  return ctx;
}
