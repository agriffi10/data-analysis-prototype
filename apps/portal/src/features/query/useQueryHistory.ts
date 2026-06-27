import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getQueryHistory, appendQueryHistory, updateQueryHistoryEntry } from './queryHistory.service';
import { queryKeys } from './queryKeys';
import type { QueryHistory, QueryHistoryEntry } from './query.types';

export type UseQueryHistoryResult = {
  history: QueryHistoryEntry[];
  isLoading: boolean;
  error: string | null;
  // Append at submit time; update once the execution reaches a terminal state.
  appendEntry: (entry: QueryHistoryEntry) => Promise<QueryHistory>;
  updateEntry: (vars: { queryExecutionId: string; patch: Partial<QueryHistoryEntry> }) => Promise<QueryHistory>;
  // SPEC-046: manual re-read of the store from S3 (invalidate + refetch the
  // history key). `isRefreshing` is the in-flight state for the drawer's Refresh
  // control (true only for a refetch, not the initial load).
  refresh: () => Promise<unknown>;
  isRefreshing: boolean;
};

// SPEC-034 FR-007: per-user query history list + append/update mutations. Disabled
// while username is null. Mutations write the JSON file then seed the cache with
// the returned history so the list reflects the change immediately. History is
// read-only to the user (SPEC-036) — there is no delete/clear.
export function useQueryHistory(username: string | null): UseQueryHistoryResult {
  const queryClient = useQueryClient();
  const key = queryKeys.history(username ?? '__none__');

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<QueryHistory> => {
      const result = await getQueryHistory(username as string);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
  });

  // Seed the cache for an instant UI update, then invalidate so the next read
  // reconciles against S3 (the source of truth) — guards against any drift from
  // the services' read-modify-write writes.
  const onWriteSuccess = (data: QueryHistory) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({ queryKey: key });
  };

  const append = useMutation({
    mutationFn: async (entry: QueryHistoryEntry): Promise<QueryHistory> => {
      const result = await appendQueryHistory(username as string, entry);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    onSuccess: onWriteSuccess,
  });

  const update = useMutation({
    mutationFn: async (vars: {
      queryExecutionId: string;
      patch: Partial<QueryHistoryEntry>;
    }): Promise<QueryHistory> => {
      const result = await updateQueryHistoryEntry(username as string, vars.queryExecutionId, vars.patch);
      if (!result.success) throw new Error(result.error.message);
      return result.data;
    },
    onSuccess: onWriteSuccess,
  });

  return {
    history: query.data?.entries ?? [],
    isLoading: query.isPending,
    error: query.isError ? (query.error as Error).message : null,
    appendEntry: append.mutateAsync,
    updateEntry: update.mutateAsync,
    // invalidateQueries re-reads from S3 for the active observer and resolves once
    // the refetch settles; a failed refetch keeps the last data (non-destructive).
    refresh: () => queryClient.invalidateQueries({ queryKey: key }),
    isRefreshing: query.isRefetching,
  };
}
