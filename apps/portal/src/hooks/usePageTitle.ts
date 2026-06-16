import { useEffect } from 'react';
import { formatPageTitle } from '../lib/formatPageTitle';

// Sets document.title to the canonical "{page} — S3 File Portal" form (SPEC-031).
// Call once at the top of a page component. No unmount cleanup — in an SPA the
// next page sets its own title.
export function usePageTitle(page?: string): void {
  useEffect(() => {
    document.title = formatPageTitle(page);
  }, [page]);
}
