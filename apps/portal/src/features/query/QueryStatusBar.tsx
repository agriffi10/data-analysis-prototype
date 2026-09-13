import {useEffect, useState} from 'react';
import {formatBytes} from '../../lib/format';
import {formatCount, formatDurationMs} from '../../lib/format';
import type {QueryStatus} from '../catalog/catalog.types';

type QueryStatusBarProps = {
  status?: QueryStatus;
  isInFlight: boolean;
  startedAt: number | null;
  /**
   * Multi-statement batch progress: 1-based current statement
   * + total. Supplied only when the run holds more than one statement.
   */
  batch?: {current: number; total: number};
  /** Loaded-count fallback shown while the exact total is still being counted. */
  rowCount?: number;
  hasMoreRows?: boolean;
  /**
   * Whether the succeeded query returned a result set. False for DDL/no-result
   * statements, which show no row-count stat at all.
   */
  hasResultSet?: boolean;
  /** Exact total from the background page-walk; null while still counting. */
  totalRowCount?: number | null;
  /**
   * Whether the displayed result is savable (row-returning, not pure DDL). Offered
   * alongside any verdict, not only success: a batch that failed or was stopped at a later
   * statement still shows an earlier statement's complete, already-billed result.
   */
  canSaveResults?: boolean;
  onSaveResults: () => void;
  /**
   * The batch ended on a failure. It owns the verdict even where `status` disagrees: a
   * statement whose status could not be read has no terminal state to show, and one that
   * never started leaves an earlier statement's success on display.
   */
  batchFailed?: boolean;
};

/**
 * The row-count fragment for a succeeded, row-returning query. Prefers the exact
 * background total; until it resolves, falls back to today's loaded
 * count with a "+" when more pages exist.
 */
function rowCountLabel({
  rowCount,
  hasMoreRows,
  totalRowCount
}: Pick<QueryStatusBarProps, 'rowCount' | 'hasMoreRows' | 'totalRowCount'>): string {
  if (totalRowCount !== null && totalRowCount !== undefined) return `${formatCount(totalRowCount)} rows`;
  return `${formatCount(rowCount ?? 0)}${hasMoreRows ? '+' : ''} rows`;
}

/**
 * Slim execution-status bar below the editor. An accessible live region;
 * state is never color-only (icon/spinner + text). FAILED's reason is shown
 * by the workspace's danger Banner — here it is only the terminal indicator,
 * and Save-results sits beside whichever terminal state is showing.
 */
export function QueryStatusBar({
  status,
  isInFlight,
  startedAt,
  batch,
  rowCount,
  hasMoreRows,
  hasResultSet = true,
  totalRowCount = null,
  canSaveResults = false,
  onSaveResults,
  batchFailed = false
}: QueryStatusBarProps) {
  // Tick once a second while in flight so the elapsed time advances. The initial
  // tick is scheduled async (setTimeout) rather than set synchronously in the
  // effect body, so the first render's elapsed appears within a frame.
  const [nowTick, setNowTick] = useState(0);
  useEffect(() => {
    if (!isInFlight) return;
    const update = () => setNowTick(Date.now());
    const initial = setTimeout(update, 0);
    const timer = setInterval(update, 1000);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [isInFlight]);

  const elapsedMs = isInFlight && startedAt && nowTick ? nowTick - startedAt : undefined;
  const state = status?.state;
  const verdict = !isInFlight && batchFailed ? 'FAILED' : state;
  // A settled verdict must be on screen for anything that hangs off the result to have
  // something to sit beside. Two ways there isn't one, and both leave a lone button on an
  // otherwise empty bar: a resubmit clears the status a history round-trip before the new run
  // is marked in flight, leaving the previous run `done` with no status at all; and
  // `isInFlight` tracks the BATCH, so it is not by itself proof the statement settled.
  const hasVerdict = !isInFlight && (verdict === 'SUCCEEDED' || verdict === 'FAILED' || verdict === 'CANCELLED');

  // The bar wraps onto a second line on a phone; the shipped
  // single-row bar is restored from `tablet:` up.
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-11 flex-none flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface px-4 py-2 text-sm tablet:h-11 tablet:flex-nowrap tablet:px-5 tablet:py-0">
      {isInFlight && (
        <>
          <span className="inline-flex items-center gap-2 font-semibold text-accent-text">
            <span
              className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent-soft border-t-accent"
              aria-hidden="true"
            />
            {state === 'QUEUED' ? 'Queued…' : 'Running…'}
          </span>
          <span className="text-text-2">
            {batch && `Statement ${batch.current} of ${batch.total} · `}
            elapsed {formatDurationMs(elapsedMs)}
            {status?.dataScannedBytes !== undefined && ` · ${formatBytes(status.dataScannedBytes)} scanned`}
          </span>
          <span
            className="h-1.5 w-40 overflow-hidden rounded-full bg-accent-soft"
            aria-hidden="true">
            <span className="block h-full w-1/2 animate-pulse rounded-full bg-accent" />
          </span>
        </>
      )}

      {!isInFlight && verdict === 'SUCCEEDED' && (
        <>
          <span className="inline-flex items-center gap-2 font-semibold text-success">
            <span
              className="h-2 w-2 rounded-full bg-success"
              aria-hidden="true"
            />
            Succeeded
          </span>
          <span className="text-text-2">
            {batch && batch.current === batch.total && `Script finished · ${batch.total} statements · `}
            {hasResultSet && `${rowCountLabel({rowCount, hasMoreRows, totalRowCount})} · `}
            {formatBytes(status?.dataScannedBytes)} scanned · {formatDurationMs(status?.engineExecutionTimeMillis)}
          </span>
        </>
      )}

      {!isInFlight && verdict === 'FAILED' && (
        <span className="inline-flex items-center gap-2 font-semibold text-danger">
          <span
            className="h-2 w-2 rounded-full bg-danger"
            aria-hidden="true"
          />
          Failed
        </span>
      )}

      {!isInFlight && verdict === 'CANCELLED' && (
        <span className="inline-flex items-center gap-2 font-semibold text-text-2">
          <span
            className="h-2 w-2 rounded-full bg-text-3"
            aria-hidden="true"
          />
          Cancelled
        </span>
      )}

      {/* Says WHAT Save would write. A non-succeeded run only ever displays a result when an
          earlier statement produced one, and in `script-single` scope there is no result-tab
          strip naming it — so without this the file's contents are unidentifiable. The row
          count is the displayed execution's; the failed statement's bytes and duration stay
          off the bar, which is what keeps the two executions from reading as one. */}
      {hasVerdict && verdict !== 'SUCCEEDED' && canSaveResults && (
        <span className="text-text-2">
          {rowCountLabel({rowCount, hasMoreRows, totalRowCount})} from an earlier statement
        </span>
      )}

      {/* Gated on the result, never on the verdict — the rows a failed or stopped batch
          already produced are complete, and re-running to reach Save bills them twice. */}
      {hasVerdict && canSaveResults && (
        <>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onSaveResults}
            className="inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm font-medium text-text-2 hover:bg-surface-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true">
              <path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
              <path d="M9 4v5h6" />
              <path d="M8 21v-7h8v7" />
            </svg>
            Save results to my files
          </button>
        </>
      )}
    </div>
  );
}
