import { useCallback, useMemo, useState } from 'react';
import { QUERY_ACTIVE_DB_STORAGE_PREFIX } from './query.constants';
import { isConnectionUsable } from './query.types';
import type { Connection } from './query.types';

// SPEC-047: the workspace-global active database — one target for all query tabs,
// persisted per-user in sessionStorage (mirroring the SPEC-041 tabs store), default
// + fallback = the personal database (username). All access goes through these
// helpers so a disabled/quota-exceeded sessionStorage degrades to "not persisted"
// rather than crashing the workspace, and an empty username is a no-op.

function activeDbKey(username: string): string | null {
  if (!username) return null;
  return `${QUERY_ACTIVE_DB_STORAGE_PREFIX}${username}`;
}

function readActiveDatabase(username: string): string | null {
  const key = activeDbKey(username);
  if (!key) return null;
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeActiveDatabase(username: string, database: string): void {
  const key = activeDbKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, database);
  } catch {
    // Degrade to not-persisted; never surface a storage error to the workspace.
  }
}

export type UseActiveDatabaseResult = {
  activeDatabase: string;
  setActiveDatabase: (database: string) => void;
  // True when a previously-persisted database is no longer available (e.g. a
  // removed shared DB) and we reset to personal — drives a non-blocking notice.
  fellBack: boolean;
  dismissFellBack: () => void;
};

export function useActiveDatabase(username: string | null, connections: Connection[]): UseActiveDatabaseResult {
  const personal = username ?? '';
  // SPEC-052: only USABLE connections are valid targets — a shared DB that's
  // provisioning/failed/leaving (revoked) is still listed (so the rail can show
  // its status) but must not hold the active target. Deriving `available` from
  // usable connections makes a once-active target fall back to personal the moment
  // it stops being usable, not only when it disappears from the cache entirely.
  const available = useMemo(() => connections.filter(isConnectionUsable).map((c) => c.database), [connections]);

  // The user's stored choice (may be stale if a once-selected shared DB is gone).
  const [stored, setStored] = useState<string>(() => readActiveDatabase(personal) ?? personal);
  const [dismissed, setDismissed] = useState(false);

  const setActiveDatabase = useCallback(
    (database: string) => {
      setStored(database);
      writeActiveDatabase(personal, database);
      setDismissed(false);
    },
    [personal]
  );

  // Reconcile purely during render (no Effect): a stored database that is no
  // longer selectable (e.g. a removed shared DB) resolves to personal, with a
  // non-blocking, dismissible notice. The stale stored value is harmless — it
  // re-resolves to personal next read, and re-applies if that DB reappears.
  const unavailable = !!personal && available.length > 0 && !available.includes(stored);
  const activeDatabase = unavailable ? personal : stored;
  const fellBack = unavailable && stored !== personal && !dismissed;

  const dismissFellBack = useCallback(() => setDismissed(true), []);

  return { activeDatabase, setActiveDatabase, fellBack, dismissFellBack };
}
