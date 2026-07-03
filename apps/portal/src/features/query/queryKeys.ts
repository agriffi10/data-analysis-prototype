/**
 * Single source of truth for query-feature TanStack Query keys. Never
 * hand-build a key array — use these so consumers and the invalidation
 * helpers stay in sync.
 */
export const queryKeys = {
  all: ['query'] as const,
  schema: (db: string) => [...queryKeys.all, 'schema', db] as const,
  execution: (id: string) => [...queryKeys.all, 'execution', id] as const,
  results: (id: string) => [...queryKeys.all, 'results', id] as const,
  // Background total-row-count walk (SPEC-080) — a separate key from `results`
  // so the large-page count never perturbs the visible 20/page pager cache.
  rowCount: (id: string) => [...queryKeys.all, 'rowCount', id] as const,
  history: (username: string) => [...queryKeys.all, 'history', username] as const,
  savedQueries: (username: string) => [...queryKeys.all, 'savedQueries', username] as const,
  // Merged personal + shared connection list; refresh-connections invalidates this key.
  connections: (username: string) => [...queryKeys.all, 'connections', username] as const
};
