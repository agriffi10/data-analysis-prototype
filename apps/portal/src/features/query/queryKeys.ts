// Single source of truth for query-feature TanStack Query keys (SPEC-034),
// mirroring fileBrowserKeys. Never hand-build a key array — use these so the
// SPEC-035/036 UI and the invalidation helpers stay in sync.
export const queryKeys = {
  all: ['query'] as const,
  schema: (db: string) => [...queryKeys.all, 'schema', db] as const,
  execution: (id: string) => [...queryKeys.all, 'execution', id] as const,
  results: (id: string) => [...queryKeys.all, 'results', id] as const,
  history: (username: string) =>
    [...queryKeys.all, 'history', username] as const,
};
