import {useEffect, useState} from 'react';
import {useLocation, useNavigationType} from 'react-router';

export type UseSpaceLinkPendingParams = {
  username: string | null;
  /** The space a link names — a `?space=` value or a `:space` segment — or null when it names none. */
  space: string | null;
  /** Does the connections list, as it stands, lack a usable space by that name? Only an absence waits. */
  missing: boolean;
  /** `useConnections`' count of settled reads of the list. */
  listReadsSettled: number;
  /** `useConnections`' one more read of the list, unless one is already running. */
  rereadList: () => Promise<unknown>;
};

/**
 * Holds back the refusal of a space a link names until a read of the connections list settles after
 * the link was followed, and asks for that read when none is due.
 *
 * `useConnections`' `isLoading` clears on ANY cached list, however old, and a list read before the
 * link may predate a space the user has just joined. Refused on that list's word, the space stays
 * refused: a list inside its staleTime owes no read, and neither does a page the link lands on
 * without remounting. Presence is trusted at once; only an absence waits.
 *
 * A link is the navigation as well as the value. While a refusal shows, the address still names the
 * space, so the same link followed again differs only in the navigation, and asks afresh. A POP is not
 * a follow, and excluding it is load-bearing: an in-page anchor such as the shell's "Skip to main
 * content" is a same-document navigation whose entry carries no state, so the router's key resets and
 * every such click would otherwise re-arm the wait and spend a read. Back and forward into a DIFFERENT
 * space still re-arm, on the value.
 *
 * @param params - The link's space, whether the list lacks it, and the list's read count and re-read.
 * @returns True while the link must neither be refused nor opened on the list as it stands.
 *
 * @example
 * const {listReadsSettled, rereadList} = useConnections(username);
 * const pending = useSpaceLinkPending({username, space, missing: !resolved, listReadsSettled, rereadList});
 */
export function useSpaceLinkPending({
  username,
  space,
  missing,
  listReadsSettled,
  rereadList
}: UseSpaceLinkPendingParams): boolean {
  // Per user too, since another user's list is another query with its own count.
  const {key: navigation} = useLocation();
  const followed = useNavigationType() !== 'POP';
  const [link, setLink] = useState({username, space, navigation, reads: listReadsSettled});
  if (link.username !== username || link.space !== space || (link.navigation !== navigation && followed)) {
    setLink({username, space, navigation, reads: listReadsSettled});
  }

  const pending = Boolean(username) && Boolean(space) && missing && listReadsSettled <= link.reads;

  // A read already running — the one owed on mount — answers instead of a second. Keyed on the link too:
  // a link followed while waiting, in the render where the awaited read settles, starts from that read
  // and leaves `pending` unchanged, so keyed on `pending` alone nothing would ask for the read it needs.
  useEffect(() => {
    if (pending) void rereadList();
  }, [pending, link, rereadList]);

  return pending;
}
