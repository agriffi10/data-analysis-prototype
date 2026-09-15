import {useCallback, useMemo, useRef, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {unwrap} from '../../lib/serviceResult';
import {getIdToken} from '../../lib/idToken';
import {connectionKeys} from './connectionKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {Connection} from './connection.types';
import type {SharedConnectionsCache} from '../shared-spaces/sharedSpaces.types';

// After an async action (create/add/leave/delete), the pipeline writes the
// cache eventually (typically ~7–15s). Without polling, an optimistic entry
// unmounts before the cache catches up (a just-created space appears to
// "disappear"), so `reconcile()` opens a short polling window: poll every 4s
// for 30s, then idle.
const RECONCILE_WINDOW_MS = 30_000;
const RECONCILE_POLL_MS = 4_000;

export type UseConnectionsResult = {
  connections: Connection[];
  isLoading: boolean;
  /**
   * True while this mount's own first read of the list is outstanding — the first load, the refetch
   * a stale cached list triggers on mount, or a read already running when it mounted. False from the
   * start when none is (a list inside its staleTime), and false for good once that read settles,
   * succeeded or failed, so no later refetch brings it back. `isLoading` clears on ANY cached list,
   * however old, so a caller about to conclude that a space does NOT exist waits on this instead.
   */
  isAwaitingFreshList: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  /**
   * Forces a credential/token refresh (so a newly-granted membership
   * principal tag is stamped on the next vend), then re-reads the cache.
   */
  refresh: () => Promise<unknown>;
  /** In-flight affordance for `refresh` (refetch only). */
  isRefreshing: boolean;
  /**
   * Starts a bounded auto-poll of the cache after submitting an action, so
   * the pending → active/removed transition is picked up without a manual
   * Refresh. Also re-mints the token once (like `refresh`) so the actor can
   * use a space they just created immediately.
   */
  reconcile: () => Promise<unknown>;
};

/**
 * The single source of databases the signed-in user can target: the personal
 * database PLUS one entry per shared connection read from the per-user cache
 * the provisioning pipeline writes. All consumers (Query schema rail, Files
 * space list, Connections tab) read this one hook — none have a parallel
 * source.
 *
 * Ordering: personal first, then shared A–Z. provisioning/failed/leaving
 * entries are included (so the UI can show their status) but flagged
 * not-usable via `isConnectionUsable`; a missing/corrupt cache yields
 * personal-only (never an error). A null/empty username yields an empty list.
 */
export function useConnections(username: string | null): UseConnectionsResult {
  const queryClient = useQueryClient();
  const key = useMemo(() => connectionKeys.list(username ?? NO_KEY), [username]);
  // End of the active reconcile window (epoch ms). A ref (not state) because the
  // refetchInterval callback below is re-evaluated by the query after each fetch —
  // it reads the latest value without needing a re-render.
  const reconcileUntil = useRef(0);

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    // A missing cache file is the expected empty state (read returns success with
    // an empty cache), so a retry buys nothing and only doubles the benign 404 the
    // browser logs when the file doesn't exist yet. Disable the default retry here.
    retry: false,
    // Auto-poll only while a reconcile window is open (after an action); idle
    // otherwise so we don't refetch the cache on a timer for no reason.
    refetchInterval: () => (Date.now() < reconcileUntil.current ? RECONCILE_POLL_MS : false),
    queryFn: async (): Promise<SharedConnectionsCache> => {
      const result = await readSharedConnectionsCache(username as string);
      return unwrap(result);
    }
  });
  // Read on the first render only: a later background refetch is not the read this mount was owed.
  const [owedReadOnMount] = useState(() => query.isPending || query.isFetching);

  const connections = useMemo<Connection[]>(() => {
    if (!username) return [];
    const personal: Connection = {
      id: 'personal',
      label: username,
      database: username,
      kind: 'personal'
    };
    const shared = (query.data?.connections ?? [])
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map<Connection>((entry) => ({
        id: entry.name,
        label: entry.name,
        database: entry.name,
        kind: 'shared',
        status: entry.status,
        role: entry.role,
        ...(entry.reason !== undefined ? {reason: entry.reason} : {}),
        ...(entry.failedAction !== undefined ? {failedAction: entry.failedAction} : {}),
        ...(entry.members !== undefined ? {members: entry.members} : {}),
        ...(entry.createdAt !== undefined ? {createdAt: entry.createdAt} : {}),
        ...(entry.owner !== undefined ? {owner: entry.owner} : {})
      }));
    return [personal, ...shared];
  }, [username, query.data]);

  const refresh = useCallback(async () => {
    // Force a fresh token so newly-granted membership claims reach the API on demand,
    // then re-read the cache. A failed refresh keeps the prior list intact
    // (invalidate is non-destructive). Dropping this leaves the button a no-op that
    // still spins.
    await getIdToken(true);
    return queryClient.invalidateQueries({queryKey: key});
  }, [queryClient, key]);

  const reconcile = useCallback(async () => {
    // Open the polling window first so the refetch triggered below schedules the
    // next poll, then re-mint the token (new membership tags for the actor) and
    // re-read the cache once immediately.
    reconcileUntil.current = Date.now() + RECONCILE_WINDOW_MS;
    await getIdToken(true);
    return queryClient.invalidateQueries({queryKey: key});
  }, [queryClient, key]);

  // Memoized so the returned object's identity is stable unless a real input changes
  // (consumers use `refresh`/`reconcile` as effect deps — a fresh object each render
  // would churn them).
  return useMemo<UseConnectionsResult>(
    () => ({
      connections,
      // The initial fetch is loading; once we have any data (incl. the empty cache)
      // the list is usable even while a background refetch runs.
      isLoading: query.isPending && username !== null,
      isAwaitingFreshList:
        username !== null && owedReadOnMount && !query.isFetchedAfterMount && (query.isPending || query.isFetching),
      error: query.error ?? null,
      refresh,
      isRefreshing: query.isRefetching,
      reconcile
    }),
    [
      connections,
      username,
      query.isPending,
      query.isFetching,
      query.isFetchedAfterMount,
      owedReadOnMount,
      query.error,
      query.isRefetching,
      refresh,
      reconcile
    ]
  );
}
