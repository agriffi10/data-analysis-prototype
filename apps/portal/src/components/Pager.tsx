import type {ReactNode} from 'react';
import {cx} from '../lib/cx';

type PagerProps = {
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  /** The range/page indicator content (incl. any sr-only text), e.g. "1–7 of 23". */
  label: ReactNode;
  /** When the next page is loading, disable Next and show "Loading…". */
  nextBusy?: boolean;
  /** Container layout (padding/border) — varies per host. */
  className?: string;
};

const pagerButton =
  'h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';

/**
 * Prev/Next pager: Prev — range indicator — Next, with consistent
 * ghost-button styling and disabled states. The indicator is an
 * `aria-live="polite"` region so page changes are announced.
 *
 * @example
 * <Pager hasPrev={page > 0} hasNext={hasMore} onPrev={prev} onNext={next} label="1–7 of 23" />
 */
export function Pager({hasPrev, hasNext, onPrev, onNext, label, nextBusy = false, className}: PagerProps) {
  return (
    <div className={cx('flex items-center justify-between gap-3', className)}>
      <button
        type="button"
        onClick={onPrev}
        disabled={!hasPrev}
        className={pagerButton}>
        Prev
      </button>
      <span
        className="text-sm text-text-2"
        aria-live="polite">
        {label}
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={!hasNext || nextBusy}
        className={pagerButton}>
        {nextBusy ? 'Loading…' : 'Next'}
      </button>
    </div>
  );
}
