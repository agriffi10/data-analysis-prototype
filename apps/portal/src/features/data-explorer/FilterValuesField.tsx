import {useId, useRef} from 'react';
import {cx} from '../../lib/cx';
import {FIELD_LABEL} from '../../components/fieldStyles';
import {useFieldErrorAnnouncement} from '../../components/useFieldErrorAnnouncement';
import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import type {ListFieldValue} from './explorationQueryOps';

export type FilterValuesFieldProps = {
  /** The field's visible and accessible name. */
  label: string;
  /** Hides the label visually, keeping it for assistive technology — for a row of fields that are labelled that way. */
  labelHidden?: boolean;
  value: ListFieldValue;
  /** Offer the (empty) box: text columns only, since a number column never holds an empty string. */
  offersEmpty: boolean;
  /** Offer the NULL box: only where the operator can list NULL. */
  offersNull: boolean;
  /** The column the list is for, which the boxes' group names — several rows of them can share a dialog. */
  column: string;
  error?: string | null;
  onChange: (value: ListFieldValue) => void;
  className?: string;
  /**
   * Put in front of the two boxes' names, for a surface showing several of these fields at once —
   * without it every one of them offers a box called "(empty)", which voice control and a list of
   * form controls cannot tell apart.
   */
  boxNamePrefix?: string;
};

/** The group of boxes under the lines, named once so both surfaces and their tests agree; the column follows it. */
export const ALSO_IN_THE_LIST = 'Also in the list for';

/**
 * The one-value-per-line field both list-operator surfaces use, with a box for each value a
 * line cannot hold.
 *
 * Extracted rather than written twice because the value dialog and *Order and filter* must
 * refuse the same lists — they already share the reader, and a second copy of the field is
 * where the labelling and the error wiring would drift apart. It carries `Input`'s
 * accessibility contract over a `<textarea>`: the label is associated by id, and the
 * message is the field's description, spoken by `useFieldErrorAnnouncement`'s rules — except
 * Enter, which is a newline here.
 *
 * The two boxes exist so the field can reopen ANY list without losing part of it. A blank
 * line is ignored, so the empty string is a box; a NULL is not a value a line can spell, so
 * it is a box too. Without them, a list written by the values picker would lose its (empty)
 * and NULL the first time *Order and filter* re-read it.
 *
 * It holds RAW TEXT, never the parsed values. A field that stored what the parser returned
 * would collapse a blank line the user had just opened, and a duplicate they were half way
 * through typing, out from under the cursor.
 */
export function FilterValuesField({
  label,
  labelHidden,
  value,
  offersEmpty,
  offersNull,
  column,
  error,
  onChange,
  className,
  boxNamePrefix
}: FilterValuesFieldProps) {
  const boxName = (shown: string) => (boxNamePrefix ? `${boxNamePrefix}: ${shown}` : undefined);
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
        value={value.text}
        onChange={(e) => {
          spoken.onChange();
          onChange({...value, text: e.target.value});
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
      {(offersEmpty || offersNull) && (
        <fieldset className="mt-2 flex flex-wrap items-center gap-x-4">
          <legend className="float-left mr-3 text-xs text-text-2">{`${ALSO_IN_THE_LIST} ${column}`}</legend>
          {offersEmpty && (
            <label className="flex min-h-[24px] items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={value.empty}
                aria-label={boxName(EMPTY_DISPLAY)}
                onChange={() => onChange({...value, empty: !value.empty})}
              />
              <span className="italic text-text-3">{EMPTY_DISPLAY}</span>
            </label>
          )}
          {offersNull && (
            <label className="flex min-h-[24px] items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={value.includesNull}
                aria-label={boxName(NULL_DISPLAY)}
                onChange={() => onChange({...value, includesNull: !value.includesNull})}
              />
              <span className="italic text-text-3">{NULL_DISPLAY}</span>
            </label>
          )}
        </fieldset>
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
