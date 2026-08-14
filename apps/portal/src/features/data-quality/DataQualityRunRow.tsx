import {Link} from 'react-router';
import {Badge} from '../../components/Badge';
import {StatusPill} from '../../components/StatusPill';
import {formatRelativeTime} from '../../lib/format';
import {cx} from '../../lib/cx';
import {splitLocation} from './dataQuality.format';
import type {DataQualityRunSummary} from './dataQuality.types';

/**
 * One completed check, as a self-contained card linking to its full report.
 *
 * THE WHOLE ROW IS THE LINK, and its accessible name names the location — never "view" or
 * "here". A screen-reader user tabbing the list hears where each link goes without having
 * to read the surrounding row.
 */
export function DataQualityRunRow({run}: {run: DataQualityRunSummary}) {
  const {space, requestId, location, verdict, fileCount, hasApproximateFigures, timestamp} = run;
  const {parent, name} = splitLocation(location);
  const clean = verdict === 'clean';

  return (
    <li>
      <Link
        to={`/data-quality/${space}/${requestId}`}
        aria-label={`Data quality check on ${location} — ${clean ? 'clean' : 'issues found'}`}
        className={cx(
          'flex items-start gap-3 rounded-md border border-border bg-surface p-4',
          'hover:border-accent-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'
        )}>
        <div className="min-w-0 flex-1">
          {/* SPLIT, NOT `dir="rtl"`. What identifies a check is the END of its location, so
              a long path must lose its head rather than its tail. The usual CSS-only trick
              for that is `direction: rtl` — but these are S3 keys, and under bidi a leading
              or trailing "/" is neutral punctuation that gets re-ordered to the wrong end,
              rendering `alice/sales/` as `/alice/sales`. Truncating the parent in its own
              span while the final segment refuses to shrink gets the same result with no
              bidi involved, and leaves the text in reading order for a screen reader. */}
          <p className="flex min-w-0 items-baseline font-mono text-sm">
            <span className="truncate text-text-3">{parent}</span>
            <span className="flex-none text-text">{name}</span>
          </p>
          {/* Metadata wraps to its own line on mobile; one tree, responsive utilities. */}
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-3">
            <span>{space}</span>
            <span aria-hidden="true">·</span>
            <span>{formatRelativeTime(timestamp)}</span>
            <span aria-hidden="true">·</span>
            <span>
              {fileCount} {fileCount === 1 ? 'file' : 'files'}
            </span>
          </p>
        </div>

        <div className="flex flex-none flex-col items-end gap-1">
          <VerdictChip clean={clean} />
          {/* THE SAMPLED CHIP IS NOT DECORATION. The list is where a user forms a quick
              impression, so a run whose figures are estimates must never read as an
              unqualified "Clean" here any more than it may in the report or the
              notification (SPEC-112/114, same rule applied at list level). */}
          {hasApproximateFigures && <Badge>Sampled</Badge>}
        </div>
      </Link>
    </li>
  );
}

/** Dot PLUS text label — never colour-only (`StatusPill`'s whole reason for existing). */
function VerdictChip({clean}: {clean: boolean}) {
  return <StatusPill tone={clean ? 'success' : 'warning'}>{clean ? 'Clean' : 'Issues found'}</StatusPill>;
}
