import {useQuery, useMutation, useQueryClient} from '@tanstack/react-query';
import {getQueryHistory, appendQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
import {unwrap} from '../../lib/serviceResult';
import {queryKeys} from './queryKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {QueryHistory, QueryHistoryEntry} from './query.types';

export type UseQueryHistoryWritersResult = {
  /** Append at submit time. */
  appendEntry: (entry: QueryHistoryEntry) => Promise<QueryHistory>;
  /** Patch an entry once the execution reaches a terminal state. */
  updateEntry: (vars: {queryExecutionId: string; patch: Partial<QueryHistoryEntry>}) => Promise<QueryHistory>;
};

export type UseQueryHistoryResult = UseQueryHistoryWritersResult & {
  history: QueryHistoryEntry[];
  isLoading: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
  /** Manual re-read of the store from S3 (invalidate + refetch). */
  refresh: () => Promise<unknown>;
  /** True only for a refetch, not the initial load — drives the Refresh control. */
  isRefreshing: boolean;
};

/**
 * Per-user query history list + append/update mutations. Disabled while
 * username is null. Mutations seed the cache with the returned history so the
 * list reflects the change immediately. History is read-only to the user —
 * there is no delete/clear.
 */
export function useQueryHistory(username: string | null): UseQueryHistoryResult {
  const queryClient = useQueryClient();
  const key = queryKeys.history(username ?? NO_KEY);

  const query = useQuery({
    queryKey: key,
    enabled: username !== null,
    queryFn: async (): Promise<QueryHistory> => {
      const result = await getQueryHistory(username as string);
      return unwrap(result);
    }
  });
  const {appendEntry, updateEntry} = useQueryHistoryWriters(username);

  return {
    history: query.data?.entries ?? [],
    isLoading: query.isPending,
    error: query.error ?? null,
    appendEntry,
    updateEntry,
    // invalidateQueries re-reads from S3 for the active observer and resolves once
    // the refetch settles; a failed refetch keeps the last data (non-destructive).
    refresh: () => queryClient.invalidateQueries({queryKey: key}),
    isRefreshing: query.isRefetching
  };
}

/**
 * The history's append and update, without the read — for the run engine at the signed-in shell,
 * which records every run but must not fetch the history on pages that never show it.
 *
 * A write seeds the history cache with what it returns and invalidates it, so an open list
 * reflects the change at once and then reconciles. Call it with the user the writes belong to.
 *
 * @param username - The signed-in user, or null when there is none.
 * @returns The two writers, each resolving with the history as written.
 *
 * @example
 * const {appendEntry, updateEntry} = useQueryHistoryWriters(username);
 */
export function useQueryHistoryWriters(username: string | null): UseQueryHistoryWritersResult {
  const queryClient = useQueryClient();
  const key = queryKeys.history(username ?? NO_KEY);

  // Seed the cache for an instant UI update, then invalidate so the next read
  // reconciles against S3 (the source of truth) — guards against any drift from
  // the services' read-modify-write writes.
  //
  // The service's `recovered` flag is DELIBERATELY dropped here, unlike in
  // `useSavedQueries`: a history write is a side effect of running a query, not
  // something the user asked for, and the quarantine path keeps it silent. The document
  // still recovers — the user is simply not interrupted to be told (the recovered
  // history is empty, and the panel shows that).
  const onWriteSuccess = (data: QueryHistory) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({queryKey: key});
  };

  const append = useMutation({
    mutationFn: async (entry: QueryHistoryEntry): Promise<QueryHistory> => {
      const result = await appendQueryHistory(username as string, entry);
      return unwrap(result);
    },
    onSuccess: onWriteSuccess
  });

  const update = useMutation({
    mutationFn: async (vars: {queryExecutionId: string; patch: Partial<QueryHistoryEntry>}): Promise<QueryHistory> => {
      const result = await updateQueryHistoryEntry(username as string, vars.queryExecutionId, vars.patch);
      return unwrap(result);
    },
    onSuccess: onWriteSuccess
  });

  return {appendEntry: append.mutateAsync, updateEntry: update.mutateAsync};
}
