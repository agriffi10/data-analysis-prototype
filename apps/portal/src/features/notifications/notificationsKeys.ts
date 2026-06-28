// Single source of truth for notifications TanStack Query keys (SPEC-059),
// mirroring fileBrowserKeys / queryKeys. Never hand-build a key array — use these
// so the hook, the prefetch helper, and the SPEC-060 UI stay in sync.
export const notificationsKeys = {
  all: ['notifications'] as const,
  list: (username: string) => [...notificationsKeys.all, username] as const
};
