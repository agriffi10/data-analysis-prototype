import {useQuery} from '@tanstack/react-query';
import {getObjectMetadata} from './fileBrowser.service';
import {unwrap} from '../../lib/serviceResult';
import {fileBrowserKeys} from './fileBrowserKeys';
import type {ObjectMetadata} from './fileBrowser.types';

export type UseObjectMetadataResult = {
  metadata: ObjectMetadata | null;
  isLoading: boolean;
  /** The raw fetch error (or null); render via `toUserMessage`/`ErrorBanner`. */
  error: unknown;
};

/**
 * Fetch a single object's HeadObject metadata via TanStack
 * Query, keyed per object so each file caches independently. Pass `key: null`
 * to disable the query (no file selected) — the panel only mounts this hook
 * when a file's Details action is open, so a failed fetch refetches on reopen
 * (a fresh observer mounts on the same key). The service never throws; we unwrap
 * its ServiceResult and throw here so Query treats a failure as a query error.
 */
export function useObjectMetadata(bucket: string, key: string | null): UseObjectMetadataResult {
  const query = useQuery({
    queryKey: fileBrowserKeys.metadata(bucket, key ?? ''),
    queryFn: async () => {
      const result = await getObjectMetadata({bucket, key: key!});
      return unwrap(result);
    },
    enabled: key !== null
  });

  return {
    metadata: query.data ?? null,
    isLoading: key !== null && query.isPending,
    error: query.error ?? null
  };
}
