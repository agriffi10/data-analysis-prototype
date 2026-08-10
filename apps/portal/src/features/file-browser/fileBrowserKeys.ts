/**
 * Single source of truth for file-browser TanStack Query keys. Mutations
 * invalidate listings through these keys via invalidateListing() in the sibling
 * invalidateListing.ts — never hand-build a key array.
 */
export const fileBrowserKeys = {
  all: ['file-browser'] as const,
  list: (bucket: string, prefix: string) => [...fileBrowserKeys.all, 'list', bucket, prefix] as const,
  /** Per-object HeadObject metadata, cached independently of listings. */
  metadata: (bucket: string, key: string) => [...fileBrowserKeys.all, 'metadata', bucket, key] as const
};
