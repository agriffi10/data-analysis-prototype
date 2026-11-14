import {QueryClient} from '@tanstack/react-query';

/**
 * The app's QueryClient — all server state (S3 reads/writes) lives in it — made by the frame once
 * per mount, never at module scope: a client shared by the module would be shared across server
 * requests the day anything renders it there, and this file is the one home of its defaults.
 *
 * Defaults: staleTime 30s (avoids refetch storms when navigating back into a
 * recently viewed prefix); retry 1 (network blips — the services already retry
 * once on credential expiry); refetchOnWindowFocus off.
 *
 * The focus default is a floor, not a rule, and two queries deliberately opt out of it. The
 * notifications inbox always did. The FILE LISTING joined them once file operations moved onto a
 * control plane: the folder in view can change minutes after the browser stops watching, so a
 * listing that only refetches on navigation is stale for as long as the user stays put.
 *
 * This module knows nothing about any feature. `invalidateListing` used to live
 * here and imported `features/file-browser`'s key factory to do it — the same
 * layering inversion the `components/` ESLint rule forbids one layer up. It now
 * sits in `features/file-browser/invalidateListing.ts`, beside the keys it builds.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false
      }
    }
  });
}
