import {useEffect, useState} from 'react';
import {SAVED_QUERIES_PAGE_SIZE} from './query.constants';
import type {SavedQuery} from './query.types';

type Args = {
  queries: SavedQuery[];
  /** Further LISTING pages exist. */
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  /** The listing's error, if any — stops the fill so a failure cannot spin. */
  error: unknown;
  /** Changing this resets to page 1 (the chosen space, and the drawer opening). */
  resetKey: string;
};

export type SavedQueriesPagerState = {
  /** The rows to render for the current display page. */
  page: SavedQuery[];
  hasPrev: boolean;
  hasNext: boolean;
  /** Next is waiting on a listing page. */
  isFetching: boolean;
  /** The `Pager` label content: `X–Y of Z`, or `Z+` while more pages remain. */
  label: string;
  /** True once the listing is exhausted with no rows — the empty state's condition. */
  isEmpty: boolean;
  /** No rows YET and pages remain: still filling, so neither empty nor pageable. */
  isFilling: boolean;
  onPrev: () => void;
  onNext: () => void;
};

/**
 * The display pager the saved-queries drawer and the mobile Saved tab share.
 *
 * **A listing page and a display page are different things, and the filter is why.**
 * An S3 page of 25 keys yields only the top-level `.sql` files among them, so a folder
 * of two hundred CSVs and one saved query would otherwise render as an empty list with
 * a Load-more the user has to guess at. This hook keeps fetching while the listing is
 * truncated and it holds fewer rows than the page in view needs — bounded by the
 * listing's own end, and stopped by a failure so an error can never spin.
 *
 * S3 reports no total, so the label says `Z+` while more pages remain: the difference
 * between "there are 24" and "there are at least 24".
 *
 * @param args - The hook's rows and paging state, plus the reset key.
 * @returns The current page's rows, the Prev/Next state and the range label.
 */
export function useSavedQueriesPager({
  queries,
  hasMore,
  loadMore,
  isLoadingMore,
  error,
  resetKey
}: Args): SavedQueriesPagerState {
  const [pageIndex, setPageIndex] = useState(0);

  // Render-phase "adjust state on change" (react.md §3) rather than an effect: choosing
  // another space, or reopening the drawer, starts at page 1.
  const [prevKey, setPrevKey] = useState(resetKey);
  if (resetKey !== prevKey) {
    setPrevKey(resetKey);
    setPageIndex(0);
  }

  const total = queries.length;
  const pageCount = Math.max(1, Math.ceil(total / SAVED_QUERIES_PAGE_SIZE));
  // Clamped, so a page that no longer exists (a delete, or a fetch still in flight for
  // rows the user has already asked for) shows the nearest one that does.
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * SAVED_QUERIES_PAGE_SIZE;
  const page = queries.slice(start, start + SAVED_QUERIES_PAGE_SIZE);

  // Enough rows to fill the page the user is looking at. `pageIndex` — not `safeIndex` —
  // because pressing Next past the loaded rows is exactly the request to fetch more.
  const wanted = (pageIndex + 1) * SAVED_QUERIES_PAGE_SIZE;
  useEffect(() => {
    if (!error && hasMore && !isLoadingMore && total < wanted) loadMore();
  }, [error, hasMore, isLoadingMore, total, wanted, loadMore]);

  return {
    page,
    hasPrev: safeIndex > 0,
    hasNext: safeIndex < pageCount - 1 || hasMore,
    isFetching: isLoadingMore,
    label: `${total === 0 ? 0 : start + 1}–${start + page.length} of ${total}${hasMore ? '+' : ''}`,
    isEmpty: total === 0 && !hasMore,
    // A folder of two hundred CSVs reads as loading, not as empty and not as a pager
    // over nothing, while the fill effect walks the rest of the listing.
    isFilling: total === 0 && hasMore && !error,
    onPrev: () => setPageIndex(Math.max(0, safeIndex - 1)),
    // Past the last loaded page the index still advances: the clamp holds the view here
    // while the fill effect fetches, and the new page lands when its rows arrive.
    onNext: () => setPageIndex(safeIndex + 1)
  };
}
