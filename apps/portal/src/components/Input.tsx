import {forwardRef, useId} from 'react';
import {cx} from '../lib/cx';
import {FIELD_LABEL} from './fieldStyles';

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  /** When set: shows the message below the input + the invalid ring. */
  error?: string | null;
  /** When set: renders a `<label>` above the input. */
  label?: string;
};

const BASE =
  'w-full rounded-md border bg-surface px-3 h-9 text-base text-text placeholder:text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:border-accent disabled:opacity-45 transition-colors';

/**
 * Single-line text input with built-in error state and optional label. The
 * error message is announced (`role="alert"`) and wired to the input via
 * aria-invalid/aria-describedby. Forwards a ref and all native `<input>`
 * attributes.
 *
 * @example
 * <Input label="Folder name" value={name} onChange={(e) => setName(e.target.value)} error={nameError} />
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({error, label, id, className, 'aria-describedby': describedBy, ...rest}, ref) => {
    const hasError = error != null && error !== '';
    // Always have a stable id so the <label> and the error message are
    // programmatically associated even when the caller omits `id` (1.3.1 / 3.3.2).
    const reactId = useId();
    const inputId = id ?? reactId;
    const errorId = `${inputId}-error`;
    return (
      <div>
        {label && (
          <label
            htmlFor={inputId}
            className={FIELD_LABEL}>
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cx(
            BASE,
            hasError ? 'border-danger focus-visible:ring-danger' : 'border-border focus-visible:ring-accent',
            className
          )}
          aria-invalid={hasError || undefined}
          aria-describedby={cx(describedBy, hasError ? errorId : undefined) || undefined}
          {...rest}
        />
        {hasError && (
          <p
            id={errorId}
            role="alert"
            className="mt-1.5 text-xs text-danger">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';
