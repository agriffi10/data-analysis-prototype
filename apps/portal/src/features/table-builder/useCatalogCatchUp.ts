import {useCallback, useEffect, useRef} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateSchema} from '../catalog/useSchema';

/**
 * Re-read a database's catalog the next time the window regains focus.
 *
 * **THE ENQUEUE IS NOT THE EVENT.** A table build is asynchronous: the browser puts a request on
 * a queue and the table appears minutes later, announced by a notification. Nothing in the tab
 * that submitted it hears about the completion, so every cache keyed on that catalog — the
 * schema rail, and the Data Explorer's execution cache — goes on describing the catalog as it
 * was before the build. For the Explorer that is the stale-rows bug arriving by a second road:
 * dropping the table invalidates, rebuilding it does not, and the exploration resolves to the
 * pre-drop execution.
 *
 * Window focus is the signal because the build is watched from somewhere else — a notification,
 * another tab, a colleague's message — so returning to the page is the moment the answer is
 * wanted. It is armed by a successful enqueue and disarmed by firing, so an idle focus event
 * invalidates nothing.
 *
 * No table is named. A create is precisely the case where the caller cannot know whether the
 * name it asked for is the name that now exists, so the whole database is re-read and every
 * cached exploration of it re-runs. That is the expensive arm of the eviction, taken knowingly:
 * the alternative is showing rows the user has already been told are gone.
 *
 * Lifted out of `useTableRefresh`, which had the same effect written inline for the refresh
 * path only. The lift is what makes the create path's version the same mechanism rather than a
 * second one that drifts.
 *
 * @returns `arm(database)`, called after a successful enqueue.
 */
export function useCatalogCatchUp(): {arm: (database: string) => void} {
  const queryClient = useQueryClient();
  // The database owed a re-read, or null when nothing is armed. A ref rather than state:
  // nothing renders from it, and a re-render must not re-arm it.
  const owed = useRef<string | null>(null);

  useEffect(() => {
    const onFocus = () => {
      const database = owed.current;
      if (!database) return;
      owed.current = null;
      void invalidateSchema(queryClient, database);
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [queryClient]);

  const arm = useCallback((database: string) => {
    owed.current = database;
  }, []);

  return {arm};
}
