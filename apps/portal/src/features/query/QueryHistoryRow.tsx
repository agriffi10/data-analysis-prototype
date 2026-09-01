import {DocumentIcon} from '../../components/icons';
import {StatusPill, type StatusTone} from '../../components/StatusPill';
import {formatBytes} from '../../lib/format';
import {formatDurationMs, formatRelativeTime} from '../../lib/format';
import type {QueryHistoryEntry} from './query.types';
import type {QueryState} from '../catalog/catalog.types';

// Status → badge presentation. A prior-session entry left non-terminal (tab
// closed mid-run) has a non-terminal/absent status — shown as a neutral
// "Unknown", never a false "Running".
function badgeFor(status?: QueryState): {label: string; tone: StatusTone} {
  switch (status) {
    case 'SUCCEEDED':
      return {label: 'Succeeded', tone: 'success'};
    case 'FAILED':
      return {label: 'Failed', tone: 'danger'};
    case 'CANCELLED':
      return {label: 'Cancelled', tone: 'neutral'};
    default:
      return {label: 'Unknown', tone: 'neutral'};
  }
}

/**
 * One history entry — status badge, relative time (absolute on hover),
 * single-line SQL preview, scanned/duration stats, Open + Re-run actions.
 *
 * The action labels are overridable because the mobile workspace has no editor
 * to open into: there the same row reads View + Run.
 */
export function QueryHistoryRow({
  entry,
  onReopen,
  onRerun,
  rerunDisabled,
  openLabel = 'Open',
  openAriaLabel = 'Open this query in the editor',
  runLabel = 'Re-run',
  runAriaLabel = 'Re-run this query'
}: {
  entry: QueryHistoryEntry;
  onReopen: () => void;
  onRerun: () => void;
  rerunDisabled: boolean;
  openLabel?: string;
  openAriaLabel?: string;
  runLabel?: string;
  runAriaLabel?: string;
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
        <StatusPill tone={badge.tone}>{badge.label}</StatusPill>
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
        {/* The tablet floor is WCAG 2.2 SC 2.5.8's 24 CSS px, written absolutely because it is
            a THRESHOLD rather than a step on the rem-derived spacing scale — at this app's 14px
            root `min-h-6` draws 21px while reading as if it met the minimum, and the padded
            `text-xs` content stops at 23px on its own, so this floor is load-bearing rather
            than decorative. `min-h-11` is the mobile floor and draws 38.5px, short of the 44
            that SC 2.5.5 asks for at AAA. */}
        <button
          type="button"
          onClick={onReopen}
          aria-label={openAriaLabel}
          className="inline-flex min-h-11 items-center rounded-sm px-2 py-1 text-xs font-semibold text-accent-text tablet:min-h-[24px] hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {openLabel}
        </button>
        <button
          type="button"
          onClick={onRerun}
          disabled={rerunDisabled}
          aria-label={runAriaLabel}
          className="inline-flex min-h-11 items-center rounded-sm px-2 py-1 text-xs font-semibold text-accent-text tablet:min-h-[24px] hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {runLabel}
        </button>
      </div>
    </div>
  );
}
