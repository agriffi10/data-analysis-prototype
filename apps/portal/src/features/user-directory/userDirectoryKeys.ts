/**
 * Single source of truth for user-directory TanStack Query keys (mirrors `notificationsKeys`
 * and `dataQualityKeys`). Never hand-build a key array.
 *
 * There is exactly one key and it takes no arguments: the document is bucket-wide rather than
 * per-user, so nothing about the signed-in session changes what is fetched. That is also why
 * signing out and back in as someone else does not need to invalidate it.
 */
export const userDirectoryKeys = {
  all: ['user-directory'] as const,
  document: () => [...userDirectoryKeys.all, 'document'] as const
};
