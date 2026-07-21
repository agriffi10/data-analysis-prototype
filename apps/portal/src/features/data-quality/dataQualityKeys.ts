/**
 * Single source of truth for data-quality TanStack Query keys (mirrors
 * notificationsKeys / queryKeys). Never hand-build a key array.
 *
 * A report is keyed by space AND requestId because the request id alone does not say
 * which space holds it — the same reason the route carries both (FR-005).
 */
export const dataQualityKeys = {
  all: ['data-quality'] as const,
  report: (space: string, requestId: string) => [...dataQualityKeys.all, 'report', space, requestId] as const
};
