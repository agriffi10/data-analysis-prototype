import {Banner} from '../../components/Banner';
import {IconButton} from '../../components/IconButton';
import {ChevronLeftIcon} from '../../components/icons';
import {Pager} from '../../components/Pager';
import {QueryStatusBar} from './QueryStatusBar';
import type {QueryStatus} from './query.types';
import type {UseQueryResultsResult} from './useQueryResults';

type QueryResultsMobileProps = {
  /** Saved-query name (or a generic label for a history entry). */
  title: string;
  /** The SQL this view shows — read-only; there is no editor below `tablet`. */
  sql: string;
  onBack: () => void;
  onRun: () => void;
  runDisabled: boolean;
  /** Live execution state for this tab, from the workspace's poller. */
  status?: QueryStatus;
  isInFlight: boolean;
  startedAt: number | null;
  /** False for DDL / no-result statements, so no row-count stat is claimed. */
  hasResultSet: boolean;
  totalRowCount: number | null;
  /** True once a run has been submitted from this view (or the card that opened it). */
  hasRun: boolean;
  /** Friendly, already-mapped failure text (SPEC-106); null when there's nothing to show. */
  errorMessage: string | null;
  onDismissError: () => void;
  /** The workspace's shared pager — one page in the DOM at a time. */
  results: UseQueryResultsResult;
  /** Null until a run settles on a displayable execution. */
  displayExecutionId: string | null;
};

/**
 * The mobile (`< tablet`) results view (SPEC-100 FR-006): back + query name +
 * re-run, a **read-only** SQL preview, the shared status strip, one card per
 * result row (column → value), and a fixed Prev/Next pager. Paging is
 * replace-style, exactly as on desktop — never infinite scroll. All data comes
 * from the workspace's existing execution/results state; this view fetches
 * nothing.
 */
export function QueryResultsMobile({
  title,
  sql,
  onBack,
  onRun,
  runDisabled,
  status,
  isInFlight,
  startedAt,
  hasResultSet,
  totalRowCount,
  hasRun,
  errorMessage,
  onDismissError,
  results,
  displayExecutionId
}: QueryResultsMobileProps) {
  const {columns, rows} = results;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <IconButton
          label="Back to queries"
          onClick={onBack}>
          <ChevronLeftIcon className="h-5 w-5" />
        </IconButton>
        <h1 className="min-w-0 flex-1 truncate text-base font-semibold text-text">{title}</h1>
        <button
          type="button"
          onClick={onRun}
          disabled={runDisabled}
          className="inline-flex h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <svg
            viewBox="0 0 24 24"
            fill="currentColor"
            stroke="none"
            className="h-4 w-4"
            aria-hidden="true">
            <path d="M7 5v14l11-7z" />
          </svg>
          Run
        </button>
      </div>

      <pre className="flex-none overflow-x-auto border-b border-border bg-surface-2 px-4 py-3 font-mono text-xs leading-relaxed text-text-2">
        {sql}
      </pre>

      {hasRun && (
        <QueryStatusBar
          status={status}
          isInFlight={isInFlight}
          startedAt={startedAt}
          rowCount={displayExecutionId !== null ? results.loadedRowCount : undefined}
          hasMoreRows={results.hasMoreServer}
          hasResultSet={hasResultSet}
          totalRowCount={totalRowCount}
          canSaveResults={false}
          onSaveResults={() => {}}
        />
      )}

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {!!errorMessage && (
          <Banner
            variant="danger"
            title="Query failed."
            onDismiss={onDismissError}>
            <p className="text-sm">{errorMessage}</p>
          </Banner>
        )}

        {displayExecutionId === null || rows.length === 0 ? (
          <p className="py-8 text-center text-sm text-text-3">
            {isInFlight
              ? 'Running your query…'
              : results.isPending && displayExecutionId !== null
                ? 'Loading results…'
                : hasRun && status?.state === 'SUCCEEDED'
                  ? 'The run finished without returning rows.'
                  : 'Run this query to see results.'}
          </p>
        ) : (
          rows.map((row, rowIndex) => (
            <dl
              key={`${results.pageIndex}-${rowIndex}`}
              aria-label={`Row ${results.rangeStart + rowIndex}`}
              className="rounded-md border border-border bg-surface p-3 text-sm">
              {columns.map((column, colIndex) => (
                <div
                  key={column.name}
                  className="flex gap-3 border-b border-border py-1.5 last:border-b-0">
                  <dt className="w-2/5 flex-none truncate font-medium text-text-3">{column.name}</dt>
                  <dd className="min-w-0 flex-1 break-words font-mono text-text">{row[colIndex]}</dd>
                </div>
              ))}
            </dl>
          ))
        )}
      </div>

      {displayExecutionId !== null && rows.length > 0 && (
        // A single page holding every row leaves both sides false, so the pager
        // renders disabled rather than disappearing (FR-006).
        <Pager
          className="flex-none border-t border-border bg-surface px-4 py-3"
          hasPrev={results.hasPrev}
          hasNext={results.hasNext}
          nextBusy={results.isFetchingNext}
          onPrev={results.goPrev}
          onNext={results.goNext}
          label={
            <>
              Rows {results.rangeStart}–{results.rangeEnd}
              {results.totalRowCount !== null && ` of ${results.totalRowCount}`}
            </>
          }
        />
      )}
    </div>
  );
}
