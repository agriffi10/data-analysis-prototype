import {useCallback, useRef} from 'react';
import {useQuery} from '@tanstack/react-query';
import {unwrap} from '../../lib/serviceResult';
import {useAuth} from '../auth';
import {userDirectoryKeys} from './userDirectoryKeys';
import {getUserDirectory} from './userDirectory.service';
import {MAX_INDEXED_USERNAMES, buildIndex, search as searchIndex} from './usernameTrie';
import type {UserDirectory, UserDirectoryStatus, UsernameIndex, UsernameSearchResult} from './userDirectory.types';

/** The document changes at most once a day, so an hour of staleness costs nothing. */
const STALE_TIME_MS = 60 * 60 * 1000;
const GC_TIME_MS = 4 * STALE_TIME_MS;

export type UseUserDirectoryResult = {
  status: UserDirectoryStatus;
  /**
   * Stable across renders. Builds the index on first call, then memoises it.
   * Returns `[]` unless `status === 'ready'`.
   */
  search: (query: string, limit?: number) => UsernameSearchResult[];
  generatedAt: string | null;
};

/**
 * The username directory, as a search callback.
 *
 * **It hands out a callback rather than the index, and that is what makes the lazy build
 * invisible.** The index is built on the first `search` call and memoised behind it, so no
 * consumer ever holds a half-built structure or has to decide when to build one.
 *
 * `status` exists because a single nullable index cannot distinguish the three situations
 * consumers must tell apart: still loading, unavailable, and loaded-but-this-name-is-absent
 * (that distinction is load-bearing — a "not found" note shown while the
 * fetch is still in flight reads as a delayed rejection of a name that was accepted).
 *
 * @example
 * const {status, search} = useUserDirectory();
 * const matches = status === 'ready' ? search(typed) : [];
 */
export function useUserDirectory(): UseUserDirectoryResult {
  const {user} = useAuth();
  // The document is bucket-wide, so nothing about the session changes what is fetched — but
  // reading it still needs credentials, and a fetch issued before there are any is a
  // guaranteed failure that would land the directory in 'unavailable' for the session.
  const enabled = !!user;

  const query = useQuery({
    queryKey: userDirectoryKeys.document(),
    enabled,
    staleTime: STALE_TIME_MS,
    gcTime: GC_TIME_MS,
    // A missing document is the EMPTY STATE, not a transient failure — the service already
    // turns "absent" and "corrupt" into an empty success, so anything reaching here is a real
    // fault and retrying it only delays the fallback to free text.
    retry: false,
    queryFn: async (): Promise<UserDirectory> => unwrap(await getUserDirectory())
  });

  const usernames = query.data?.usernames;
  const status: UserDirectoryStatus = !enabled
    ? 'unavailable'
    : query.isPending
      ? 'loading'
      : query.isError || !usernames?.length
        ? // Errored and empty are collapsed deliberately: from a consumer's point of view
          // there are no suggestions either way, and collapsing here means no consumer has to
          // remember to handle both.
          'unavailable'
        : 'ready';

  // Gate on the STATUS, not merely on the array: a signed-out session can still hold a cached
  // document, and `search` must return nothing whenever `status` is not 'ready' — otherwise a
  // consumer branching on status would show suggestions it had been told did not exist.
  const indexable = status === 'ready' ? usernames : undefined;
  const built = useRef<{source: readonly string[]; index: UsernameIndex} | null>(null);

  const search = useCallback(
    (searchQuery: string, limit?: number): UsernameSearchResult[] => {
      if (!indexable?.length) return [];
      if (built.current?.source !== indexable) {
        const index = buildIndex(indexable);
        if (index.truncated) {
          console.warn(
            `[user-directory] ${indexable.length} usernames exceeds the ${MAX_INDEXED_USERNAMES} client-side index cap — suggestions cover the first ${MAX_INDEXED_USERNAMES} only`
          );
        }
        built.current = {source: indexable, index};
      }
      return searchIndex(built.current.index, searchQuery, limit);
    },
    // Identity changes only when a NEW document arrives (or the status leaves 'ready'), which
    // is exactly when the index must be rebuilt. An unrelated re-render keeps both the
    // callback and the built index.
    [indexable]
  );

  return {status, search, generatedAt: query.data?.generatedAt ?? null};
}
