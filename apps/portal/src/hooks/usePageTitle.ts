import {useEffect} from 'react';
import {formatPageTitle} from '../lib/formatPageTitle';

/**
 * Sets document.title to the canonical "{page} — Data Workspace" form. Call
 * once at the top of a page component. No unmount cleanup — in an SPA the
 * next page sets its own title.
 *
 * @example
 * usePageTitle('Notifications');
 */
export function usePageTitle(page?: string): void {
  useEffect(() => {
    document.title = formatPageTitle(page);
  }, [page]);
}
