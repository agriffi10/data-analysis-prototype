import {useMemo} from 'react';
import {useLocation, useSearchParams} from '../../lib/navigation';
import {useConnections} from '../connections/useConnections';
import {useSpaceLinkPending} from '../connections/useSpaceLinkPending';
import {resolveExploreParams} from './exploreSources';
import type {ExploreResolution} from './exploreSources';
import type {QuerySpace} from '../catalog/catalog.types';

const LOADING = {status: 'loading'} as const;

export type UseExploreDeepLinkResult = {
  /** `'loading'` while a space the link names waits on a read of the connections list; a resolution afterwards. */
  resolution: ExploreResolution | {status: 'loading'};
  /** Drops the three parameters, replacing the history entry. */
  clear: () => void;
};

/**
 * Resolve `/explore?space=&db=&table=` into a source to open.
 *
 * **IT WAITS FOR THE CONNECTIONS LIST, and that is not a nicety.** Resolution consults the
 * shared spaces the user is an active member of, so a space the list lacks is refused only on a
 * read of it that settles after the link was followed (`useSpaceLinkPending`). Until that read,
 * the denied state would be shown to a user with perfectly good access: on a cold load the list
 * is not there yet, and a cached one, however fresh, may predate a space they have just joined.
 *
 * The connections read is the user's OWN cache document. It is not the disclosure the refusal rule
 * guards: nothing is asked of Glue, or of the space named in the link, until a space this
 * user can reach has been found in a list they already had.
 *
 * @param spaces - Spaces the user can reach, ALREADY filtered by the view's `sharedWorkspaces` gate.
 * @param username - The signed-in username; '' when signed out.
 * @param sharedEnabled - Is `sharedWorkspaces` on? Passed through to the resolver, which does
 *   not read `?space=` at all when it is off.
 * @returns The resolution and a way to drop the parameters once acted on.
 */
export function useExploreDeepLink(
  spaces: readonly QuerySpace[],
  username: string,
  sharedEnabled: boolean
): UseExploreDeepLinkResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const {listReadsSettled, rereadList} = useConnections(username || null);

  const space = searchParams.get('space');
  const db = searchParams.get('db');
  const table = searchParams.get('table');

  const resolved = useMemo(
    () => resolveExploreParams({space, db, table}, spaces, username, sharedEnabled),
    [space, db, table, spaces, username, sharedEnabled]
  );
  // `loading` only while a named space is refused. Without one there is nothing to wait for — the
  // personal space is built from the username alone — and reporting `loading` anyway would put a
  // spinner in front of every visit to `/explore`. Keyed on `denied`, the wait inherits the flag:
  // with `sharedWorkspaces` off the resolver never reads `?space=`, so nothing is refused or waited on.
  const pending = useSpaceLinkPending({
    username: username || null,
    space,
    missing: resolved.status === 'denied',
    listReadsSettled,
    rereadList
  });
  const resolution = pending ? LOADING : resolved;

  return {
    resolution,
    // `replace`, so Back leaves the Data Explorer rather than re-opening the tab the link
    // already opened — and so a reload restores the session's tabs instead of
    // adding a duplicate of the linked one on top of them. The entry's state is carried over:
    // it may hold a hand-off from another feature, which is opened after the link, not dropped.
    clear: () =>
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const key of ['space', 'db', 'table']) next.delete(key);
          return next;
        },
        {replace: true, state: location.state}
      )
  };
}
