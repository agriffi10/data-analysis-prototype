import { cx } from '../../lib/cx';
import { formatBytes, formatDurationMs, formatRelativeTime } from './query.format';
import type { QueryHistoryEntry, QueryState } from './query.types';

// Status → badge presentation. A prior-session entry left non-terminal (tab
// closed mid-run) has a non-terminal/absent status — shown as a neutral
// "Unknown", never a false "Running" (SPEC-036 FR-005).
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
        dotClassName: 'bg-success',
      };
    case 'FAILED':
      return {
        label: 'Failed',
        className: 'bg-danger-soft text-danger',
        dotClassName: 'bg-danger',
      };
    case 'CANCELLED':
      return {
        label: 'Cancelled',
        className: 'border border-border bg-surface-2 text-text-2',
        dotClassName: 'bg-text-3',
      };
    default:
      return {
        label: 'Unknown',
        className: 'border border-border bg-surface-2 text-text-2',
        dotClassName: 'bg-text-3',
      };
  }
}

// SPEC-036 FR-001: one history entry — status badge, relative time (absolute on
// hover), single-line SQL preview, scanned/duration stats, Open + Re-run actions.
export function QueryHistoryRow({
  entry,
  onReopen,
  onRerun,
  rerunDisabled,
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
    entry.durationMs !== undefined && formatDurationMs(entry.durationMs),
  ].filter(Boolean);

  return (
    <div className="rounded-md border border-border p-3">
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cx(
            'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold',
            badge.className,
          )}
        >
          <span
            className={cx('h-[7px] w-[7px] rounded-full', badge.dotClassName)}
            aria-hidden="true"
          />
          {badge.label}
        </span>
        <span
          className="ml-auto text-xs text-text-3"
          title={new Date(entry.submittedAt).toLocaleString()}
        >
          {formatRelativeTime(entry.submittedAt)}
        </span>
      </div>

      <p
        className="truncate font-mono text-sm text-text"
        title={preview}
      >
        {preview}
      </p>

      <div className="mt-2 flex items-center gap-3">
        {stats.length > 0 && (
          <span className="text-xs text-text-3">{stats.join(' · ')}</span>
        )}
        <span className="min-w-0 truncate text-xs text-text-3">{entry.database}</span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onReopen}
          className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-accent-text hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          Open
        </button>
        <button
          type="button"
          onClick={onRerun}
          disabled={rerunDisabled}
          className="rounded-sm px-1.5 py-0.5 text-xs font-semibold text-accent-text hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          Re-run
        </button>
      </div>
    </div>
  );
}
