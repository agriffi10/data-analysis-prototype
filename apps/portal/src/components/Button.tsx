import {forwardRef} from 'react';
import {cx} from '../lib/cx';

export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger' | 'dangerOutline';
export type ButtonSize = 'sm' | 'md' | 'lg';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /**
   * Unavailable, and SAYING WHY. Renders `aria-disabled` rather than
   * `disabled`, so the control keeps its place in the tab order and the reason is reachable —
   * a `disabled` button is skipped entirely, which is how "it's greyed out and I can't find out
   * why" happens. The click is swallowed here, so a caller cannot forget to guard its handler.
   *
   * The reason rides as `title`, which becomes the accessible DESCRIPTION. Deliberately not
   * rendered inside the button: text in the content becomes part of the accessible NAME, and
   * every registry row and test queries these controls by name.
   *
   * `disabled` still wins where it belongs — an in-flight operation is not a refusal, and
   * nothing is gained by leaving a busy control focusable.
   */
  disabledReason?: string;
};

const BASE =
  'rounded-md font-medium inline-flex items-center justify-center gap-2 whitespace-nowrap disabled:opacity-45 disabled:cursor-not-allowed transition-colors';

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover',
  default: 'bg-surface border border-border text-text hover:bg-surface-2',
  ghost: 'text-text-2 hover:bg-surface-2 hover:text-text',
  // `on-danger`, not white: `danger` has to be light enough to read as text on a dark surface,
  // which leaves it too light to carry white as a fill. The two roles part company in the dark
  // theme, and this is the token that names the second one.
  danger: 'bg-danger text-on-danger hover:bg-danger/90',
  // The control that OPENS a destructive confirmation: red enough to read as one before it is
  // clicked, and quieter than the solid `danger` of the confirm button it leads to.
  dangerOutline: 'border border-danger text-danger hover:bg-danger-soft'
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-9 px-4 text-base',
  lg: 'h-[46px] px-6 text-md'
};

/**
 * Design-system button. Forwards all native `<button>` attributes and a ref;
 * defaults `type` to "button" so it never submits a form by accident.
 * `className` is appended last so callers can extend or override the
 * generated classes.
 *
 * @example
 * <Button variant="danger" size="sm" onClick={handleDelete}>Delete</Button>
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({variant = 'default', size = 'md', className, type, disabledReason, onClick, title, ...rest}, ref) => (
    <button
      ref={ref}
      {...rest}
      type={type ?? 'button'}
      className={cx(BASE, VARIANTS[variant], SIZES[size], disabledReason && 'opacity-45 cursor-not-allowed', className)}
      aria-disabled={disabledReason ? true : undefined}
      title={disabledReason ?? title}
      onClick={disabledReason ? undefined : onClick}
    />
  )
);

Button.displayName = 'Button';
