/**
 * Single source of truth for saved-query TanStack Query keys (out of
 * `queryKeys.savedQueries`). Never hand-build a key array — use these so consumers and
 * the invalidation helpers stay in sync.
 *
 * Rooted at `['saved-queries']` rather than under `['query']`: a namespace naming the
 * wrong feature lets one feature's blanket invalidation reach another's caches
 * (the reasoning for `catalogKeys`).
 */
export const savedQueryKeys = {
  all: ['saved-queries'] as const,
  // Keyed by SPACE, not by user: saved queries are files in a space's
  // `saved_queries/` folder, and the same user reads a different list per space.
  list: (spaceId: string) => [...savedQueryKeys.all, 'list', spaceId] as const
};
