import { forwardRef } from 'react';
import { cx } from '../lib/cx';

export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const BASE =
  'rounded-md font-medium inline-flex items-center justify-center gap-2 disabled:opacity-45 disabled:cursor-not-allowed transition-colors';

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover',
  default: 'bg-surface border border-border text-text hover:bg-surface-2',
  ghost: 'text-text-2 hover:bg-surface-2 hover:text-text',
  danger: 'bg-danger text-white hover:bg-danger/90',
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-9 px-4 text-base',
  lg: 'h-[46px] px-6 text-md',
};

// Design-system button (SPEC-028). Accepts a variant + size and forwards all
// native <button> attributes and a ref. `className` is appended last so callers
// can extend or override the generated classes.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'default', size = 'md', className, type, ...rest }, ref) => (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={cx(BASE, VARIANTS[variant], SIZES[size], className)}
      {...rest}
    />
  ),
);

Button.displayName = 'Button';
