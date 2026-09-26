/**
 * Single source of truth for notifications TanStack Query keys (mirrors
 * fileBrowserKeys / queryKeys). Never hand-build a key array.
 */
export const notificationsKeys = {
  all: ['notifications'] as const,
  list: (username: string) => [...notificationsKeys.all, username] as const,
  /**
   * The reads a user has asked for and the writer has not yet confirmed. A root of its own,
   * never under `all`: an invalidation of the list is a prefix match, and a refetch of this
   * entry would replace it with nothing.
   */
  pendingReads: (username: string) => ['notifications-pending-reads', username] as const
};
