import {useMemo, useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {EXPLORER_FILTER_VALUES_MAX} from './dataExplorer.constants';
import {FILTER_OPERATOR_LABELS, narrowingFor, operatorListsNull, operatorTakesValues} from './explorationQueryOps';
import {refusalOf, sameValue} from './columnValues';
import {FilterValuePicker} from './FilterValuePicker';
import {useColumnValues} from './useColumnValues';
import type {
  ColumnFilter,
  ExplorationQuery,
  ExplorationSource,
  FilterValueKind,
  ValueSelection
} from './dataExplorer.types';

/** Refused when Apply has nothing to filter by. */
export const TICK_AT_LEAST_ONE = 'Tick at least one value.';

/** Refused when more values are ticked than one list may hold. */
export const CHOOSE_AT_MOST = `Choose at most ${EXPLORER_FILTER_VALUES_MAX.toLocaleString('en-US')} values.`;

/** What the dialog applies: a list filter, or clearing the column's filter when every value is kept. */
export type FilterByValueResult =
  {kind: 'filter'; operator: 'in' | 'notIn'; values: string[]; includesNull?: true} | {kind: 'clear'};

export type FilterByValueDialogProps = {
  source: ExplorationSource;
  column: string;
  valueKind: FilterValueKind;
  /** The applied description: its other filters narrow the list, and its filter on this column is the start. */
  query: ExplorationQuery;
  existing: ColumnFilter | null;
  /** From the Options menu, the value of the cell it was opened on; from a header menu, null. */
  seed: {value: string | null} | null;
  onApply: (result: FilterByValueResult) => void;
  onCancel: () => void;
};

// A seed the list could not tick starts nothing ticked, rather than a selection Apply would write.
function seedSelection(seed: {value: string | null} | null, valueKind: FilterValueKind): ValueSelection {
  if (!seed) return {values: [], includesNull: false};
  if (seed.value === null) return {values: [], includesNull: true};
  const refused = refusalOf({value: seed.value, count: 0}, valueKind, 'in') !== null;
  return {values: refused ? [] : [seed.value], includesNull: false};
}

/**
 * Filters a column to the values the user ticks, or away from them, from a list of what it holds.
 *
 * Starts from the column's list filter when it has one — its operator, its values and its NULL —
 * so reopening is an edit; otherwise from **is one of** and the cell the Options menu was opened
 * on. Apply does not wait for the list: until it lands the selected values are under *Also
 * selected*, and the one rule that needs the whole list, "every value kept clears the filter
 * instead", is judged only once it has.
 *
 * The list's request is made here as well as inside the picker, with the same key, so it is one
 * listing: this dialog needs the entries for its apply rules, and the picker is the component a
 * condition builder embeds on its own.
 */
export function FilterByValueDialog({
  source,
  column,
  valueKind,
  query,
  existing,
  seed,
  onApply,
  onCancel
}: FilterByValueDialogProps) {
  const listed = existing !== null && operatorTakesValues(existing.operator) ? existing : null;
  const [operator, setOperator] = useState<'in' | 'notIn'>(listed?.operator === 'notIn' ? 'notIn' : 'in');
  const [selection, setSelection] = useState<ValueSelection>(() =>
    listed ? {values: listed.values ?? [], includesNull: listed.includesNull === true} : seedSelection(seed, valueKind)
  );
  const [error, setError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  // Enter in the search box searches; it must not apply a filter the user is still choosing.
  const noEnterSubmit = useRef<HTMLElement>(null);

  const narrowing = useMemo(() => narrowingFor(query, column), [query, column]);
  const {listing} = useColumnValues({source, narrowing, column});

  const submit = () => {
    const values = [...new Set(selection.values)];
    const includesNull = operatorListsNull(operator) && selection.includesNull;
    if (values.length === 0 && !includesNull) {
      setError(TICK_AT_LEAST_ONE);
      return;
    }
    if (values.length > EXPLORER_FILTER_VALUES_MAX) {
      setError(CHOOSE_AT_MOST);
      return;
    }
    // Every value kept, from a list known to be whole, is no filter at all: the same rows, from a
    // shorter statement that is the unfiltered execution already cached.
    if (operator === 'in' && listing.status === 'ready' && !listing.truncated && listing.entries.length > 0) {
      const listedAs = (value: string) =>
        listing.entries.some((entry) => entry.value !== null && sameValue(valueKind, entry.value, value));
      const keepsEvery = listing.entries.every(
        (entry) =>
          refusalOf(entry, valueKind, operator) === null &&
          (entry.value === null
            ? includesNull
            : values.some((value) => sameValue(valueKind, value, entry.value as string)))
      );
      if (keepsEvery && values.every(listedAs)) {
        onApply({kind: 'clear'});
        return;
      }
    }
    onApply(includesNull ? {kind: 'filter', operator, values, includesNull: true} : {kind: 'filter', operator, values});
  };

  return (
    <FormDialog
      title={`Filter ${column} by value`}
      ariaLabel={`Filter ${column} by value`}
      submitLabel="Apply filter"
      autoFocusRef={searchRef}
      submitOnEnterRef={noEnterSubmit}
      scrollBody
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Show rows where <span className="font-medium text-text">{column}</span>
      </p>
      <fieldset className="mt-2 flex flex-wrap gap-x-4">
        <legend className="sr-only">Match</legend>
        {(['in', 'notIn'] as const).map((choice) => (
          <label
            key={choice}
            className="flex min-h-[24px] items-center gap-2 text-sm text-text">
            <input
              type="radio"
              name="filter-by-value-match"
              checked={operator === choice}
              onChange={() => {
                setOperator(choice);
                setError(null);
              }}
            />
            {FILTER_OPERATOR_LABELS[choice]}
          </label>
        ))}
      </fieldset>
      <p className="mb-3 mt-2 text-sm text-text-2">the ticked values:</p>
      <FilterValuePicker
        source={source}
        column={column}
        valueKind={valueKind}
        operator={operator}
        narrowing={narrowing}
        selection={selection}
        onSelectionChange={(next) => {
          setSelection(next);
          setError(null);
        }}
        searchRef={searchRef}
      />
      {error && (
        <p
          role="alert"
          className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </FormDialog>
  );
}
