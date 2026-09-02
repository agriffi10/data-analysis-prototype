import {Banner} from '../../components/Banner';
import {toUserText} from '../../lib/errorMessages';
import {allLanded, outcomeHeading} from './fileOps.outcomes';
import type {FileOpItemResult, FileOpOutcome} from './fileOps.types';

/** `code` is the stable app/AWS code; the banner maps it to friendly text. */
export type OperationError = {label: string; message?: string; code?: string};

type Props = {
  count: number; // how many items succeeded
  pastVerb: string; // "Deleted" / "Moved" / "Copied"
  failVerb: string; // "delete" / "move" / "copy"
  errors: OperationError[];
  onDismiss: () => void;
};

/**
 * Result banner for a bulk delete/move/copy — success count
 * plus any per-item failures. Shared shell extracted from the three near-identical
 * FileBrowser banners (react-best-practices abstraction pass).
 */
export function OperationSummaryBanner({count, pastVerb, failVerb, errors, onDismiss}: Props) {
  return (
    <Banner
      variant={errors.length === 0 ? 'success' : 'warning'}
      // Clean result is a polite status; a partial failure is an error-class
      // message and should assert (WCAG 4.1.3).
      role={errors.length === 0 ? 'status' : 'alert'}
      onDismiss={onDismiss}
      className="mb-4"
      title={`${pastVerb} ${count} ${count === 1 ? 'item' : 'items'}.`}>
      {errors.length > 0 && (
        <>
          <p className="mt-1">
            Could not {failVerb} {errors.length}:
          </p>
          <ul className="mt-1 list-disc pl-5">
            {errors.map((e, i) => (
              <li key={`${e.label}-${i}`}>
                {e.label} — {toUserText({code: e.code, message: e.message})}
              </li>
            ))}
          </ul>
        </>
      )}
    </Banner>
  );
}

type OutcomeProps = {
  /** The heading. Never a completion claim for work that is still running. */
  title: string;
  results: FileOpItemResult[];
  onDismiss?: () => void;
  className?: string;
};

/**
 * The same banner over a plane's PER-ITEM OUTCOMES, grouped by what happened to each item.
 *
 * **`{count, errors}` cannot express what this plane reports and this is not a cosmetic
 * difference.** That shape chooses success or warning on `errors.length === 0` and titles itself
 * `${pastVerb} ${count} items.` — a binary, and a completion claim. A run here can come back as
 * three moved, one `noop`, one `protected` and one `conflict`: a `noop` is neither a success nor
 * an error, and the title would be asserting an outcome for items that did not get one.
 *
 * **The neutral variant is the default**, because a mixed run is exactly what this renders. It
 * turns success only when every item landed.
 *
 * **What feeds it today is one outcome, and that is the wire's doing.** The plane's notification
 * payload is capped at 1 KiB and carries the conflicted items alone; the run's other outcomes are
 * told in the message beside it. The grouping is written over the whole vocabulary anyway — the
 * alternative is a conflict-shaped surface that has to be rewritten the day the channel widens,
 * and the grouping is what makes a bounded sample legible in the meantime.
 */
export function OperationOutcomeBanner({title, results, onDismiss, className = 'mb-4'}: OutcomeProps) {
  const groups = new Map<FileOpOutcome, FileOpItemResult[]>();
  for (const result of results) {
    const group = groups.get(result.outcome);
    if (group) group.push(result);
    else groups.set(result.outcome, [result]);
  }

  return (
    <Banner
      variant={results.length > 0 && allLanded(results) ? 'success' : 'info'}
      role="status"
      onDismiss={onDismiss}
      className={className}
      title={title}>
      {[...groups.entries()].map(([outcome, items]) => (
        <div
          key={outcome}
          className="mt-2">
          <p className="text-sm font-semibold">
            {outcomeHeading(outcome)} ({items.length})
          </p>
          <ul className="mt-1 list-disc pl-5 text-sm">
            {items.map((item) => (
              <li key={item.itemKey}>
                {item.label}
                {item.sample && item.sample.length > 0 && (
                  <>
                    {' — '}
                    {item.sample.join(', ')}
                    {/* BOUNDED at the producer, by bytes as well as count, so a list that was cut
                        must never read as the whole of it. */}
                    {item.more && <span className="text-text-3"> and more</span>}
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Banner>
  );
}
