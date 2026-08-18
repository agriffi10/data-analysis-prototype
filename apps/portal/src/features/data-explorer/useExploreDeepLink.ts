import {useMemo} from 'react';
import {useSearchParams} from 'react-router';
import {useConnections} from '../connections/useConnections';
import {resolveExploreParams} from './exploreSources';
import type {ExploreResolution} from './exploreSources';
import type {QuerySpace} from '../catalog/catalog.types';

export type UseExploreDeepLinkResult = {
  /** `'loading'` until the connections list has settled; a resolution afterwards. */
  resolution: ExploreResolution | {status: 'loading'};
  /** Drops the three parameters, replacing the history entry. */
  clear: () => void;
};

/**
 * Resolve `/explore?space=&db=&table=` into a source to open.
 *
 * **IT WAITS FOR THE CONNECTIONS LIST, and that is not a nicety.** Resolution consults the
 * shared spaces the user is an active member of; until they load, a link to a shared space
 * would resolve to nothing and the page would flash the denied state at a user with perfectly
 * good access — and a link whose space name equals the username would resolve PERSONAL for a
 * beat, which is the one wrong answer that also looks right.
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
  const {isLoading} = useConnections(username || null);

  const space = searchParams.get('space');
  const db = searchParams.get('db');
  const table = searchParams.get('table');

  const resolution = useMemo((): ExploreResolution | {status: 'loading'} => {
    // `loading` only while a `?space=` is actually waiting on something. Without one there
    // is nothing to wait for — the personal space is built from the username alone — and
    // reporting `loading` anyway would put a spinner in front of every visit to `/explore`.
    //
    // `sharedEnabled` belongs in this condition, not only in the resolver: with the flag off
    // the parameter is discarded unread, so waiting on connections for it would be waiting
    // on a value that cannot change the answer — and the "not read at all" would be
    // true of the resolution while visibly false of the page.
    if (isLoading && sharedEnabled && space !== null) return {status: 'loading'};
    return resolveExploreParams({space, db, table}, spaces, username, sharedEnabled);
  }, [isLoading, space, db, table, spaces, username, sharedEnabled]);

  return {
    resolution,
    // `replace`, so Back leaves the Data Explorer rather than re-opening the tab the link
    // already opened — and so a reload restores the session's tabs instead of
    // adding a duplicate of the linked one on top of them.
    clear: () =>
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const key of ['space', 'db', 'table']) next.delete(key);
          return next;
        },
        {replace: true}
      )
  };
}
