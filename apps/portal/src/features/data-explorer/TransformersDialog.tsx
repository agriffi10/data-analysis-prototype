import {useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {
  BINARY_TRANSFORMER_DEFAULT_MAX_LENGTH,
  BINARY_TRANSFORMER_MAX_LENGTH,
  NUMERIC_TRANSFORMER_MAX_PRECISION,
  SELECT_CLASS
} from './dataExplorer.constants';
import {templateRefusal, URL_PLACEHOLDER} from './urlTransformer';
import type {Transformer} from './dataExplorer.types';

export type TransformersDialogProps = {
  /** Every column the current result has, in display order. */
  columns: string[];
  /** The applied transformers, keyed by column name. */
  transformers: Record<string, Transformer>;
  onApply: (transformers: Record<string, Transformer>) => void;
  onCancel: () => void;
};

export const TRANSFORMERS_RAW_NOTE =
  'These change how a value is shown. Filters, colors, Calc and copy all still use the value itself.';
export const PRECISION_REFUSAL = `Decimal places must be a whole number from 0 to ${NUMERIC_TRANSFORMER_MAX_PRECISION}.`;
export const MAX_LENGTH_REFUSAL = `Length must be a whole number from 1 to ${BINARY_TRANSFORMER_MAX_LENGTH}.`;

const NONE = '';

/** What each kind is called, in the one order the picker offers them. */
const KIND_LABELS: {value: Transformer['kind'] | ''; label: string}[] = [
  {value: NONE, label: 'As it is'},
  {value: 'numeric', label: 'Number'},
  {value: 'binary', label: 'Encoded'},
  {value: 'url', label: 'Link'}
];

/** A transformer as a newly-chosen one starts. */
function defaultOf(kind: Transformer['kind']): Transformer {
  if (kind === 'numeric') return {kind: 'numeric', precision: 2, lenient: true};
  if (kind === 'binary') {
    return {kind: 'binary', encoding: 'hex', maxLength: BINARY_TRANSFORMER_DEFAULT_MAX_LENGTH};
  }
  return {kind: 'url', template: `https://example.com/${URL_PLACEHOLDER}`};
}

/**
 * How each column's values are rendered.
 *
 * One row per column, so several are set in one Apply and any one is cleared on its own.
 * Staged like the colours dialog beside it: a link template is half-invalid for most of the
 * time it is being typed, and applying each keystroke would flicker every row in the column
 * between a link and a refusal.
 *
 * **The note at the top is a promise the code keeps structurally**: `transformCell` is
 * called at the cell and nowhere upstream, so a filter, a colour rule, Calc and copy all
 * read the raw row. A transformed value leaking into any of them is a wrong answer nobody
 * can see is wrong.
 */
export function TransformersDialog({columns, transformers, onApply, onCancel}: TransformersDialogProps) {
  const [draft, setDraft] = useState<Record<string, Transformer>>(transformers);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = (column: string, transformer: Transformer | null) => {
    setErrors((e) => ({...e, [column]: ''}));
    setDraft((d) => {
      // A computed key in an object literal DEFINES a property; `next[column] = …` would
      // invoke the inherited setter for a column named `__proto__` and set the object's
      // prototype instead, silently storing nothing.
      if (transformer) return {...d, [column]: transformer};
      const next = {...d};
      delete next[column];
      return next;
    });
  };

  const submit = () => {
    const bad: Record<string, string> = {};
    for (const [column, transformer] of Object.entries(draft)) {
      if (transformer.kind === 'url') {
        // Refused HERE, where a template with no placeholder is a mistake the user can
        // still see. Left to the cell it would render the same static link on every row.
        const refusal = templateRefusal(transformer.template);
        if (refusal) bad[column] = refusal;
      }
      if (transformer.kind === 'numeric') {
        const {precision} = transformer;
        if (!Number.isInteger(precision) || precision < 0 || precision > NUMERIC_TRANSFORMER_MAX_PRECISION) {
          bad[column] = PRECISION_REFUSAL;
        }
      }
      if (transformer.kind === 'binary') {
        const {maxLength} = transformer;
        if (!Number.isInteger(maxLength) || maxLength < 1 || maxLength > BINARY_TRANSFORMER_MAX_LENGTH) {
          bad[column] = MAX_LENGTH_REFUSAL;
        }
      }
    }
    if (Object.keys(bad).length > 0) {
      setErrors(bad);
      return;
    }
    onApply(draft);
  };

  return (
    <FormDialog
      title="Transformers"
      ariaLabel="Transformers"
      submitLabel="Apply"
      className="max-w-3xl"
      scrollBody
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">{TRANSFORMERS_RAW_NOTE}</p>

      <ul className="mt-4 flex flex-col gap-2">
        {columns.map((column) => {
          const transformer = draft[column];
          return (
            <li
              key={column}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2">
              <span className="min-w-0 flex-1 basis-40 truncate text-sm text-text">{column}</span>

              <select
                aria-label={`Show ${column} as`}
                className={SELECT_CLASS}
                value={transformer?.kind ?? NONE}
                onChange={(e) =>
                  set(column, e.target.value === NONE ? null : defaultOf(e.target.value as Transformer['kind']))
                }>
                {KIND_LABELS.map(({value, label}) => (
                  <option
                    key={label}
                    value={value}>
                    {label}
                  </option>
                ))}
              </select>

              {transformer?.kind === 'numeric' && (
                <>
                  <span className="basis-32">
                    <Input
                      aria-label={`Decimal places for ${column}`}
                      inputMode="numeric"
                      value={Number.isFinite(transformer.precision) ? String(transformer.precision) : ''}
                      error={errors[column] || null}
                      onChange={(e) => set(column, {...transformer, precision: Number(e.target.value)})}
                    />
                  </span>
                  <label className="flex items-center gap-1.5 text-xs text-text-2">
                    <input
                      type="checkbox"
                      aria-label={`Leave non-numbers alone in ${column}`}
                      checked={transformer.lenient}
                      onChange={(e) => set(column, {...transformer, lenient: e.target.checked})}
                    />
                    Leave non-numbers alone
                  </label>
                </>
              )}

              {transformer?.kind === 'binary' && (
                <>
                  <select
                    aria-label={`Encoding for ${column}`}
                    className={SELECT_CLASS}
                    value={transformer.encoding}
                    onChange={(e) => set(column, {...transformer, encoding: e.target.value as 'hex' | 'base64'})}>
                    <option value="hex">Hex</option>
                    <option value="base64">Base64</option>
                  </select>
                  <span className="basis-32">
                    <Input
                      aria-label={`Longest rendering for ${column}`}
                      inputMode="numeric"
                      value={Number.isFinite(transformer.maxLength) ? String(transformer.maxLength) : ''}
                      error={errors[column] || null}
                      onChange={(e) => set(column, {...transformer, maxLength: Number(e.target.value)})}
                    />
                  </span>
                </>
              )}

              {transformer?.kind === 'url' && (
                <span className="basis-full">
                  <Input
                    aria-label={`Link for ${column}`}
                    value={transformer.template}
                    error={errors[column] || null}
                    onChange={(e) => set(column, {...transformer, template: e.target.value})}
                  />
                  <p className="mt-1 text-xs text-text-3">
                    {`Use ${URL_PLACEHOLDER} where the cell’s value goes. Only https links open.`}
                  </p>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </FormDialog>
  );
}
