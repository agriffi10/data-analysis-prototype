import {useMemo} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {getSessionCredentials} from '../../lib/awsCredentials';
import {queryKeys} from './queryKeys';
import type {Connection} from './query.types';
import type {SharedConnectionsCache} from '../shared-spaces/sharedSpaces.types';

export type UseConnectionsResult = {
  connections: Connection[];
  isLoading: boolean;
  error: string | null;
  // SPEC-052 FR-003: Refresh-connections — force a credential/token refresh (so a
  // newly-granted `shared_space_k` principal tag is stamped on the next vend), then
  // re-read the cache. `isRefreshing` is the in-flight affordance (refetch only).
  refresh: () => Promise<unknown>;
  isRefreshing: boolean;
};

// SPEC-047 FR-001 + SPEC-052 FR-001: the single source of databases the signed-in
// user can target. Returns the personal database PLUS one entry per shared
// connection read from the per-user cache the provisioning pipeline writes
// ({username}/user_settings/shared-connections.json, SPEC-056). Consumers — the
// Query schema rail (SPEC-047), the Files space list (SPEC-057), and the
// Connections tab (SPEC-052) — all read this one hook; none have a parallel source.
//
// Ordering: personal first, then shared A–Z. provisioning/failed/leaving entries
// are included (so the UI can show their status) but flagged not-usable via
// `isConnectionUsable`; a missing/corrupt cache yields personal-only (never an
// error). A null/empty username yields an empty list (the workspace falls back to
// its existing not-signed-in handling — no crash).
export function useConnections(username: string | null): UseConnectionsResult {
  const queryClient = useQueryClient();
  const key = queryKeys.connections(username ?? '__none__');

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    // A missing cache file is the expected empty state (read returns success with
    // an empty cache), so a retry buys nothing and only doubles the benign 404 the
    // browser logs when the file doesn't exist yet. Disable the default retry here.
    retry: false,
    queryFn: async (): Promise<SharedConnectionsCache> => {
      const result = await readSharedConnectionsCache(username as string);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    }
  });

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
        ...(entry.members !== undefined ? {members: entry.members} : {})
      }));
    return [personal, ...shared];
  }, [username, query.data]);

  return {
    connections,
    // The initial fetch is loading; once we have any data (incl. the empty cache)
    // the list is usable even while a background refetch runs.
    isLoading: query.isPending && username !== null,
    error: query.isError ? (query.error as Error).message : null,
    refresh: async () => {
      // Force a fresh credential vend so newly-granted membership tags apply on
      // demand (architecture §3/§6), then re-read the cache. A failed refresh keeps
      // the prior list intact (invalidate is non-destructive). Credential refresh
      // failures shouldn't block the cache re-read — surface them via the query.
      await getSessionCredentials(true);
      return queryClient.invalidateQueries({queryKey: key});
    },
    isRefreshing: query.isRefetching
  };
}
