import {cx} from '../../lib/cx';
import {DocumentIcon} from '../../components/icons';
import {formatBytes, formatDurationMs, formatRelativeTime} from './query.format';
import type {QueryHistoryEntry, QueryState} from './query.types';

// Status → badge presentation. A prior-session entry left non-terminal (tab
// closed mid-run) has a non-terminal/absent status — shown as a neutral
// "Unknown", never a false "Running".
function badgeFor(status?: QueryState): {
  label: string;
  className: string;
  dotClassName: string;
} {
  switch (status) {
    case 'SUCCEEDED':
      return {
        label: 'Succeeded',
        className: 'bg-success-soft text-success',
        dotClassName: 'bg-success'
      };
    case 'FAILED':
      return {
        label: 'Failed',
        className: 'bg-danger-soft text-danger',
        dotClassName: 'bg-danger'
      };
    case 'CANCELLED':
      return {
        label: 'Cancelled',
        className: 'border border-border bg-surface-2 text-text-2',
        dotClassName: 'bg-text-3'
      };
    default:
      return {
        label: 'Unknown',
        className: 'border border-border bg-surface-2 text-text-2',
        dotClassName: 'bg-text-3'
      };
  }
}

/**
 * One history entry — status badge, relative time (absolute on hover),
 * single-line SQL preview, scanned/duration stats, Open + Re-run actions.
 */
export function QueryHistoryRow({
  entry,
  onReopen,
  onRerun,
  rerunDisabled
}: {
  entry: QueryHistoryEntry;
  onReopen: () => void;
  onRerun: () => void;
  rerunDisabled: boolean;
}) {
  const badge = badgeFor(entry.status);
  const preview = entry.sql.replace(/\s+/g, ' ').trim();
  const stats = [
    entry.dataScannedBytes !== undefined && `${formatBytes(entry.dataScannedBytes)} scanned`,
    entry.durationMs !== undefined && formatDurationMs(entry.durationMs)
  ].filter(Boolean);

  return (
    <div className="rounded-md border border-border p-3">
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cx(
            'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold',
            badge.className
          )}>
          <span
            className={cx('h-[7px] w-[7px] rounded-full', badge.dotClassName)}
            aria-hidden="true"
          />
          {badge.label}
        </span>
        <span
          className="ml-auto text-xs text-text-3"
          title={new Date(entry.submittedAt).toLocaleString()}>
          {formatRelativeTime(entry.submittedAt)}
        </span>
      </div>

      {entry.savedQueryName && (
        <span className="mb-1.5 inline-flex max-w-full items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-text">
          <DocumentIcon className="h-3 w-3 flex-none" />
          <span className="truncate">Saved: {entry.savedQueryName}</span>
        </span>
      )}

      <p
        className="truncate font-mono text-sm text-text"
        title={preview}>
        {preview}
      </p>

      <div className="mt-2 flex items-center gap-3">
        {stats.length > 0 && <span className="text-xs text-text-3">{stats.join(' · ')}</span>}
        <span className="min-w-0 truncate text-xs text-text-3">{entry.database}</span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onReopen}
          aria-label="Open this query in the editor"
          className="inline-flex min-h-6 items-center rounded-sm px-2 py-1 text-xs font-semibold text-accent-text hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Open
        </button>
        <button
          type="button"
          onClick={onRerun}
          disabled={rerunDisabled}
          aria-label="Re-run this query"
          className="inline-flex min-h-6 items-center rounded-sm px-2 py-1 text-xs font-semibold text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Re-run
        </button>
      </div>
    </div>
  );
}
