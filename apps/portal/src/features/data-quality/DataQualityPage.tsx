import {useState} from 'react';
import {Link} from 'react-router-dom';
import {Banner} from '../../components/Banner';
import {IconButton} from '../../components/IconButton';
import {PageLayout} from '../../components/PageLayout';
import {Pager} from '../../components/Pager';
import {cx} from '../../lib/cx';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useDataQualityRuns} from './useDataQualityRuns';
import {DataQualityRunRow} from './DataQualityRunRow';

const PAGE_SIZE = 10;

type Filter = 'all' | 'issues' | 'clean';

const FILTERS: {value: Filter; label: string}[] = [
  {value: 'all', label: 'All'},
  {value: 'issues', label: 'Issues found'},
  {value: 'clean', label: 'Clean'}
];

/**
 * The data-quality runs dashboard: every completed check the user can see, newest first,
 * 10 per page, filterable by verdict, each row linking to its full report.
 *
 * It exists because a report used to be reachable ONLY from its notification, so dismissing
 * that notification effectively lost the report.
 */
export function DataQualityPage() {
  usePageTitle('Data quality');
  const {runs, isLoading, error, refresh} = useDataQualityRuns();

  const [filter, setFilter] = useState<Filter>('all');
  const visible =
    filter === 'all'
      ? runs
      : runs.filter((run) => (filter === 'clean' ? run.verdict === 'clean' : run.verdict !== 'clean'));

  // Client-side pager over the in-memory list, clamped so a shrunk list never strands the
  // user on a blank page (the NotificationsPage shape).
  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const safeIndex = Math.min(pageIndex, pageCount - 1);
  const start = safeIndex * PAGE_SIZE;
  const pageItems = visible.slice(start, start + PAGE_SIZE);

  const applyFilter = (next: Filter) => {
    setFilter(next);
    setPageIndex(0);
  };

  const [refreshing, setRefreshing] = useState(false);
  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
    setPageIndex(0);
  };

  return (
    <PageLayout
      title="Data quality"
      contentClassName="max-w-[920px] gap-2"
      stackActionsOnMobile
      actions={
        <>
          <FilterTabs
            filter={filter}
            onChange={applyFilter}
          />
          <IconButton
            label="Refresh data quality checks"
            size="sm"
            disabled={refreshing}
            onClick={() => void handleRefresh()}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={cx('h-4 w-4', refreshing && 'animate-spin')}
              aria-hidden="true">
              <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              <path d="M21 3v5h-5" />
              <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
              <path d="M3 21v-5h5" />
            </svg>
          </IconButton>
        </>
      }>
      {/* Shown ABOVE the list and never replacing it, so a failed Refresh is
          non-destructive — the rows already on screen stay readable. */}
      {error && (
        <Banner
          variant="danger"
          title={error}
          className="mb-2">
          <button
            type="button"
            onClick={() => void handleRefresh()}
            className="font-semibold underline underline-offset-2 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Try again
          </button>
        </Banner>
      )}

      {isLoading ? (
        <p
          role="status"
          className="px-1 py-10 text-center text-sm text-text-3">
          Loading data quality checks…
        </p>
      ) : visible.length === 0 ? (
        error ? null : (
          <div className="rounded-lg border border-dashed border-border bg-surface-2 px-5 py-12 text-center">
            <p className="text-sm font-medium text-text">
              {runs.length === 0 ? 'No quality checks yet' : 'No checks match this filter'}
            </p>
            <p className="mt-1 text-sm text-text-3">
              {runs.length === 0
                ? 'Start one from any file or folder in Files — select it, then choose Check quality.'
                : 'Try a different filter to see your other checks.'}
            </p>
          </div>
        )
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {pageItems.map((run) => (
              <DataQualityRunRow
                key={`${run.space}/${run.requestId}`}
                run={run}
              />
            ))}
          </ul>
          <Pager
            className="mt-2"
            hasPrev={safeIndex > 0}
            hasNext={safeIndex < pageCount - 1}
            onPrev={() => setPageIndex(Math.max(0, safeIndex - 1))}
            onNext={() => setPageIndex(Math.min(pageCount - 1, safeIndex + 1))}
            label={
              <>
                {start + 1}–{start + pageItems.length} of {visible.length}
                <span className="sr-only"> (page {safeIndex + 1})</span>
              </>
            }
          />
        </>
      )}

      <CompletedOnlyNote />
    </PageLayout>
  );
}

/**
 * THE LINE THAT CONVERTS AN OMISSION INTO A SIGNPOST.
 *
 * This page lists completed checks only — a run that fails before `assemble-report` never
 * writes an index entry, so it has no row here. A history page that silently omits failures
 * teaches the user to trust a list that is lying to them, so the omission is stated.
 *
 * WHY IT IS WORDED "usually" RATHER THAN AS A GUARANTEE. SPEC-114 FR-004 makes the failure
 * notification survive everything that happens once an execution has STARTED — including a
 * Lambda import error and a Step Functions-level error, neither of which any verb can catch.
 * What it cannot cover is a request that never starts an execution at all (a malformed body
 * the Pipe rejects, which exhausts its receives into the DLQ): nothing ran, so nothing can
 * notify. **SPEC-126** closes that by draining the DLQs back into the notification pipeline,
 * and is not built yet. Until it ships, promising "you'll always get a notification" would
 * be the page making a claim the system does not yet honour — the precise failure this line
 * exists to prevent, merely relocated. Tighten the wording when SPEC-126 lands.
 */
function CompletedOnlyNote() {
  return (
    <p className="mt-4 px-1 text-xs text-text-3">
      This lists checks that finished. A check that failed usually reports itself in your{' '}
      <Link
        to="/notifications"
        className="underline underline-offset-2 hover:text-text-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        notifications
      </Link>{' '}
      instead.
    </p>
  );
}

// All / Issues found / Clean segmented control — `aria-pressed` on each, so the choice is
// never conveyed by styling alone.
function FilterTabs({filter, onChange}: {filter: Filter; onChange: (next: Filter) => void}) {
  return (
    <div
      role="group"
      aria-label="Filter checks"
      className="inline-flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
      {FILTERS.map(({value, label}) => {
        const active = filter === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(value)}
            className={cx(
              'h-7 rounded-sm px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active ? 'bg-surface font-semibold text-accent-text shadow-sm' : 'text-text-2 hover:text-text'
            )}>
            {label}
          </button>
        );
      })}
    </div>
  );
}
