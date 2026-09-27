import {forwardRef, useCallback, useId, useRef} from 'react';
import {cx} from '../lib/cx';
import {FIELD_LABEL} from './fieldStyles';
import {useFieldErrorAnnouncement} from './useFieldErrorAnnouncement';

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  /** When set: shows the message below the input + the invalid ring. */
  error?: string | null;
  /** When set: renders a `<label>` above the input. */
  label?: string;
  /**
   * Speak an error the input already has when it mounts. Off by default, so a blank row says
   * nothing before the user types; on for a field that reopens carrying a failure the user just
   * caused, which would otherwise be heard only as the description of the focused field.
   */
  announceInitialError?: boolean;
};

const BASE =
  'w-full rounded-md border bg-surface px-3 h-9 text-base text-text placeholder:text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:border-accent disabled:opacity-45 transition-colors';

/**
 * Single-line text input with built-in error state and optional label. Forwards a ref and all
 * native `<input>` attributes.
 *
 * The error is the input's description (`aria-invalid` + `aria-describedby`), never an alert: an
 * alert interrupts on every keystroke that changes the message, and for a field the user is not in.
 * It is spoken politely when the field is left, when an action raises it, and on Enter — the rules
 * are `useFieldErrorAnnouncement`'s.
 *
 * @example
 * <Input label="Folder name" value={name} onChange={(e) => setName(e.target.value)} error={nameError} />
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      error,
      label,
      announceInitialError = false,
      id,
      className,
      'aria-describedby': describedBy,
      onChange,
      onFocus,
      onBlur,
      onKeyDown,
      ...rest
    },
    ref
  ) => {
    const hasError = error != null && error !== '';
    const fieldRef = useRef<HTMLInputElement | null>(null);
    const spoken = useFieldErrorAnnouncement(error, fieldRef, {speakInitial: announceInitialError});
    const setRefs = useCallback(
      (node: HTMLInputElement | null) => {
        fieldRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      },
      [ref]
    );
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
          ref={setRefs}
          id={inputId}
          className={cx(
            BASE,
            hasError ? 'border-danger focus-visible:ring-danger' : 'border-border focus-visible:ring-accent',
            className
          )}
          aria-invalid={hasError || undefined}
          aria-describedby={cx(describedBy, hasError ? errorId : undefined) || undefined}
          onChange={(e) => {
            spoken.onChange();
            onChange?.(e);
          }}
          onFocus={(e) => {
            spoken.onFocus();
            onFocus?.(e);
          }}
          onBlur={(e) => {
            spoken.onBlur();
            onBlur?.(e);
          }}
          onKeyDown={(e) => {
            spoken.onKeyDown(e);
            onKeyDown?.(e);
          }}
          {...rest}
        />
        {hasError && (
          <p
            id={errorId}
            className="mt-1.5 text-xs text-danger">
            {error}
          </p>
        )}
        <span
          aria-live="polite"
          aria-atomic="true"
          className="sr-only">
          {spoken.announcement}
        </span>
      </div>
    );
  }
);

Input.displayName = 'Input';
