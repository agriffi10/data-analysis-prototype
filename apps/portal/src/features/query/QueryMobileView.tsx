import {useState} from 'react';
import {Banner} from '../../components/Banner';
import {DocumentIcon} from '../../components/icons';
import {Pager} from '../../components/Pager';
import {cx} from '../../lib/cx';
import {toUserText} from '../../lib/errorMessages';
import {QueryHistoryRow} from './QueryHistoryRow';
import {QUERY_HISTORY_PAGE_SIZE} from './query.constants';
import {formatRelativeTime} from '../../lib/format';
import {formatBytes} from '../../lib/format';
import {SavedQuerySpaceSelect} from '../saved-queries/SavedQuerySpaceSelect';
import {SavedQueryDeleteConfirm} from './SavedQueriesPanel';
import {useSavedQueriesPager} from '../saved-queries/useSavedQueriesPager';
import type {MobileHomeTab, QueryHistoryEntry} from './query.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

type QueryMobileViewProps = {
  /** Which list is showing; owned by the workspace so Back returns to it. */
  tab: MobileHomeTab;
  onTabChange: (tab: MobileHomeTab) => void;
  /** Every space the user may load saved queries from, personal first. */
  spaces: QuerySpace[];
  space: QuerySpace | null;
  onSelectSpace: (spaceId: string) => void;
  savedQueries: SavedQuery[];
  savedLoading: boolean;
  /** Raw fetch error (or null); rendered via `toUserMessage`. */
  savedError: unknown;
  /** Further listing pages exist for the chosen space. */
  savedHasMore: boolean;
  onLoadMoreSaved: () => void;
  savedLoadingMore: boolean;
  /** Host deletes the file and unlinks any open tab. */
  onDeleteSaved: (query: SavedQuery) => void;
  history: QueryHistoryEntry[];
  historyLoading: boolean;
  historyError: unknown;
  /** Submit this SQL through the shared run path and open the results view. */
  onRun: (sql: string, title: string) => void;
  /** Open the results view read-only, without running. */
  onView: (sql: string, title: string) => void;
  /** A saved query carries no SQL until its file is read, so the host does both. */
  onRunSaved: (query: SavedQuery) => void;
  onViewSaved: (query: SavedQuery) => void;
  /** True while a run is in flight — Run is unavailable until it settles. */
  runDisabled: boolean;
};

const TABS: ReadonlyArray<{value: MobileHomeTab; label: string}> = [
  {value: 'saved', label: 'Saved'},
  {value: 'history', label: 'History'}
];

// ≥44px touch target on a phone.
const cardAction =
  'inline-flex min-h-11 items-center rounded-sm px-2 py-1 text-sm font-semibold text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';

function EmptyState({title, hint}: {title: string; hint: string}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <DocumentIcon className="h-8 w-8 text-text-3" />
      <p className="text-sm font-medium text-text">{title}</p>
      <p className="max-w-[280px] text-sm text-text-3">{hint}</p>
    </div>
  );
}

/**
 * The mobile (`< tablet`) query workspace: browse-first, with no SQL editor
 * (SPEC-100 FR-004). Saved queries and History are the two surfaces — tapping
 * **Run** on a card submits that entry through the same run path the editor uses
 * and hands off to the mobile results view; **View** opens it read-only. Both
 * lists are the workspace's existing data, passed down (no new fetch).
 *
 * @example
 * <QueryMobileView tab="saved" onTabChange={setTab} savedQueries={saved.queries} … />
 */
