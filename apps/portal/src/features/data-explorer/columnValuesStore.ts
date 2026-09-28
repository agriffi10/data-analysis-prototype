import {createContext} from 'react';
import {isCancelledError, type QueryClient, type QueryKey} from '@tanstack/react-query';
import {getQueryResults, runQuery} from '../catalog/athena.service';
import {apiRetryPolicy} from '../../lib/apiClient';
import {unwrap} from '../../lib/serviceResult';
import type {ServiceResult} from '../../types/service.types';
import {EXPLORER_FILTER_VALUES_MAX} from './dataExplorer.constants';
import {explorerKeys} from './explorerKeys';
import type {QueryStatus} from '../catalog/catalog.types';
import type {ColumnValueCount} from './dataExplorer.types';

export type ExecutionEntry = {
  status: 'watching' | 'reading' | 'ready' | 'error';
  startKey: QueryKey;
  /** Every tab that asked for this execution; each is billed for it once. */
  tabIds: string[];
  /** Bumped by a retry, so a watch that ended starts again as a new one. */
  watchGeneration: number;
  /** The terminal status, once the watch saw one. */
  terminal: QueryStatus | null;
  entries: ColumnValueCount[];
  valueCount: number;
  error: unknown;
};

export type KeyEntry =
  | {status: 'starting'}
  | {status: 'resolved'; executionId: string; fromCache: boolean}
  | {status: 'error'; error: unknown};

export type Registry = {keys: Record<string, KeyEntry>; executions: Record<string, ExecutionEntry>};

/** What the listing actions read from the workspace, refreshed after every render. */
export type ListingEnv = {
  ledgerOf: (tabId: string) => Readonly<Record<string, number>> | undefined;
  recordScan: (tabId: string, queryExecutionId: string, bytesScanned: number) => void;
  username: string;
  queryClient: QueryClient;
};

/**
 * The registry of listings, as an external store the provider and every picker subscribe to.
 *
 * External rather than React state because the actions that change it run from promises — a
 * start's query function, a results read — long after the render that began them. The workspace's
 * ledger and recorder ride on it too, refreshed by the provider after each render, for the same
 * reason.
 */
export type ListingStore = {
  get: () => Registry;
  set: (update: (registry: Registry) => Registry) => void;
  subscribe: (listener: () => void) => () => void;
  env: () => ListingEnv;
  setEnv: (env: ListingEnv) => void;
};

/**
 * Creates an empty registry.
 *
 * @param initial - The workspace's ledger, recorder, user and query client at mount.
 * @returns The store.
 */
export function createListingStore(initial: ListingEnv): ListingStore {
  let registry: Registry = {keys: {}, executions: {}};
  let env = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => registry,
    set: (update) => {
      registry = update(registry);
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    env: () => env,
    setEnv: (next) => {
      env = next;
    }
  };
}

export type ColumnValuesContextValue = {
  store: ListingStore;
  activeTabId: string | null;
  totalOf: (tabId: string) => number;
  request: (tabId: string, scope: readonly [string, string, string], sql: string) => void;
  retryExecution: (executionId: string) => void;
};

export const ColumnValuesContext = createContext<ColumnValuesContextValue | null>(null);

/** The spec's listing key, `{tabId, valuesSql}`, as one string. */
export const keyOf = (tabId: string, sql: string) => `${tabId}\n${sql}`;

function withExecution(registry: Registry, id: string, update: (entry: ExecutionEntry) => ExecutionEntry): Registry {
  const entry = registry.executions[id];
  return entry ? {...registry, executions: {...registry.executions, [id]: update(entry)}} : registry;
}

function withKey(registry: Registry, key: string, entry: KeyEntry): Registry {
  return {...registry, keys: {...registry.keys, [key]: entry}};
}

/**
 * Reads a succeeded values listing, following `nextToken` until it holds the cap or there is none.
 *
 * A failed page fails the whole listing: a partial list would be cut short without saying so,
 * under a note that claims it is the most common values.
 *
 * @param queryExecutionId - The succeeded listing execution.
 * @returns Its entries, most common first, and how many values the column has in all.
 */
export async function readValuesPages(
  queryExecutionId: string
): Promise<ServiceResult<{entries: ColumnValueCount[]; valueCount: number}>> {
  const entries: ColumnValueCount[] = [];
  let valueCount = 0;
  let nextToken: string | undefined;
  do {
    const page = await getQueryResults({queryExecutionId, nextToken, maxRows: EXPLORER_FILTER_VALUES_MAX});
    if (!page.success) return page;
    for (const row of page.data.rows) {
      if (entries.length === 0) valueCount = Number(row[2] ?? 0);
      entries.push({value: row[0] ?? null, count: Number(row[1] ?? 0)});
    }
    nextToken = page.data.nextToken;
  } while (nextToken !== undefined && entries.length < EXPLORER_FILTER_VALUES_MAX);
  return {success: true, data: {entries: entries.slice(0, EXPLORER_FILTER_VALUES_MAX), valueCount}};
}

/**
 * The operations on the registry: requesting a listing, and what a watch reports back.
 *
 * Built once per provider, so the watcher's callbacks keep one identity and its effect runs on a
 * change of status, never on a re-render.
 *
 * @param store - The provider's store.
 * @returns The actions.
 */
