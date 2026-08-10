import type {QueryClient} from '@tanstack/react-query';
import {fileBrowserKeys} from './fileBrowserKeys';

/**
 * Invalidates a single prefix listing so the next read refetches from S3.
 * Called after mutations (upload, delete, move/rename) so the browser reflects
 * the change.
 *
 * Lives beside the key factory rather than in `lib/queryClient`: the shared layer
 * owns the client, this feature owns what its keys mean. Callers outside the
 * feature — `features/query`'s save-results flow — reach it through the barrel.
 */
export async function invalidateListing(client: QueryClient, bucket: string, prefix: string): Promise<void> {
  await client.invalidateQueries({
    queryKey: fileBrowserKeys.list(bucket, prefix)
  });
}
