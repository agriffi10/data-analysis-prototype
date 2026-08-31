import {useState} from 'react';
import {getIdToken} from '../../lib/idToken';
import type {FileSpaceKind} from './useFileSpace';

export type UseSharedSpaceAccessRecoveryResult = {
  /** The listing failed with a denial that a token re-mint is likely to fix. */
  justAddedToShared: boolean;
  /** In-flight affordance for {@link refreshAccess}. */
  refreshing: boolean;
  refreshAccess: () => Promise<void>;
};

type Params = {
  /** The listing error, or null. */
  error: unknown;
  spaceKind: FileSpaceKind | undefined;
  /** Re-reads the listing after the token is re-minted. */
  refreshListing: () => void;
};

/**
 * A shared space the user was just added to can list-deny until their session's
 * token is re-minted with the new membership-slot tag (shared-spaces
 * architecture §3). Detecting that case is what lets the browser offer a
 * one-click "refresh access" instead of a dead error.
 */
export function useSharedSpaceAccessRecovery({
  error,
  spaceKind,
  refreshListing
}: Params): UseSharedSpaceAccessRecoveryResult {
  const [refreshing, setRefreshing] = useState(false);

  const accessError = error as {message?: string; code?: string} | null;
  const isAccessDenied =
    !!accessError &&
    (accessError.code === 'AccessDenied' || /not authorized|access denied|listbucket/i.test(accessError.message ?? ''));

  return {
    justAddedToShared: spaceKind === 'shared' && isAccessDenied,
    refreshing,
    refreshAccess: async () => {
      setRefreshing(true);
      // Re-mint the ID token so the new shared_space_k claim reaches the API, then
      // re-list. A failed re-mint just leaves the error in place. Dropping this leaves
      // the affordance a no-op that still spins.
      await getIdToken(true);
      refreshListing();
      setRefreshing(false);
    }
  };
}
