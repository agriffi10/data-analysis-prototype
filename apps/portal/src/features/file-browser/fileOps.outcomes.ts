import {lastSegment} from './fileBrowser.paths';
import type {FileOpItemResult, FileOpOutcome} from './fileOps.types';
import type {NotificationPayload} from '../notifications';

/**
 * How each outcome reads as the heading of a group.
 *
 * The plane's own `focommon.messages` words the notification; this words a LIST, which is a
 * different job — a heading over three items cannot be a sentence about one. Neither invents an
 * outcome: the vocabulary is the plane's.
 */
const OUTCOME_HEADINGS: Record<FileOpOutcome, string> = {
  cleared: 'Ready to go',
  conflict: 'Something is already in the way',
  noop: 'Nothing to do',
  source_missing: 'No longer there',
  source_empty: 'Empty',
  protected: 'Protected — the portal manages these',
  copy_failed: 'The copy did not finish',
  delete_failed: 'Could not be removed',
  duplicate: 'Copied, but the original is still there',
  refused: 'Refused',
  moved: 'Moved',
  copied: 'Copied',
  deleted: 'Deleted'
};

/**
 * Is this outcome one the user has nothing to do about?
 *
 * The three that landed are a success; everything else is neither a success nor an error. A
 * `noop` did no harm and a `duplicate` put the data where it was asked to — calling either a
 * failure was the specific thing that made the old success/error binary wrong here.
 */
const LANDED: ReadonlySet<FileOpOutcome> = new Set<FileOpOutcome>(['moved', 'copied', 'deleted']);

/**
 * The heading for one outcome group.
 *
 * @param outcome - The outcome.
 * @returns The heading.
 */
export function outcomeHeading(outcome: FileOpOutcome): string {
  return OUTCOME_HEADINGS[outcome];
}

/**
 * Did everything in this list land?
 *
 * @param results - The per-item results.
 * @returns True when every one of them is a success outcome.
 */
export function allLanded(results: readonly FileOpItemResult[]): boolean {
  return results.every((result) => LANDED.has(result.outcome));
}

/**
 * The conflicted items a notification named, as a surface renders them.
 *
 * **`conflict` is the only outcome this can produce, and that is a property of the wire rather
 * than of this function.** The producer's payload carries the conflicted items and nothing else
 * per item — it is capped at 1 KiB, and one conflicted item costs a couple of hundred bytes at
 * ordinary key lengths and thousands at the plane's own caps. A full outcome list is not
 * something that channel can carry, so the notification's MESSAGE is where the rest of a run's
 * outcomes are told, and this is what a re-submit can be built from.
 *
 * @param payload - The producer's structured field.
 * @returns One result per conflicted item, in the order the producer named them.
 */
export function itemResultsFromPayload(payload: NotificationPayload | undefined): FileOpItemResult[] {
  return (payload?.conflicts ?? []).map((conflict) => ({
    itemKey: conflict.itemKey,
    // The leaf, never the whole key: the user picked these by name, and a column of absolute
    // prefixes is unreadable. `targetName` wins where there is one — for a rename that is the
    // only name the user ever typed.
    label: conflict.targetName ?? lastSegment(conflict.itemKey),
    outcome: 'conflict',
    sample: conflict.sample,
    more: conflict.more
  }));
}
