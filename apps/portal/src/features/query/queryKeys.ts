/**
 * Single source of truth for query-workspace TanStack Query keys. Never
 * hand-build a key array — use these so consumers and the invalidation
 * helpers stay in sync.
 *
 * The schema, execution, results and row-count keys are `catalogKeys` in
 * `features/catalog/`, and the connections key is `connectionKeys` in
 * `features/connections/` (SPEC-176).
 */
export const queryKeys = {
  all: ['query'] as const,
  history: (username: string) => [...queryKeys.all, 'history', username] as const,
  // Keyed by SPACE, not by user (SPEC-173): saved queries are files in a space's
  // `saved_queries/` folder, and the same user reads a different list per space.
  savedQueries: (spaceId: string) => [...queryKeys.all, 'savedQueries', spaceId] as const
};
