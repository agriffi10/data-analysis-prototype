import {useMemo} from 'react';
import {useAuth} from '../auth';
import {spaceBuckets} from '../../lib/userSpace';
import {useConnections} from '../connections/useConnections';
import {isConnectionUsable} from '../connections/connection.types';
import type {QuerySpace} from './catalog.types';

/**
 * Every space the query feature can read from or write into: the user's own space
 * first, then each shared space they are an active member of.
 *
 * One definition for the whole feature — `useSaveResults` computed this list inline
 * before the store moved, and loading and saving queries need it again.
 * A space is usable when it is the personal one or a shared connection whose status
 * is `active`; a connection that is provisioning, failed or leaving is omitted.
 *
 * @returns The spaces, personal first. Empty when the user-space bucket is unset.
 */
export function useQuerySpaces(): QuerySpace[] {
  const {user} = useAuth();
  const username = user?.username ?? '';
  const {user: userSpaceBucket, shared: sharedSpaceBucket} = spaceBuckets();
  const {connections} = useConnections(username || null);

  return useMemo(() => {
    // No username means no space, not a space rooted at `/`. On the dev-unauth path
    // `ProtectedLayout` renders the workspace with no user, and an empty username built a
    // personal space whose root was the BUCKET root — which would then hold a marker open
    // and list `saved_queries/` there. The hook was disabled in exactly this state.
    if (!userSpaceBucket || !username) return [];
    const personal: QuerySpace = {
      id: 'personal',
      label: 'My files',
      bucket: userSpaceBucket,
      rootPrefix: `${username}/`,
      rootLabel: 'My Files'
    };
    if (!sharedSpaceBucket) return [personal];
    const shared = connections
      .filter((c) => c.kind === 'shared' && isConnectionUsable(c))
      .map((c) => ({
        id: c.database,
        label: c.database,
        bucket: sharedSpaceBucket,
        rootPrefix: `${c.database}/`,
        rootLabel: c.database
      }));
    return [personal, ...shared];
  }, [userSpaceBucket, sharedSpaceBucket, username, connections]);
}
