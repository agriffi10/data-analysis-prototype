/**
 * Single source of truth for data-quality TanStack Query keys (mirrors
 * notificationsKeys / queryKeys). Never hand-build a key array.
 *
 * A report is keyed by space AND requestId because the request id alone does not say
 * which space holds it — the same reason the route carries both (FR-005).
 */
export const dataQualityKeys = {
  all: ['data-quality'] as const,
  report: (space: string, requestId: string) => [...dataQualityKeys.all, 'report', space, requestId] as const,
  /**
   * The runs list. Keyed by the JOINED SPACE NAMES, not by username: the list is
   * merged across every space the user can see, so leaving or joining a shared space must
   * produce a different key — otherwise the cache would keep serving a list that still
   * contains a space the user no longer belongs to.
   */
  runs: (spaces: string) => [...dataQualityKeys.all, 'runs', spaces] as const
};
