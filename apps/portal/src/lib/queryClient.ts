import {QueryClient} from '@tanstack/react-query';
import {fileBrowserKeys} from '../features/file-browser/fileBrowserKeys';

// Single app-wide QueryClient (SPEC-015 FR-001). Server state (S3 reads/writes)
// lives here so later file-operation specs get caching, refetch, and
// post-mutation invalidation for free.
//
// Defaults:
// - staleTime 30s        — listings stay fresh briefly; avoids refetch storms
//                          when navigating back into a recently viewed prefix.
// - retry 1              — one automatic retry on a failed query before erroring
//                          (S3/network blips); the service already retries once
//                          on credential expiry, so this is a thin extra guard.
// - refetchOnWindowFocus false — corporate users tab away constantly; refetching
//                          on every focus is noisy and surprising for file lists.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
});

// Invalidate a single prefix listing so the next read refetches from S3. Later
// mutation specs (upload, delete, move/rename) call this after a write so the
// browser reflects the change. Exported as a free function (not a method) so it
// can be unit-tested and called with any QueryClient instance.
export async function invalidateListing(client: QueryClient, bucket: string, prefix: string): Promise<void> {
  await client.invalidateQueries({
    queryKey: fileBrowserKeys.list(bucket, prefix)
  });
}