export function createActions(store: ListingStore) {
  const register = (id: string, startKey: QueryKey) =>
    store.set((registry) =>
      registry.executions[id]
        ? registry
        : {
            ...registry,
            executions: {
              ...registry.executions,
              [id]: {
                status: 'watching',
                startKey,
                tabIds: [],
                watchGeneration: 0,
                terminal: null,
                entries: [],
                valueCount: 0,
                error: null
              }
            }
          }
    );

  // `fresh` is a new showing: the cache-hit path asks the ledger again, so a listing reopened
  // after it was recorded says it scanned nothing. The start's own two links leave a key already
  // resolved to this execution alone.
  const link = (key: string, tabId: string, id: string, fresh: boolean) => {
    const current = store.get().keys[key];
    const execution = store.get().executions[id];
    if (!execution) return;
    if (fresh || current?.status !== 'resolved' || current.executionId !== id) {
      const fromCache = store.env().ledgerOf(tabId)?.[id] !== undefined;
      store.set((registry) => withKey(registry, key, {status: 'resolved', executionId: id, fromCache}));
    }
    if (!execution.tabIds.includes(tabId)) {
      store.set((registry) => withExecution(registry, id, (entry) => ({...entry, tabIds: [...entry.tabIds, tabId]})));
    }
    // A tab asking for a listing that has already settled is billed for it now, as an exploration
    // shown in a second tab is.
    const bytes = execution.terminal?.dataScannedBytes;
    if (execution.terminal) store.env().recordScan(tabId, id, bytes ?? 0);
  };

  const read = (id: string) => {
    store.set((registry) => withExecution(registry, id, (entry) => ({...entry, status: 'reading', error: null})));
    void readValuesPages(id).then((result) =>
      store.set((registry) =>
        withExecution(registry, id, (entry) =>
          result.success
            ? {...entry, status: 'ready', entries: result.data.entries, valueCount: result.data.valueCount}
            : {...entry, status: 'error', error: result.error}
        )
      )
    );
  };

  const start = (key: string, tabId: string, startKey: QueryKey, sql: string) => {
    store.set((registry) => withKey(registry, key, {status: 'starting'}));
    const {queryClient, username} = store.env();
    queryClient
      .fetchQuery({
        queryKey: startKey,
        staleTime: Infinity,
        gcTime: Infinity,
        // Starting a query is not idempotent: a retry is a second execution and a second bill.
        retry: apiRetryPolicy('athena.start'),
        queryFn: async (): Promise<string> => {
          const id = unwrap(await runQuery({sql, username})).queryExecutionId;
          register(id, startKey);
          link(key, tabId, id, false);
          return id;
        }
      })
      .then(
        (id) => link(key, tabId, id, false),
        (error: unknown) => {
          // Cancelled by an eviction during the start: the query function still registers what it
          // started, and asking again here would start a second execution for one gesture.
          if (isCancelledError(error)) return;
          store.set((registry) => withKey(registry, key, {status: 'error', error}));
        }
      );
  };

  return {
    request: (tabId: string, scope: readonly [string, string, string], sql: string) => {
      const key = keyOf(tabId, sql);
      if (store.get().keys[key]?.status === 'starting') return;
      const startKey = explorerKeys.execution(scope, sql);
      const cached = store.env().queryClient.getQueryData<string>(startKey);
      if (cached === undefined) {
        if (store.env().username !== '') start(key, tabId, startKey, sql);
        return;
      }
      register(cached, startKey);
      link(key, tabId, cached, true);
      // A new showing of a listing whose watch ended still running looks again, as a new watch of
      // an exploration does.
      const execution = store.get().executions[cached];
      if (execution?.status === 'error' && execution.terminal === null) {
        store.set((registry) =>
          withExecution(registry, cached, (entry) => ({
            ...entry,
            status: 'watching',
            error: null,
            watchGeneration: entry.watchGeneration + 1
          }))
        );
      }
    },

    retryExecution: (id: string) => {
      const execution = store.get().executions[id];
      if (!execution || execution.status !== 'error') return;
      if (execution.terminal?.state === 'SUCCEEDED') {
        read(id);
        return;
      }
      store.set((registry) =>
        withExecution(registry, id, (entry) => ({
          ...entry,
          status: 'watching',
          error: null,
          watchGeneration: entry.watchGeneration + 1
        }))
      );
    },

    settle: (id: string, status: QueryStatus) => {
      const execution = store.get().executions[id];
      if (!execution || execution.status !== 'watching') return;
      store.set((registry) => withExecution(registry, id, (entry) => ({...entry, terminal: status})));
      // Recorded for every tab that asked, whether or not any picker is still showing it. An
      // execution that fails before reporting statistics contributes zero, never NaN.
      for (const tabId of execution.tabIds) store.env().recordScan(tabId, id, status.dataScannedBytes ?? 0);
      if (status.state === 'SUCCEEDED') {
        read(id);
        return;
      }
      store.set((registry) =>
        withExecution(registry, id, (entry) => ({
          ...entry,
          status: 'error',
          error: {code: status.state, message: status.stateChangeReason}
        }))
      );
      // Dropped so the next request starts one execution — and only while it is still this
      // execution's, since an eviction and a new request may have put a newer one there. Nothing
      // observes the entry, so dropping it cannot start anything on its own.
      const {queryClient} = store.env();
      if (queryClient.getQueryData(execution.startKey) === id)
        queryClient.removeQueries({queryKey: execution.startKey});
    },

    endWatch: (id: string, error: unknown) =>
      store.set((registry) =>
        withExecution(registry, id, (entry) =>
          entry.status === 'watching' ? {...entry, status: 'error', error} : entry
        )
      )
  };
}
