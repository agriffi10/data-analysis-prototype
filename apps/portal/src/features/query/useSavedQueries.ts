import {useQuery, useMutation, useQueryClient} from '@tanstack/react-query';
import {getSavedQueries, upsertSavedQuery, removeSavedQuery} from './savedQueries.service';
import {unwrap} from '../../lib/serviceResult';
import {queryKeys} from './queryKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {SavedQueriesStore, SavedQuery} from './query.types';

export type UseSavedQueriesResult = {
  queries: SavedQuery[];
  isLoading: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  upsert: (query: SavedQuery) => Promise<SavedQueriesStore>;
  remove: (id: string) => Promise<SavedQueriesStore>;
};

/**
 * Per-user saved-queries list + upsert/remove mutations. Disabled while
 * username is null. Mutations seed the cache with the returned store so the
 * UI reflects the change immediately, then reconcile against S3 — see
 * `onWriteSuccess`.
 */
export function useSavedQueries(username: string | null): UseSavedQueriesResult {
  const queryClient = useQueryClient();
  const key = queryKeys.savedQueries(username ?? NO_KEY);

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<SavedQueriesStore> => {
      const result = await getSavedQueries(username as string);
      return unwrap(result);
    }
  });

  // Seed the cache for an instant UI update, then invalidate so the next read
  // reconciles against S3 (the source of truth). The seeded store is the WRITER'S
  // view of a read-modify-write, so a write from another tab would otherwise sit
  // unnoticed until something else refetched. Matches `useQueryHistory`.
  const onWriteSuccess = (data: SavedQueriesStore) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({queryKey: key});
  };

  const upsert = useMutation({
    mutationFn: async (q: SavedQuery): Promise<SavedQueriesStore> => {
      const result = await upsertSavedQuery(username as string, q);
      return unwrap(result);
    },
    onSuccess: onWriteSuccess
  });

  const remove = useMutation({
    mutationFn: async (id: string): Promise<SavedQueriesStore> => {
      const result = await removeSavedQuery(username as string, id);
      return unwrap(result);
    },
    onSuccess: onWriteSuccess
  });

  return {
    queries: query.data?.queries ?? [],
    isLoading: query.isPending,
    error: query.error ?? null,
    upsert: upsert.mutateAsync,
    remove: remove.mutateAsync
  };
}
