// Single source of truth for file-browser TanStack Query keys (SPEC-015 FR-001).
// Mutation specs (SPEC-016/018/019) invalidate listings through these keys via
// invalidateListing() in src/lib/queryClient.ts — never hand-build a key array.
export const fileBrowserKeys = {
  all: ['file-browser'] as const,
  list: (bucket: string, prefix: string) => [...fileBrowserKeys.all, 'list', bucket, prefix] as const,
  // Per-object HeadObject metadata (SPEC-017), cached independently of listings.
  metadata: (bucket: string, key: string) => [...fileBrowserKeys.all, 'metadata', bucket, key] as const
};
