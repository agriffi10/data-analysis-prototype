import { forwardRef } from 'react';
import { cx } from '../lib/cx';

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  error?: string | null; // when set: shows the message + invalid ring
  label?: string; // when set: renders a <label> above the input
};

const BASE =
  'w-full rounded-md border bg-surface px-3 h-9 text-base text-text placeholder:text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:border-accent disabled:opacity-45 transition-colors';

// Single-line text input (SPEC-028) with built-in error state and optional
// label. Forwards a ref and all native <input> attributes.
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ error, label, id, className, 'aria-describedby': describedBy, ...rest }, ref) => {
    const hasError = error != null && error !== '';
    const errorId = id ? `${id}-error` : undefined;
    return (
      <div>
        {label && (
          <label
            htmlFor={id}
            className="mb-1.5 block text-sm font-medium text-text"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={id}
          className={cx(
            BASE,
            hasError
              ? 'border-danger focus-visible:ring-danger/40'
              : 'border-border focus-visible:ring-accent/40',
            className,
          )}
          aria-invalid={hasError || undefined}
          aria-describedby={cx(describedBy, hasError ? errorId : undefined) || undefined}
          {...rest}
        />
        {hasError && (
          <p id={errorId} role="alert" className="mt-1.5 text-xs text-danger">
            {error}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
