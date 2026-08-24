/**
 * Single source of truth for file-browser TanStack Query keys. Mutations
 * invalidate listings through these keys via invalidateListing() in the sibling
 * invalidateListing.ts — never hand-build a key array.
 */
export const fileBrowserKeys = {
  all: ['file-browser'] as const,
  list: (bucket: string, prefix: string) => [...fileBrowserKeys.all, 'list', bucket, prefix] as const,
  /** Per-object HeadObject metadata, cached independently of listings. */
  metadata: (bucket: string, key: string) => [...fileBrowserKeys.all, 'metadata', bucket, key] as const,
  /**
   * "Is there anything under this prefix?" — its own key, deliberately not `list`'s.
   *
   * `list` is an infinite query whose pages are the browser's filtered view; this is one raw key
   * and answers a different question. Sharing the key would put two incompatible shapes in one
   * cache entry.
   */
  exists: (bucket: string, prefix: string) => [...fileBrowserKeys.all, 'exists', bucket, prefix] as const
};
