import {Banner, type BannerVariant} from '../../components/Banner';
import {cx} from '../../lib/cx';
import {ResultTabs} from './ResultTabs';
import {ResultsPageSizeControl} from './ResultsPageSizeControl';
import {QueryStatusBar} from './QueryStatusBar';
import {QueryResultsTable} from './QueryResultsTable';
import type {QueryStatus} from '../catalog/catalog.types';
import type {TabRun} from './useTabRuns';
import type {UseQueryResultsResult} from '../catalog/useQueryResults';
import type {UseResultsPageSizeResult} from './useResultsPageSize';
import type {UseColumnWidthsResult} from '../catalog/useColumnWidths';

type Props = {
  /** The active tab's run, if it has one. */
  run: TabRun | undefined;
  status: QueryStatus | undefined;
  /** The batch hasn't reached a terminal state. */
  isInFlight: boolean;
  batchDone: boolean;
  /**
   * The editor shell may narrate this run — false for a run the mobile surface
   * submitted, which leaves the editor buffer untouched by design.
   */
  editorOwnsRun: boolean;
  /** Non-null once the editor's own run has an execution — gates the status bar. */
  editorExecutionId: string | null;
  /** The execution the grid renders, or null for the empty state. */
  editorDisplayExecutionId: string | null;
  /** The execution the results query is keyed to (may belong to a disowned run). */
  displayExecutionId: string | null;
  hasResultSet: boolean;
  totalRowCount: number | null;
  results: UseQueryResultsResult;
  pageSize: UseResultsPageSizeResult;
  colWidths: UseColumnWidthsResult;
  /** show the tab-per-statement scope's result-tab strip. */
  showResultTabs: boolean;
  showError: boolean;
  errorMessage: string | null;
  /** The banner's title and variant, which follow the message shown. Default to a failure's. */
  errorTitle?: string;
  errorVariant?: BannerVariant;
  onDismissError: () => void;
  onSelectResultTab: (index: number) => void;
  canSaveResults: boolean;
  onSaveResults: () => void;
};

/**
 * Everything below the editor pane: the status bar, the failure banner, and the
 * results region — the result-tab strip, the page-size control,
 * and either the grid or the empty state that explains why there is none.
 */
export function QueryResultsRegion({
  run,
  status,
  isInFlight,
  batchDone,
  editorOwnsRun,
  editorExecutionId,
  editorDisplayExecutionId,
  displayExecutionId,
  hasResultSet,
  totalRowCount,
  results,
  pageSize,
  colWidths,
  showResultTabs,
  showError,
  errorMessage,
  errorTitle = 'Query failed.',
  errorVariant = 'danger',
  onDismissError,
  onSelectResultTab,
  canSaveResults,
  onSaveResults
}: Props) {
  return (
    <>
      {editorExecutionId !== null && (
        <QueryStatusBar
          status={status}
          isInFlight={isInFlight}
          startedAt={run?.startedAt ?? null}
          batch={
            run && run.statements.length > 1 ? {current: run.currentIndex + 1, total: run.statements.length} : undefined
          }
          rowCount={displayExecutionId !== null ? results.loadedRowCount : undefined}
          hasMoreRows={results.hasMoreServer}
          hasResultSet={hasResultSet}
          totalRowCount={totalRowCount}
          canSaveResults={canSaveResults}
          onSaveResults={onSaveResults}
          batchFailed={!!run?.failure}
          stillRunning={!!run?.stillRunning}
        />
      )}

      {showError && editorOwnsRun && (
        <div className="px-5 pt-4">
          <Banner
            variant={errorVariant}
            title={errorTitle}
            onDismiss={onDismissError}>
            {/* friendly, mapped guidance — no raw Athena
          engine text (the raw reason is dev-logged + kept in history). */}
            <p className="text-sm">{errorMessage}</p>
          </Banner>
        </div>
      )}

      <div className={cx('flex min-h-0 flex-1 flex-col overflow-hidden px-5 py-4')}>
        {/* the tab-per-statement scope gets a result-tab
      strip; the other scopes render a single result view. Tabs are
      ephemeral — a new run replaces the tab's run state wholesale. */}
        {showResultTabs && run && (
          <ResultTabs
            tabs={run.resultTabs}
            activeIndex={run.activeResultTabIndex}
            onSelect={onSelectResultTab}
          />
        )}
        {/* the Results header row carries the "Rows per
      page" control — above the grid, right under the status bar's
      row-count stat, and always rendered (disabled, never hidden,
      when there's no result set to page). */}
        <div className="mb-3 flex flex-none flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">Results</h2>
          <ResultsPageSizeControl
            pageSize={pageSize.pageSize}
            onCommit={pageSize.setPageSize}
            disabled={!hasResultSet || !editorOwnsRun}
          />
        </div>
        {editorDisplayExecutionId !== null ? (
          <div
            className="flex min-h-0 flex-1 flex-col"
            {...(showResultTabs &&
              run && {
                role: 'tabpanel',
                id: 'result-tabpanel',
                'aria-labelledby': `result-tab-${run.activeResultTabIndex}`
              })}>
            <QueryResultsTable
              columns={results.columns}
              rows={results.rows}
              pageIndex={results.pageIndex}
              rangeStart={results.rangeStart}
              rangeEnd={results.rangeEnd}
              // The workspace's one total — the same number the status bar above shows. It
              // already prefers this pager's own count once the last page is loaded, so there is
              // nothing to combine here, and combining a second time is how two surfaces drift.
              totalRowCount={totalRowCount}
              hasPrev={results.hasPrev}
              hasNext={results.hasNext}
              isFetchingNext={results.isFetchingNext}
              isLoading={results.isPending}
              widths={colWidths.widths}
              onResize={colWidths.setWidth}
              onResetColumn={colWidths.resetColumn}
              onPrev={results.goPrev}
              onNext={results.goNext}
            />
          </div>
        ) : (
          <p className="flex h-full items-center justify-center text-sm text-text-3">
            {/* A disowned run isn't this buffer's to narrate — but while
              it holds the tab it locks the toolbar, so silence would
              leave that unexplained. */}
            {isInFlight
              ? editorOwnsRun
                ? 'Running your query…'
                : 'A query you started on a smaller screen is still running.'
              : editorOwnsRun && batchDone && status?.state === 'SUCCEEDED'
                ? 'The run finished without returning rows.'
                : 'Run a query to see results.'}
          </p>
        )}
      </div>
    </>
  );
}
