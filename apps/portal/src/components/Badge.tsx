import {cx} from '../lib/cx';

/**
 * Neutral pill label, e.g. file/folder type badges in the file table.
 *
 * Forwards all native `<span>` attributes; `className` is appended so callers
 * can extend the styling.
 *
 * @example
 * <Badge>CSV</Badge>
 */
export function Badge({className, ...rest}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-full bg-surface-2 border border-border px-2 py-0.5 text-xs font-medium text-text-2',
        className
      )}
      {...rest}
    />
  );
}
