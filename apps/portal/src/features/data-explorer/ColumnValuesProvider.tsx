import {useEffect, useMemo, useState, useSyncExternalStore, type ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {useAuth} from '../auth';
import {isTerminalState} from '../catalog/athena.service';
import {useQueryExecution} from '../catalog/useQueryExecution';
import {
  ColumnValuesContext,
  createActions,
  createListingStore,
  type ColumnValuesContextValue
} from './columnValuesStore';
import type {QueryStatus} from '../catalog/catalog.types';

/** The ledger and the tabs, as the workspace holds them. */
export type ColumnValuesProviderProps = {
  activeTabId: string | null;
  /** A tab's bytes-by-execution ledger, read at the moment a listing is linked or settles. */
  ledgerOf: (tabId: string) => Readonly<Record<string, number>> | undefined;
  recordScan: (tabId: string, queryExecutionId: string, bytesScanned: number) => void;
  /** A tab's running total, for the picker's cost line. */
  totalOf: (tabId: string) => number;
  children: ReactNode;
};

/**
 * Watches one listing execution until it settles, then hands the status to the provider.
 *
 * A component rather than a hook in the picker, because it must outlive the picker: an Athena
 * execution is billed whether or not anyone is still looking, so the scan is recorded after the
 * dialog that asked for it has closed.
 */
function ListingWatcher({
  executionId,
  generation,
  onSettled,
  onWatchEnded
}: {
  executionId: string;
  generation: number;
  onSettled: (executionId: string, status: QueryStatus) => void;
  onWatchEnded: (executionId: string, error: unknown) => void;
}) {
  const watch = useQueryExecution(executionId, {watchKey: `values:${executionId}:${generation}`});
  const settled = watch.status && isTerminalState(watch.status.state) ? watch.status : null;
  const ended = watch.stillRunning ?? watch.error;
  useEffect(() => {
    if (settled) onSettled(executionId, settled);
    else if (ended) onWatchEnded(executionId, ended);
  }, [settled, ended, executionId, onSettled, onWatchEnded]);
  return null;
}

/**
 * Owns every column-values listing in the Data Explorer, and bills each to the tab that asked.
 *
 * Mounted around the whole workspace — above the source picker, not inside the tab panel — so
 * choosing New tab does not unmount the watch of a listing still running.
 *
 * **A listing is started imperatively and never OBSERVED**, and that is what keeps a catalog
 * change from starting one. Its start is cached under the exploration's execution keys, so an
 * eviction drops it with the explorations over that table; but `resetQueries` refetches only
 * an entry something observes, so a dropped listing starts again only when a picker next asks.
 * The watch is on the execution's own status key, which an eviction does not touch, so an
 * execution caught mid-run is still recorded once.
 *
 * **The start's bookkeeping happens inside its query function.** An eviction during the start
 * request cancels the caller's promise, but the function runs on; registering the execution
 * there is what keeps a started, billed execution watched and recorded when that happens.
 */
export function ColumnValuesProvider({
  activeTabId,
  ledgerOf,
  recordScan,
  totalOf,
  children
}: ColumnValuesProviderProps) {
  const queryClient = useQueryClient();
  const {user} = useAuth();
  const username = user?.username ?? '';
  const [store] = useState(() => createListingStore({ledgerOf, recordScan, username, queryClient}));
  const registry = useSyncExternalStore(store.subscribe, store.get);

  // The ledger and the recorder change identity with every tab edit, and the actions that use
  // them run from promises; the store is handed the latest after each render.
  useEffect(() => {
    store.setEnv({ledgerOf, recordScan, username, queryClient});
  });

  const [actions] = useState(() => createActions(store));

  const value = useMemo<ColumnValuesContextValue>(
    () => ({store, activeTabId, totalOf, request: actions.request, retryExecution: actions.retryExecution}),
    [store, activeTabId, totalOf, actions]
  );

  const watching = Object.entries(registry.executions).filter(([, entry]) => entry.status === 'watching');
  return (
    <ColumnValuesContext.Provider value={value}>
      {children}
      {watching.map(([id, entry]) => (
        <ListingWatcher
          key={`${id}:${entry.watchGeneration}`}
          executionId={id}
          generation={entry.watchGeneration}
          onSettled={actions.settle}
          onWatchEnded={actions.endWatch}
        />
      ))}
    </ColumnValuesContext.Provider>
  );
}
