import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {FILTER_OPERATOR_LABELS} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import type {FilterOperator, FilterValueKind} from './dataExplorer.types';

export type FilterValueDialogProps = {
  column: string;
  operator: FilterOperator;
  /** How the value will be rendered — decides whether a number is required. */
  valueKind: FilterValueKind;
  /** Pre-filled value, e.g. when editing the filter already on this column. */
  initialValue?: string;
  onApply: (value: string) => void;
  onCancel: () => void;
};

export const NUMERIC_VALUE_REFUSAL = 'Enter a number — this column holds numbers, not text.';

/**
 * Asks for the value a comparison filters by.
 *
 * The value never reaches the SQL unescaped: it is carried on a `ColumnFilter` and quoted
 * by `sqlLiteral` at render time. What this dialog owns instead is the ONE case the
 * renderer cannot escape its way out of — a numeric column, whose value is emitted bare —
 * and it refuses that here, at the input, using the renderer's own predicate. The
 * alternative is an `ExplorationRenderError`, whose message names a column and an operator
 * and is operator text the error-wording rule forbids showing anyone.
 *
 * Cancelling applies nothing at all: the caller only learns a value through `onApply`.
 */
export function FilterValueDialog({
  column,
  operator,
  valueKind,
  initialValue = '',
  onApply,
  onCancel
}: FilterValueDialogProps) {
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    if (valueKind === 'number' && !isBareNumeric(value.trim())) {
      setError(NUMERIC_VALUE_REFUSAL);
      return;
    }
    // Trimmed for a number (where surrounding space is never meaningful) and verbatim for
    // a string, where a trailing space is a value a cell can genuinely hold.
    onApply(valueKind === 'number' ? value.trim() : value);
  };

  return (
    <FormDialog
      title={`Filter ${column}`}
      ariaLabel={`Filter ${column}`}
      submitLabel="Apply filter"
      autoFocusRef={inputRef}
      autoFocusSelect
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Show rows where <span className="font-medium text-text">{column}</span> {FILTER_OPERATOR_LABELS[operator]}:
      </p>
      <Input
        ref={inputRef}
        className="mt-3"
        label="Value"
        value={value}
        error={error}
        inputMode={valueKind === 'number' ? 'decimal' : undefined}
        onChange={(e) => {
          setValue(e.target.value);
          setError(null);
        }}
      />
    </FormDialog>
  );
}
