import { useMemo } from 'react';
import type { Connection } from './query.types';

export type UseConnectionsResult = {
  connections: Connection[];
  isLoading: boolean;
  error: string | null;
};

// SPEC-047 FR-001: the single source of databases the signed-in user can target.
// Today it returns exactly one entry — the user's personal database. This is the
// documented extension point the shared-spaces arc (SPEC-052) feeds `kind:'shared'`
// connections into, so consumers (the schema rail, the toolbar chip) don't change.
//
// The personal connection's label is the user's database name (which is the
// username, SPEC-033) so the schema rail always shows the real database title
// rather than a generic "My workspace".
//
// A null/empty username yields an empty list (the workspace falls back to its
// existing not-signed-in handling — no crash).
export function useConnections(username: string | null): UseConnectionsResult {
  const connections = useMemo<Connection[]>(
    () =>
      username
        ? [
            {
              id: 'personal',
              label: username,
              database: username,
              kind: 'personal',
            },
          ]
        : [],
    [username],
  );

  return { connections, isLoading: false, error: null };
}
