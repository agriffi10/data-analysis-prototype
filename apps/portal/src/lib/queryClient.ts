import {QueryClient} from '@tanstack/react-query';
import {fileBrowserKeys} from '../features/file-browser/fileBrowserKeys';

/**
 * Single app-wide QueryClient — all server state (S3 reads/writes) lives here.
 *
 * Defaults: staleTime 30s (avoids refetch storms when navigating back into a
 * recently viewed prefix); retry 1 (network blips — the services already retry
 * once on credential expiry); refetchOnWindowFocus off (refetching file lists
 * on every tab focus is noisy and surprising).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
});

/**
 * Invalidates a single prefix listing so the next read refetches from S3.
 * Called after mutations (upload, delete, move/rename) so the browser reflects
 * the change.
 */
export async function invalidateListing(client: QueryClient, bucket: string, prefix: string): Promise<void> {
  await client.invalidateQueries({
    queryKey: fileBrowserKeys.list(bucket, prefix)
  });
}
