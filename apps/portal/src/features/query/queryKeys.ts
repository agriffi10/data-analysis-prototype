/**
 * Single source of truth for query-feature TanStack Query keys. Never
 * hand-build a key array — use these so consumers and the invalidation
 * helpers stay in sync.
 */
export const queryKeys = {
  all: ['query'] as const,
  schema: (db: string) => [...queryKeys.all, 'schema', db] as const,
  execution: (id: string) => [...queryKeys.all, 'execution', id] as const,
  // Keyed by page size too (SPEC-087): a "Rows per page" change re-fetches
  // page 1 at the new size instead of mixing in stale-sized cached pages.
  results: (id: string, pageSize: number) => [...queryKeys.all, 'results', id, pageSize] as const,
  // Background total-row-count walk (SPEC-080) — a separate key from `results`
  // so the large-page count never perturbs the visible 20/page pager cache.
  rowCount: (id: string) => [...queryKeys.all, 'rowCount', id] as const,
  history: (username: string) => [...queryKeys.all, 'history', username] as const,
  // Keyed by SPACE, not by user (SPEC-173): saved queries are files in a space's
  // `saved_queries/` folder, and the same user reads a different list per space.
  savedQueries: (spaceId: string) => [...queryKeys.all, 'savedQueries', spaceId] as const,
  // Merged personal + shared connection list; refresh-connections invalidates this key.
  connections: (username: string) => [...queryKeys.all, 'connections', username] as const
};
