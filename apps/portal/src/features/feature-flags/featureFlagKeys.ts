/**
 * Single source of truth for feature-flag TanStack Query keys (mirrors `userDirectoryKeys`).
 * Never hand-build a key array.
 *
 * The key carries the ENVIRONMENT, unlike the username directory's, because the resolved set
 * is a function of the document AND the build's environment name — two environments reading
 * one document can resolve to different answers, and a cache that could not tell them apart
 * would serve one environment's flags under the other's name.
 */
export const featureFlagKeys = {
  all: ['feature-flags'] as const,
  resolved: (environment: string | undefined) => [...featureFlagKeys.all, 'resolved', environment ?? null] as const
};
