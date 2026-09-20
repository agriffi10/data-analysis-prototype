import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {FilterValuesField} from './FilterValuesField';
import {
  EMPTY_TEXT_REFUSAL,
  FILTER_OPERATOR_LABELS,
  filterValuesText,
  operatorTakesValues,
  operatorUsesValueKind,
  parseFilterValues
} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import type {ColumnFilter, FilterOperator, FilterValueKind} from './dataExplorer.types';

/** What the dialog hands back: one value for a comparison or a text operator, a list for the other two. */
export type FilterValueResult = {value: string} | {values: string[]};

export type FilterValueDialogProps = {
  column: string;
  operator: FilterOperator;
  /** How the value will be rendered — decides whether a number is required. */
  valueKind: FilterValueKind;
  /** The filter already on this column, so re-filtering it is an edit rather than a retype. */
  existing?: ColumnFilter | null;
  onApply: (result: FilterValueResult) => void;
  onCancel: () => void;
};

export const NUMERIC_VALUE_REFUSAL = 'Enter a number — this column holds numbers, not text.';

/** The multi-line field's label, so the dialog and its tests name it once. */
export const VALUES_FIELD_LABEL = 'Values, one per line';

/**
 * Asks for the value, or the list of values, a filter matches by.
 *
 * The value never reaches the SQL unescaped: it is carried on a `ColumnFilter` and quoted
 * by `sqlLiteral` at render time. What this dialog owns instead is the ONE case the
 * renderer cannot escape its way out of — a numeric column, whose value is emitted bare —
 * and it refuses that here, at the input, using the renderer's own predicate. The
 * alternative is an `ExplorationRenderError`, whose message names a column and an operator
 * and is operator text the error-wording rule forbids showing anyone.
 *
 * The numeric refusal follows the OPERATOR, not the column: the four text operators build a
 * pattern and quote it whatever the column holds, so refusing text typed into one of them
 * on a numeric column would turn back a filter the renderer accepts.
 *
 * Cancelling applies nothing at all: the caller only learns a value through `onApply`.
 */
export function FilterValueDialog({
  column,
  operator,
  valueKind,
  existing = null,
  onApply,
  onCancel
}: FilterValueDialogProps) {
  const list = operatorTakesValues(operator);
  const [value, setValue] = useState(existing && !list ? (existing.value ?? '') : '');
  // Pre-filled in the list's STORED order rather than the rendered one, so the lines a user
  // sees are the lines they typed; the renderer sorts on its own way to the SQL.
  const [text, setText] = useState(list ? filterValuesText(existing?.values ?? []) : '');
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const submitList = () => {
    const parsed = parseFilterValues(text, valueKind);
    if ('refusal' in parsed) {
      setError(parsed.refusal);
      return;
    }
    onApply({values: parsed.values});
  };

  const submitValue = () => {
    const numeric = valueKind === 'number' && operatorUsesValueKind(operator);
    if (numeric && !isBareNumeric(value.trim())) {
      setError(NUMERIC_VALUE_REFUSAL);
      return;
    }
    // An empty pattern matches every non-NULL row, which is never the gesture the user made.
    // The four text operators are exactly the ones that take a value without reading the
    // column's kind. A comparison keeps taking an empty one: `= ''` is a real question, and
    // on a table built from CSV files it is the one that finds the blank cells.
    if (!operatorUsesValueKind(operator) && value === '') {
      setError(EMPTY_TEXT_REFUSAL);
      return;
    }
    // Trimmed for a number (where surrounding space is never meaningful) and verbatim for
    // a string, where a trailing space is a value a cell can genuinely hold.
    onApply({value: numeric ? value.trim() : value});
  };

  return (
    <FormDialog
      title={`Filter ${column}`}
      ariaLabel={`Filter ${column}`}
      submitLabel="Apply filter"
      // The textarea is deliberately NOT the autofocus ref: that ref doubles as the one
      // field Enter submits from, and Enter in a list of values is a new line. With none
      // passed, the dialog focuses its first control, which is the field either way.
      autoFocusRef={list ? undefined : inputRef}
      autoFocusSelect={!list}
      onSubmit={list ? submitList : submitValue}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Show rows where <span className="font-medium text-text">{column}</span> {FILTER_OPERATOR_LABELS[operator]}:
      </p>
      {list ? (
        <FilterValuesField
          ref={textRef}
          className="mt-3"
          label={VALUES_FIELD_LABEL}
          value={text}
          error={error}
          onChange={(next) => {
            setText(next);
            setError(null);
          }}
        />
      ) : (
        <Input
          ref={inputRef}
          className="mt-3"
          label="Value"
          value={value}
          error={error}
          inputMode={valueKind === 'number' && operatorUsesValueKind(operator) ? 'decimal' : undefined}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
        />
      )}
    </FormDialog>
  );
}
