import {useQuery, useMutation, useQueryClient} from '@tanstack/react-query';
import {getSavedQueries, upsertSavedQuery, removeSavedQuery} from './savedQueries.service';
import {queryKeys} from './queryKeys';
import type {SavedQueriesStore, SavedQuery} from './query.types';

export type UseSavedQueriesResult = {
  queries: SavedQuery[];
  isLoading: boolean;
  error: string | null;
  upsert: (query: SavedQuery) => Promise<SavedQueriesStore>;
  remove: (id: string) => Promise<SavedQueriesStore>;
};

/**
 * Per-user saved-queries list + upsert/remove mutations. Disabled while
 * username is null. Mutations seed the cache with the returned store so the
 * UI reflects the change immediately.
 */
export function useSavedQueries(username: string | null): UseSavedQueriesResult {
  const queryClient = useQueryClient();
  const key = queryKeys.savedQueries(username ?? '__none__');

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<SavedQueriesStore> => {
      const result = await getSavedQueries(username as string);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    }
  });

  const upsert = useMutation({
    mutationFn: async (q: SavedQuery): Promise<SavedQueriesStore> => {
      const result = await upsertSavedQuery(username as string, q);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    onSuccess: (data) => queryClient.setQueryData(key, data)
  });

  const remove = useMutation({
    mutationFn: async (id: string): Promise<SavedQueriesStore> => {
      const result = await removeSavedQuery(username as string, id);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    onSuccess: (data) => queryClient.setQueryData(key, data)
  });

  return {
    queries: query.data?.queries ?? [],
    isLoading: query.isPending,
    error: query.isError ? (query.error as Error).message : null,
    upsert: upsert.mutateAsync,
    remove: remove.mutateAsync
  };
}
