/**
 * Single source of truth for query-workspace TanStack Query keys. Never
 * hand-build a key array — use these so consumers and the invalidation
 * helpers stay in sync.
 *
 * The schema, execution, results and row-count keys are `catalogKeys` in
 * `features/catalog/`, the connections key is `connectionKeys` in
 * `features/connections/`, and the saved-query key is `savedQueryKeys` in
 * `features/saved-queries/`.
 */
export const queryKeys = {
  all: ['query'] as const,
  history: (username: string) => [...queryKeys.all, 'history', username] as const
};
