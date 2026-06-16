import { cx } from '../lib/cx';

// Neutral type pill (SPEC-028) — file/folder type labels in the file table.
export function Badge({
  className,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-full bg-surface-2 border border-border px-2 py-0.5 text-xs font-medium text-text-2',
        className,
      )}
      {...rest}
    />
  );
}
