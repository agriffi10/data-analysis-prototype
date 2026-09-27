import {useId, useRef} from 'react';
import {cx} from '../../lib/cx';
import {FIELD_LABEL} from '../../components/fieldStyles';
import {useFieldErrorAnnouncement} from '../../components/useFieldErrorAnnouncement';

export type FilterValuesFieldProps = {
  /** The field's visible and accessible name. */
  label: string;
  /** Hides the label visually, keeping it for assistive technology — for a row of fields that are labelled that way. */
  labelHidden?: boolean;
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
 * message is the field's description, spoken by `useFieldErrorAnnouncement`'s rules — except
 * Enter, which is a newline here.
 *
 * It holds RAW TEXT, never the parsed values. A field that stored what the parser returned
 * would collapse a blank line the user had just opened, and a duplicate they were half way
 * through typing, out from under the cursor.
 */
export function FilterValuesField({label, labelHidden, value, error, onChange, className}: FilterValuesFieldProps) {
  const fieldId = useId();
  const errorId = `${fieldId}-error`;
  const hasError = error != null && error !== '';
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const spoken = useFieldErrorAnnouncement(error, fieldRef);
  return (
    <div className={className}>
      <label
        htmlFor={fieldId}
        className={labelHidden ? 'sr-only' : FIELD_LABEL}>
        {label}
      </label>
      <textarea
        ref={fieldRef}
        id={fieldId}
        rows={6}
        value={value}
        onChange={(e) => {
          spoken.onChange();
          onChange(e.target.value);
        }}
        onFocus={spoken.onFocus}
        onBlur={spoken.onBlur}
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
