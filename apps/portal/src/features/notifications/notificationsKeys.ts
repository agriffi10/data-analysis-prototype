/**
 * Single source of truth for notifications TanStack Query keys (mirrors
 * fileBrowserKeys / queryKeys). Never hand-build a key array.
 */
export const notificationsKeys = {
  all: ['notifications'] as const,
  list: (username: string) => [...notificationsKeys.all, username] as const
};
