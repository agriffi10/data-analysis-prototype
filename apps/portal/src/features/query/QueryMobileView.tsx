import {useState} from 'react';
import {Banner} from '../../components/Banner';
import {DocumentIcon} from '../../components/icons';
import {Pager} from '../../components/Pager';
import {cx} from '../../lib/cx';
import {toUserMessage} from '../../lib/errorMessages';
import {QueryHistoryRow} from './QueryHistoryRow';
import {QUERY_HISTORY_PAGE_SIZE} from './query.constants';
import {formatRelativeTime} from './query.format';
import type {MobileHomeTab, QueryHistoryEntry, SavedQuery} from './query.types';

type QueryMobileViewProps = {
  /** Which list is showing; owned by the workspace so Back returns to it. */
  tab: MobileHomeTab;
  onTabChange: (tab: MobileHomeTab) => void;
  savedQueries: SavedQuery[];
  savedLoading: boolean;
  /** Raw fetch error (or null); rendered via `toUserMessage`. */
  savedError: unknown;
  history: QueryHistoryEntry[];
  historyLoading: boolean;
  historyError: unknown;
  /** Submit this SQL through the shared run path and open the results view. */
  onRun: (sql: string, title: string) => void;
  /** Open the results view read-only, without running. */
  onView: (sql: string, title: string) => void;
  /** True while a run is in flight — Run is unavailable until it settles. */
  runDisabled: boolean;
};

const TABS: ReadonlyArray<{value: MobileHomeTab; label: string}> = [
  {value: 'saved', label: 'Saved'},
  {value: 'history', label: 'History'}
];

// ≥44px touch target on a phone (SPEC-100 Phase 4).
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
  savedQueries,
  savedLoading,
  savedError,
  history,
  historyLoading,
  historyError,
  onRun,
  onView,
  runDisabled
}: QueryMobileViewProps) {
  // Client-side Prev/Next over the in-memory newest-first history, mirroring the
  // desktop drawer's pager (SPEC-042) — replace-style, never infinite scroll.
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

  const sortedSaved = [...savedQueries].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
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
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {!!error && (
          <Banner
            variant="danger"
            title={tab === 'saved' ? 'Couldn’t load saved queries.' : 'Couldn’t load history.'}>
            {toUserMessage(error).message}
          </Banner>
        )}

        {isLoading ? (
          <p className="text-sm text-text-3">Loading&hellip;</p>
        ) : tab === 'saved' ? (
          sortedSaved.length === 0 ? (
            error ? null : (
              <EmptyState
                title="No saved queries yet"
                hint="Save a query on a larger screen and it’ll appear here to run."
              />
            )
          ) : (
            sortedSaved.map((q) => {
              const preview = q.sql.replace(/\s+/g, ' ').trim();
              return (
                <div
                  key={q.id}
                  className="rounded-md border border-border bg-surface p-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="truncate font-semibold text-text">{q.name}</span>
                    <span
                      className="ml-auto flex-none text-xs text-text-3"
                      title={new Date(q.updatedAt).toLocaleString()}>
                      {formatRelativeTime(q.updatedAt)}
                    </span>
                  </div>
                  <p
                    className="truncate font-mono text-sm text-text-2"
                    title={preview}>
                    {preview}
                  </p>
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex-1" />
                    <button
                      type="button"
                      onClick={() => onView(q.sql, q.name)}
                      aria-label={`View saved query ${q.name}`}
                      className={cardAction}>
                      View
                    </button>
                    <button
                      type="button"
                      onClick={() => onRun(q.sql, q.name)}
                      disabled={runDisabled}
                      aria-label={`Run saved query ${q.name}`}
                      className={cardAction}>
                      Run
                    </button>
                  </div>
                </div>
              );
            })
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
    </div>
  );
}
