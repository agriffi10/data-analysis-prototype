import {useCallback, useMemo} from 'react';
import {useInfiniteQuery, useQueryClient} from '@tanstack/react-query';
import {deleteSavedQuery, listSavedQueries} from './savedQueries.service';
import {unwrap} from '../../lib/serviceResult';
import {queryKeys} from './queryKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {SavedQuery, SavedQueryPage} from './query.types';
import type {QuerySpace} from '../catalog/catalog.types';

export type UseSavedQueriesResult = {
  queries: SavedQuery[];
  isLoading: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  /** Whether further LISTING pages exist — drives the "Load more" control. */
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  refresh: () => void;
  /** Deletes the object and invalidates the list, so the drawer reflects it. */
  remove: (query: SavedQuery) => Promise<void>;
};

/**
 * A space's saved queries — the `.sql` files in its `saved_queries/` folder — paginated
 * over S3's own listing (SPEC-173 FR-006).
 *
 * Disabled while `space` is null, and keyed by SPACE: the same user reads a different
 * list per space, and SPEC-174 passes the chosen one where this spec always passes the
 * personal space, so the hook does not change again.
 *
 * No body is ever fetched here. A row is name + modified + size, which is everything a
 * `.sql` object carries; the SQL is read only when a query is opened.
 *
 * @param space - The space to list, or null to stay idle.
 * @returns The list, its paging state and the delete mutation.
 */
export function useSavedQueries(space: QuerySpace | null): UseSavedQueriesResult {
  const queryClient = useQueryClient();
  const spaceId = space?.id ?? NO_KEY;
  const key = useMemo(() => queryKeys.savedQueries(spaceId), [spaceId]);

  const query = useInfiniteQuery({
    queryKey: key,
    enabled: space !== null,
    queryFn: async ({pageParam, signal}) => {
      const result = await listSavedQueries({space: space as QuerySpace, continuationToken: pageParam, signal});
      return unwrap(result);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: SavedQueryPage) => (last.isTruncated ? last.nextContinuationToken : undefined)
  });

  const queries = useMemo(() => (query.data?.pages ?? []).flatMap((p) => p.queries), [query.data]);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({queryKey: key});
  }, [queryClient, key]);

  const loadMore = useCallback(() => {
    void query.fetchNextPage();
  }, [query]);

  const remove = useCallback(
    async (target: SavedQuery) => {
      const result = await deleteSavedQuery({bucket: target.bucket, key: target.key, username: usernameFor(target)});
      unwrap(result);
      await queryClient.invalidateQueries({queryKey: key});
    },
    [queryClient, key]
  );

  return {
    queries,
    isLoading: query.isPending,
    error: query.error ?? null,
    hasMore: query.hasNextPage,
    loadMore,
    isLoadingMore: query.isFetchingNextPage,
    refresh,
    remove
  };
}

// The marker guard in `deleteObject` identifies the ROOT marker of the prefix the key
// sits under, and a saved query's key always starts with that root segment. Taking it
// from the key rather than from `useAuth` keeps the guard correct in a shared space,
// where the root segment is the space name and not the signed-in user.
function usernameFor(query: SavedQuery): string {
  return query.key.slice(0, query.key.indexOf('/'));
}
