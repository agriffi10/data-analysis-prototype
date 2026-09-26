import {formatBytes} from '../../lib/format';

export type CostIndicatorProps = {
  /** Bytes the current execution scanned, or null before one has reported. */
  bytesScanned: number | null;
  /**
   * Whether the current statement resolved to an execution already run — by this tab, or by
   * another open tab showing the same description (the cache is shared; the ledgers are not).
   */
  cacheHit: 'none' | 'this-tab' | 'another-tab';
  /** Bytes scanned across every distinct execution this tab has run. */
  totalBytes: number;
};

export const CACHE_HIT_TEXT = 'Loaded from an earlier run in this tab — nothing more scanned';
export const CACHE_HIT_ELSEWHERE_TEXT = 'Loaded from an earlier run in another tab — nothing more scanned';

/**
 * What the last apply cost, and what this tab has cost.
 *
 * Reported after the fact, always: Athena will not say what a query will scan before it
 * runs it, so there is no pre-flight estimate to warn on and no honest "this looks
 * expensive" confirm to build. The guards are the workgroup's per-query cutoff and this.
 *
 * A cache hit **says so** rather than repeating the figure the execution originally
 * scanned — the number would be true and the sentence would not, since this gesture
 * scanned nothing. That includes an execution another open tab ran: two tabs showing one
 * description share one execution. The total behind it is unaffected either way: it is
 * summed from a map keyed by execution id, so re-resolving to a known execution cannot add
 * to it, and one another tab already paid for is recorded here as nothing.
 */
export function CostIndicator({bytesScanned, cacheHit, totalBytes}: CostIndicatorProps) {
  const applied =
    cacheHit === 'this-tab'
      ? CACHE_HIT_TEXT
      : cacheHit === 'another-tab'
        ? CACHE_HIT_ELSEWHERE_TEXT
        : `This query scanned ${formatBytes(bytesScanned ?? 0)}`;
  return (
    // Not a live region: this is a standing figure that changes after every apply, and a
    // polite announcement of it would talk over the results the user is reading.
    <p className="flex-none border-t border-border px-3 py-1.5 text-xs text-text-3">
      {bytesScanned === null
        ? `${formatBytes(totalBytes)} scanned by this exploration`
        : `${applied} · ${formatBytes(totalBytes)} scanned by this exploration`}
    </p>
  );
}