export function QueryMobileView({
  tab,
  onTabChange,
  spaces,
  space,
  onSelectSpace,
  savedQueries,
  savedLoading,
  savedError,
  savedHasMore,
  onLoadMoreSaved,
  savedLoadingMore,
  onDeleteSaved,
  history,
  historyLoading,
  historyError,
  onRun,
  onView,
  onRunSaved,
  onViewSaved,
  runDisabled
}: QueryMobileViewProps) {
  // Client-side Prev/Next over the in-memory newest-first history, mirroring the
  // desktop drawer's pager — replace-style, never infinite scroll.
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(1, Math.ceil(history.length / QUERY_HISTORY_PAGE_SIZE));
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * QUERY_HISTORY_PAGE_SIZE;
  const pageEntries = history.slice(start, start + QUERY_HISTORY_PAGE_SIZE);

  // Snap back to the newest page when an entry is appended in-session.
  const [prevLen, setPrevLen] = useState(history.length);
  if (history.length !== prevLen) {
    setPrevLen(history.length);
    if (history.length > prevLen) setPageIndex(0);
  }

  // The same rows, the same hook and the same pager as the drawer —
  // one tree that reflows, never a `*Mobile` twin of the list.
  const savedPager = useSavedQueriesPager({
    queries: savedQueries,
    hasMore: savedHasMore,
    loadMore: onLoadMoreSaved,
    isLoadingMore: savedLoadingMore,
    error: savedError,
    resetKey: space?.id ?? '',
    // Only while the Saved tab is the one showing: on History this surface would otherwise
    // walk a listing for a list that is not on screen.
    enabled: tab === 'saved'
  });
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);

  const error = tab === 'saved' ? savedError : historyError;
  const isLoading = tab === 'saved' ? savedLoading : historyLoading;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h1 className="sr-only">Query workspace</h1>

      <div className="flex-none border-b border-border bg-surface px-4 py-3">
        <div
          role="group"
          aria-label="Query lists"
          className="inline-flex w-full gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
          {TABS.map(({value, label}) => {
            const active = tab === value;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={active}
                onClick={() => onTabChange(value)}
                className={cx(
                  'h-10 flex-1 rounded-sm px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                  active ? 'bg-surface font-semibold text-accent-text shadow-sm' : 'text-text-2 hover:text-text'
                )}>
                {label}
              </button>
            );
          })}
        </div>
        {/* Run is disabled because the tab is busy — say so rather than leaving
            every card greyed out with no reason. */}
        {runDisabled && <p className="pt-2 text-xs text-text-3">A query is running — Run is back when it finishes.</p>}
        {tab === 'saved' && (
          <SavedQuerySpaceSelect
            spaces={spaces}
            space={space}
            onSelectSpace={onSelectSpace}
            className="pt-3"
          />
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {!!error && (
          <Banner
            variant="danger"
            title={tab === 'saved' ? 'Couldn’t load saved queries.' : 'Couldn’t load history.'}>
            {toUserText(error)}
          </Banner>
        )}

        {isLoading || (tab === 'saved' && savedPager.isFilling) ? (
          <p className="text-sm text-text-3">Loading&hellip;</p>
        ) : tab === 'saved' ? (
          savedPager.isEmpty ? (
            error ? null : (
              <EmptyState
                title={`No saved queries in ${space?.label ?? 'this space'}`}
                hint="Save a query on a larger screen and it’ll appear here to run."
              />
            )
          ) : (
            savedPager.page.map((q) => (
              <div
                key={q.key}
                className="rounded-md border border-border bg-surface p-3">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="truncate font-semibold text-text">{q.name}</span>
                  <span
                    className="ml-auto flex-none text-xs text-text-3"
                    title={new Date(q.updatedAt).toLocaleString()}>
                    {formatRelativeTime(q.updatedAt)}
                  </span>
                </div>
                {/* No SQL preview: a `.sql` file carries no body until it is read, and a
                    preview per row would be a GetObject per row. */}
                <p className="text-sm text-text-3">{formatBytes(q.size)}</p>
                <div className="mt-2 flex items-center gap-3">
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => onViewSaved(q)}
                    aria-label={`View saved query ${q.name}`}
                    className={cardAction}>
                    View
                  </button>
                  <button
                    type="button"
                    onClick={() => onRunSaved(q)}
                    disabled={runDisabled}
                    aria-label={`Run saved query ${q.name}`}
                    className={cardAction}>
                    Run
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(q)}
                    aria-label={`Delete saved query ${q.name}`}
                    className={cx(cardAction, 'text-danger hover:bg-danger-soft focus-visible:ring-danger')}>
                    Delete
                  </button>
                </div>
              </div>
            ))
          )
        ) : history.length === 0 ? (
          error ? null : (
            <EmptyState
              title="No queries yet"
              hint="Queries you run show up here so you can run them again."
            />
          )
        ) : (
          pageEntries.map((entry) => (
            <QueryHistoryRow
              key={`${entry.queryExecutionId}-${entry.submittedAt}`}
              entry={entry}
              onReopen={() => onView(entry.sql, 'Query')}
              onRerun={() => onRun(entry.sql, 'Query')}
              rerunDisabled={runDisabled}
              openLabel="View"
              openAriaLabel="View this query"
              runLabel="Run"
              runAriaLabel="Run this query"
            />
          ))
        )}
      </div>

      {tab === 'history' && !historyLoading && history.length > 0 && (
        <Pager
          className="flex-none border-t border-border bg-surface px-4 py-3"
          hasPrev={safeIndex > 0}
          hasNext={safeIndex < pageCount - 1}
          onPrev={() => setPageIndex(Math.max(0, safeIndex - 1))}
          onNext={() => setPageIndex(Math.min(pageCount - 1, safeIndex + 1))}
          label={
            <>
              {start + 1}–{start + pageEntries.length} of {history.length}
              <span className="sr-only"> (page {safeIndex + 1})</span>
            </>
          }
        />
      )}

      {/* Follows the ROWS, not the error: a failed page keeps what is loaded and Prev
          stays reachable. */}
      {tab === 'saved' && !savedLoading && savedPager.page.length > 0 && (
        <Pager
          className="flex-none border-t border-border bg-surface px-4 py-3"
          hasPrev={savedPager.hasPrev}
          hasNext={savedPager.hasNext}
          onPrev={savedPager.onPrev}
          onNext={savedPager.onNext}
          nextBusy={savedPager.isFetching}
          label={savedPager.label}
        />
      )}

      {pendingDelete && (
        <SavedQueryDeleteConfirm
          query={pendingDelete}
          onConfirm={() => {
            onDeleteSaved(pendingDelete);
            setPendingDelete(null);
          }}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
