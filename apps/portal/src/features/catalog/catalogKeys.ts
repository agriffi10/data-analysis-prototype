/**
 * Single source of truth for catalog TanStack Query keys — the schema reader, the
 * Athena execution poll, the results pager and the background row-count walk. Never
 * hand-build a key array; use these so consumers and the invalidation helpers stay in
 * sync.
 *
 * Rooted at ['catalog'], not ['query'] (SPEC-176 FR-003): a key namespace naming a
 * feature the module no longer belongs to is the hidden coupling this layer exists to
 * remove, and it would make `invalidateQueries({queryKey: queryKeys.all})` reach into
 * the Data Explorer's caches.
 */
export const catalogKeys = {
  all: ['catalog'] as const,
  schema: (db: string) => [...catalogKeys.all, 'schema', db] as const,
  execution: (id: string) => [...catalogKeys.all, 'execution', id] as const,
  // Keyed by page size too (SPEC-087): a "Rows per page" change re-fetches
  // page 1 at the new size instead of mixing in stale-sized cached pages.
  results: (id: string, pageSize: number) => [...catalogKeys.all, 'results', id, pageSize] as const,
  // Background total-row-count walk (SPEC-080) — a separate key from `results`
  // so the large-page count never perturbs the visible 20/page pager cache.
  rowCount: (id: string) => [...catalogKeys.all, 'rowCount', id] as const
};
