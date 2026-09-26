import {Link} from 'react-router';
import {Badge} from '../../components/Badge';
import {StatusPill} from '../../components/StatusPill';
import {formatRelativeTime} from '../../lib/format';
import {cx} from '../../lib/cx';
import {reportPath, splitLocation} from './dataQuality.format';
import type {DataQualityRunSummary} from './dataQuality.types';

/**
 * One completed check, as a self-contained card linking to its full report.
 *
 * THE WHOLE ROW IS THE LINK, and its accessible name names the location — never "view" or
 * "here". A screen-reader user tabbing the list hears where each link goes without having
 * to read the surrounding row. The name carries everything the card shows: the label replaces
 * the content, so a figure left out of it is one a screen reader never hears — the Partly
 * checked qualifier above all, and the time and file count that tell two checks of one folder apart.
 */
export function DataQualityRunRow({run}: {run: DataQualityRunSummary}) {
  const {space, requestId, location, verdict, fileCount, hasIncompleteFigures, timestamp} = run;
  const {parent, name} = splitLocation(location);
  const clean = verdict === 'clean';
  const when = formatRelativeTime(timestamp);
  const files = `${fileCount} ${fileCount === 1 ? 'file' : 'files'}`;
  const outcome = `${clean ? 'clean' : 'issues found'}${hasIncompleteFigures ? ', partly checked' : ''}`;

  return (
    <li>
      <Link
        to={reportPath(space, requestId)}
        aria-label={`Data quality check on ${location} in ${space}, ${when}, ${files} — ${outcome}`}
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
            <span>{when}</span>
            <span aria-hidden="true">·</span>
            <span>{files}</span>
          </p>
        </div>

        <div className="flex flex-none flex-col items-end gap-1">
          <VerdictChip clean={clean} />
          {/* THE PARTLY CHECKED TAG IS NOT DECORATION. The list is where a user forms a
              quick impression, so a run where a check was skipped, failed or only sampled
              must never read as an unqualified "Clean" here, just as the report banner
              warns on the same flag. It keys off the incomplete flag, not the approximate
              one: that is true on every report, so a tag keyed to it said nothing. The
              link's aria-label replaces this text for a screen reader, so it says it too. */}
          {hasIncompleteFigures && <Badge>Partly checked</Badge>}
        </div>
      </Link>
    </li>
  );
}

/** Dot PLUS text label — never colour-only (`StatusPill`'s whole reason for existing). */
function VerdictChip({clean}: {clean: boolean}) {
  return <StatusPill tone={clean ? 'success' : 'warning'}>{clean ? 'Clean' : 'Issues found'}</StatusPill>;
}
