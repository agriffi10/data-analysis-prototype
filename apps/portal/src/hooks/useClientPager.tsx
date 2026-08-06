import {useState, type ReactNode} from 'react';

export type ClientPager<T> = {
  /** The current page's slice of `items`. */
  pageItems: T[];
  /** Spread straight onto `<Pager>` — including the label and its screen-reader page number. */
  pagerProps: {
    hasPrev: boolean;
    hasNext: boolean;
    onPrev: () => void;
    onNext: () => void;
    label: ReactNode;
  };
  /** Jump back to page 1 — for a filter change, a refresh, or newly-arrived items. */
  resetToFirst: () => void;
};

/**
 * Client-side pagination over an in-memory list, clamped.
 *
 * THE CLAMP IS THE POINT: the page index is held in state but never trusted directly —
 * every render derives a `safeIndex` from the CURRENT item count, so a list that shrinks
 * under the user (a filter, a refresh, a mark-read) can never strand them on a blank
 * page. Nothing has to remember to reset the index when the data changes.
 *
 * The label and its `sr-only` page number are built here too: the notifications and
 * data-quality pages had written the identical `<Pager>` invocation down to that span,
 * and a page count announced to sighted users only is exactly the kind of divergence
 * two copies produce.
 *
 * @param items - The full (already filtered) list.
 * @param pageSize - Items per page.
 *
 * @example
 * const {pageItems, pagerProps, resetToFirst} = useClientPager(visible, 10);
 * …
 * <Pager className="mt-2" {...pagerProps} />
 */
export function useClientPager<T>(items: readonly T[], pageSize: number): ClientPager<T> {
  const [pageIndex, setPageIndex] = useState(0);

  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * pageSize;
  const pageItems = items.slice(start, start + pageSize);

  return {
    pageItems,
    pagerProps: {
      hasPrev: safeIndex > 0,
      hasNext: safeIndex < pageCount - 1,
      onPrev: () => setPageIndex(Math.max(0, safeIndex - 1)),
      onNext: () => setPageIndex(Math.min(pageCount - 1, safeIndex + 1)),
      label: (
        <>
          {start + 1}–{start + pageItems.length} of {items.length}
          <span className="sr-only"> (page {safeIndex + 1})</span>
        </>
      )
    },
    resetToFirst: () => setPageIndex(0)
  };
}
