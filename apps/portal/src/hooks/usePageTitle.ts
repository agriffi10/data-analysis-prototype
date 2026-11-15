import {useEffect, useLayoutEffect, useRef} from 'react';
import {formatPageTitle} from '../lib/formatPageTitle';

/**
 * Sets document.title to the canonical "{page} — Data Quarry" form. Call
 * once at the top of a page component. No unmount cleanup — in an SPA the
 * next page sets its own title.
 *
 * On the App Router the page file also sets the title as it mounts
 * ({@link usePageTitleOnMount}); this hook, in the view, then owns every
 * change the page makes to it afterwards, such as an unread count.
 *
 * @example
 * usePageTitle('Notifications');
 */
export function usePageTitle(page?: string): void {
  useEffect(() => {
    document.title = formatPageTitle(page);
  }, [page]);
}

/**
 * Sets the title in the commit that mounts an App Router page, once, for its
 * page file to call with the name its view titles itself by.
 *
 * Next's route announcer reads document.title in a passive effect of the
 * commit that changes the router's tree. On a first visit that commit holds
 * the page but not its view, which `next/dynamic` is still loading, so a
 * title set only by the view is read a commit late and the user hears the
 * page they left. A layout effect runs before every passive effect: it is in
 * place for the announcer, and before the view's {@link usePageTitle} in a
 * commit holding both. It writes once per mount, because a boundary above
 * that hides the page and shows it again re-runs its layout effects but not
 * the view's passive one.
 *
 * What a first visit announces is this name, so a view whose title depends
 * on state (an unread count, a flag that is off) is announced by its page's
 * name until the next navigation reads its own.
 *
 * @param page - The page's name, as its view passes it to `usePageTitle`.
 * @returns Nothing.
 *
 * @example
 * usePageTitleOnMount('Files');
 */
export function usePageTitleOnMount(page: string): void {
  const written = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (written.current === page) return;
    written.current = page;
    document.title = formatPageTitle(page);
  }, [page]);
}
