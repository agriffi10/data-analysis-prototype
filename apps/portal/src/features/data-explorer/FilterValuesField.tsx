import {forwardRef, useId} from 'react';
import {cx} from '../../lib/cx';
import {FIELD_LABEL} from '../../components/fieldStyles';

export type FilterValuesFieldProps = {
  /** The field's visible and accessible name. */
  label: string;
  value: string;
  error?: string | null;
  onChange: (value: string) => void;
  className?: string;
};

/**
 * The one-value-per-line field both list-operator surfaces use.
 *
 * Extracted rather than written twice because the value dialog and *Order and filter* must
 * refuse the same lists — they already share the parser, and a second copy of the field is
 * where the labelling and the error wiring would drift apart. It carries `Input`'s
 * accessibility contract over a `<textarea>`: the label is associated by id, and the
 * message is announced and pointed at by `aria-describedby`.
 *
 * It holds RAW TEXT, never the parsed values. A field that stored what the parser returned
 * would collapse a blank line the user had just opened, and a duplicate they were half way
 * through typing, out from under the cursor.
 */
export const FilterValuesField = forwardRef<HTMLTextAreaElement, FilterValuesFieldProps>(
  ({label, value, error, onChange, className}, ref) => {
    const fieldId = useId();
    const errorId = `${fieldId}-error`;
    const hasError = error != null && error !== '';
    return (
      <div className={className}>
        <label
          htmlFor={fieldId}
          className={FIELD_LABEL}>
          {label}
        </label>
        <textarea
          ref={ref}
          id={fieldId}
          rows={6}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cx(
            'w-full rounded-md border bg-surface px-3 py-2 font-mono text-sm text-text',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:border-accent transition-colors',
            hasError ? 'border-danger focus-visible:ring-danger' : 'border-border focus-visible:ring-accent'
          )}
          aria-invalid={hasError || undefined}
          aria-describedby={hasError ? errorId : undefined}
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

FilterValuesField.displayName = 'FilterValuesField';
