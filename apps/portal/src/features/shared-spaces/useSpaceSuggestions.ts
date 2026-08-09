import {useCallback, useMemo, useRef} from 'react';
import {useAuth} from '../auth';
import {useConnections} from '../connections/useConnections';
import {isConnectionUsable} from '../connections/connection.types';
import {buildIndex, search as searchIndex} from '../user-directory/usernameTrie';
import type {
  SuggestionSource,
  UserDirectoryStatus,
  UsernameIndex,
  UsernameSearchResult
} from '../user-directory/userDirectory.types';

/**
 * The signed-in user's own shared spaces as a {@link SuggestionSource}.
 *
 * **It makes no request of its own.** `useConnections` already fetches the per-user connections
 * cache for the Connections page and the Query rail, so this reads a query the app has made
 * anyway — which is the whole reason SPEC-158 costs no new AWS call, IAM or published document.
 *
 * What it deliberately does NOT offer is every space in the organisation. Sharing a table to a
 * space does not require membership, so a complete list would be strictly more useful — and would
 * disclose every space name to every authenticated user, which has no equivalent today. A space
 * the user does not belong to stays typeable; see the `decisions.md` entry.
 *
 * @returns `status` and `search`, using the same three-state vocabulary as the username
 *   directory: `'unavailable'` covers both a failed fetch and a user who belongs to no shared
 *   space, because from the field's point of view there are no suggestions either way.
 *
 * @example
 * <UsernameCombobox {...useSpaceSuggestions()} label="Space names" … />
 */
export function useSpaceSuggestions(): SuggestionSource {
  const {user} = useAuth();
  const {connections, isLoading, error} = useConnections(user?.username ?? null);

  // The personal database is filtered out by `kind`, not by name: this field targets shared
  // spaces, and a user's own database is reachable as a USER recipient in the same dialog.
  // Unusable entries (provisioning/failed/leaving) are dropped too — suggesting a space a share
  // would fail against is worse than suggesting nothing.
  const spaces = useMemo(
    () =>
      connections
        .filter((connection) => connection.kind === 'shared' && isConnectionUsable(connection))
        .map((connection) => connection.database),
    [connections]
  );

  const status: UserDirectoryStatus = isLoading ? 'loading' : error || spaces.length === 0 ? 'unavailable' : 'ready';

  // Same lazy build as `useUserDirectory`, for the same reason: the caller holds a callback, not
  // an index, so it never has to decide when to build one. Keyed on the list's identity —
  // `useConnections` memoises it — so an unrelated re-render keeps the built index and only a
  // new connection list rebuilds it.
  const indexable = status === 'ready' ? spaces : undefined;
  const built = useRef<{source: readonly string[]; index: UsernameIndex} | null>(null);

  const search = useCallback(
    (searchQuery: string, limit?: number): UsernameSearchResult[] => {
      if (!indexable?.length) return [];
      if (built.current?.source !== indexable) built.current = {source: indexable, index: buildIndex([...indexable])};
      return searchIndex(built.current.index, searchQuery, limit);
    },
    [indexable]
  );

  return useMemo(() => ({status, search}), [status, search]);
}
