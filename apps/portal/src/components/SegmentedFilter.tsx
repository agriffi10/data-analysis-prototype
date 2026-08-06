import {cx} from '../lib/cx';

type SegmentedFilterProps<T extends string> = {
  /** Names the group for screen readers, e.g. "Filter notifications". */
  label: string;
  options: readonly {value: T; label: string}[];
  value: T;
  onChange: (next: T) => void;
};

/**
 * A small segmented control: one `role="group"` of toggle buttons where the chosen
 * one carries `aria-pressed`, so the choice is never conveyed by styling alone.
 *
 * Generic over its options because the two pages that had written this out differ only
 * in their list — All/Unread and All/Clean/Issues — and one of them had to `capitalize`
 * its raw values in CSS to make them read as labels. Labels are given, not derived.
 *
 * @example
 * <SegmentedFilter
 *   label="Filter notifications"
 *   options={[{value: 'all', label: 'All'}, {value: 'unread', label: 'Unread'}]}
 *   value={filter}
 *   onChange={applyFilter}
 * />
 */
export function SegmentedFilter<T extends string>({label, options, value, onChange}: SegmentedFilterProps<T>) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex gap-0.5 rounded-md border border-border bg-surface-2 p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cx(
              'h-7 rounded-sm px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
              active ? 'bg-surface font-semibold text-accent-text shadow-sm' : 'text-text-2 hover:text-text'
            )}>
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
