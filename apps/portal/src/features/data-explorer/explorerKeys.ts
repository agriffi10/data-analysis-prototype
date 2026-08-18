/**
 * Single source of truth for Data Explorer TanStack Query keys. Never hand-build a key
 * array — use these so consumers and the invalidation helpers stay in sync.
 *
 * Rooted at `['data-explorer']`, not `['query']` or `['catalog']` (the rule):
 * a namespace naming a feature the module does not belong to lets one feature's blanket
 * invalidation reach another's caches.
 *
 * The execution key is **the rendered SQL itself**. That is what makes
 * the cache the cost control: two explorations that render identically resolve to one
 * Athena execution, so changing a filter and changing it back is a cache hit rather than
 * a second bill. Keying by exploration id instead would bill every gesture.
 */
export const explorerKeys = {
  all: ['data-explorer'] as const,
  execution: (sql: string) => [...explorerKeys.all, 'execution', sql] as const
};
