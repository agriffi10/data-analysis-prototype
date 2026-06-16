import { forwardRef } from 'react';
import { cx } from '../lib/cx';

type IconButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: 'sm' | 'md';
  label: string; // required — applied as aria-label (the icon child is decorative)
};

const BASE =
  'inline-flex items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text disabled:opacity-45 disabled:cursor-not-allowed transition-colors';

const SIZES = { sm: 'h-7 w-7', md: 'h-8 w-8' } as const;

// Ghost icon-only button (SPEC-028) — close buttons, row actions. `label`
// becomes the accessible name.
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ size = 'md', label, className, type, ...rest }, ref) => (
    <button
      ref={ref}
      type={type ?? 'button'}
      aria-label={label}
      className={cx(BASE, SIZES[size], className)}
      {...rest}
    />
  ),
);

IconButton.displayName = 'IconButton';
