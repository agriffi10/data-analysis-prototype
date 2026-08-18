import {useState} from 'react';
import {Link} from 'react-router';
import {Banner} from '../../components/Banner';
import {Button} from '../../components/Button';
import {PageLayout} from '../../components/PageLayout';
import {Pager} from '../../components/Pager';
import {RefreshIconButton} from '../../components/RefreshIconButton';
import {SegmentedFilter} from '../../components/SegmentedFilter';
import {spaceBuckets} from '../../lib/userSpace';
import {usePageTitle} from '../../hooks/usePageTitle';
import {useClientPager} from '../../hooks/useClientPager';
import {useAuth} from '../auth';
import {useConnections} from '../connections/useConnections';
import {useFeature} from '../feature-flags';
import {usableSpaceTargets} from '../file-browser';
import {useDataQualityRuns} from './useDataQualityRuns';
import {useDataQualityCheck, type DataQualityTarget} from './useDataQualityCheck';
import {StartQualityCheckDialog} from './StartQualityCheckDialog';
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

  // The second entry point into a check. Spaces are REUSED from
  // `usableSpaceTargets`, not re-derived: `useConnections` carries no bucket and no root
  // prefix, and a third derivation of that mapping would be the one that drifts.
  const {user} = useAuth();
  const {connections} = useConnections(user?.username ?? null);
  const buckets = spaceBuckets();
  // Same shared-workspace surface as the move/copy picker: with shared workspaces
  // off, this dialog must not be the remaining way to reach a shared space by name.
  const sharedSpacesEnabled = useFeature('sharedWorkspaces');
  const spaces = usableSpaceTargets(connections, user?.username ?? null, buckets.user, buckets.shared).filter(
    (space) => sharedSpacesEnabled || space.kind === 'personal'
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [started, setStarted] = useState<string | null>(null);
  const {start: startCheck, isPending} = useDataQualityCheck();

  const handleStart = async (target: DataQualityTarget) => {
    // `toast: false` — the banner below is the receipt, and it says strictly more than the
    // toast does. One action, one confirmation. A FAILURE still toasts (the hook owns that
    // wording) and returns false, so the dialog stays open with the target intact rather
    // than costing the user a selection they can't get back.
    const ok = await startCheck(target, {toast: false});
    if (!ok) return;
    setStarted(target.location);
    setDialogOpen(false);
  };

  const [filter, setFilter] = useState<Filter>('all');
  const visible =
    filter === 'all'
      ? runs
      : runs.filter((run) => (filter === 'clean' ? run.verdict === 'clean' : run.verdict !== 'clean'));

  // Clamped client-side pager: a shrunk list never strands the user on a blank page.
  const {pageItems, pagerProps, resetToFirst} = useClientPager(visible, PAGE_SIZE);

  const applyFilter = (next: Filter) => {
    setFilter(next);
    resetToFirst();
  };

  const [refreshing, setRefreshing] = useState(false);
  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
    resetToFirst();
  };

  return (
    <PageLayout
      title="Data quality"
      contentClassName="max-w-[920px] gap-2"
      stackActionsOnMobile
      actions={
        <>
          <SegmentedFilter
            label="Filter checks"
            options={FILTERS}
            value={filter}
            onChange={applyFilter}
          />
          <RefreshIconButton
            label="Refresh data quality checks"
            busy={refreshing}
            onClick={() => void handleRefresh()}
          />
          {/* Starting a check NEVER depends on the history being readable, so this
              renders in every list state — including the error one. */}
          {spaces.length > 0 && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setDialogOpen(true)}>
              New quality check
            </Button>
          )}
        </>
      }>
      {/* Shown ABOVE the list and never replacing it, so a failed Refresh is
          non-destructive — the rows already on screen stay readable. */}
      {error && (
        <Banner
          variant="danger"
          title={error}
          retry={() => void handleRefresh()}
          className="mb-2"
        />
      )}

      {/* A check that has just started is NOT in the list and will not be
          for minutes, so without this the most common first impression of the feature is
          "I pressed the button and nothing happened." It reports that the check STARTED —
          never that it will pass — and does not survive a reload: it is a receipt for an
          action just taken, not a state of the world. */}
      {started !== null && (
        <Banner
          variant="info"
          role="status"
          title="Check started"
          onDismiss={() => setStarted(null)}
          className="mb-2">
          We’re checking <span className="font-mono">{started}</span> in the background. It will appear in this list
          when it finishes, and you’ll get a notification either way.
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
                ? 'Pick a folder or a file and we’ll check it for missing values, ragged rows, and type problems.'
                : 'Try a different filter to see your other checks.'}
            </p>
            {/* SPEC-124 FR-001 amends SPEC-123 FR-005's copy: the empty state used to send
                the user to the Files browser. Files is still a valid entry point (and the
                help content still says so) — the page just stops sending them away from the
                one place that can now do the job. */}
            {runs.length === 0 && spaces.length > 0 && (
              <Button
                variant="primary"
                className="mt-4"
                onClick={() => setDialogOpen(true)}>
                New quality check
              </Button>
            )}
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
            {...pagerProps}
          />
        </>
      )}

      <CompletedOnlyNote />

      {dialogOpen && (
        <StartQualityCheckDialog
          spaces={spaces}
          isPending={isPending}
          onStart={(target) => void handleStart(target)}
          onCancel={() => setDialogOpen(false)}
        />
      )}
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
 * WHY IT NOW SAYS "always" AND NOT "usually". SPEC-114 FR-004 makes the failure notification
 * survive everything that happens once an execution has STARTED — including a Lambda import
 * error and a Step Functions-level error, neither of which any verb can catch. What it could
 * not cover was a request that never started an execution at all (a malformed body the Pipe
 * rejects, which exhausts its receives into the DLQ): nothing ran, so nothing notified, and
 * this line hedged with "usually" for exactly that gap. **SPEC-126** closed it — the request
 * DLQs drain back into the notification pipeline — so the hedge is now the inaccuracy.
 *
 * The remaining hole is the NOTIFICATIONS DLQ itself, which SPEC-126 deliberately leaves
 * undrained (draining it through the queue that just failed to deliver is circular). That is
 * a failure of the delivery channel, not of the check — if it breaks, no wording on this page
 * is reaching the user anyway.
 *
 * This is the STANDING explanation; SPEC-124's post-enqueue banner is the MOMENTARY one.
 * Together they are what keeps a completed-only list honest: the banner covers the check the
 * user just started and cannot yet see, this line covers every check that will never appear.
 */
function CompletedOnlyNote() {
  return (
    <p className="mt-4 px-1 text-xs text-text-3">
      This lists checks that finished. A check that failed always reports itself in your{' '}
      <Link
        to="/notifications"
        className="underline underline-offset-2 hover:text-text-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        notifications
      </Link>{' '}
      instead.
    </p>
  );
}
