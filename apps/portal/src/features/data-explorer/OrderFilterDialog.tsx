import {useId, useState} from 'react';
import {Button} from '../../components/Button';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {cx} from '../../lib/cx';
import {LAST_COLUMN_REFUSAL} from './useColumnGeometry';
import {NUMERIC_VALUE_REFUSAL} from './FilterValueDialog';
import {FilterValuesField} from './FilterValuesField';
import {SELECT_CLASS} from './dataExplorer.constants';
import {
  EMPTY_TEXT_REFUSAL,
  FILTER_OPERATOR_LABELS,
  clearFilter,
  clearSort,
  filterOf,
  filterValueKind,
  filterValuesText,
  moveSortPriority,
  moveSortRefusal,
  operatorTakesValue,
  operatorTakesValues,
  operatorUsesValueKind,
  operatorsFor,
  parseFilterValues,
  setFilter,
  setSort,
  sortOf
} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import type {ExplorationQuery, FilterOperator} from './dataExplorer.types';
import type {GridColumn} from './useColumnGeometry';

/** How a refused control looks: dimmed like `Button.disabledReason`, and still focusable. */
const REFUSED = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-45';

export type OrderFilterSettings = {
  query: ExplorationQuery;
  hiddenColumns: string[];
  pinnedColumns: string[];
};

export type OrderFilterDialogProps = {
  /** Every column in display order, hidden ones included. */
  columns: GridColumn[];
  /**
   * Why a column takes no filter and no sort, or null when it does.
   *
   * The same reader the header menu asks. It matters most HERE: Record view, the default
   * below `tablet`, and Text view have no column header, so this dialog stands in for the
   * header menu's sort and criteria there — and a calculated column offered a sort here would
   * be refused by the renderer, not by Athena, taking the whole exploration to an error banner.
   */
  queryRefusalOf: (column: string) => string | null;
  /** The applied description — the starting point for the staged one. */
  query: ExplorationQuery;
  onApply: (settings: OrderFilterSettings) => void;
  onCancel: () => void;
};

/**
 * Every column's visibility, pinning, sort and criteria in one staged form.
 *
 * The point of the dialog is the STAGING: several changes made here become **one**
 * execution on Apply, where the same changes made from the header would be one execution
 * each. So the draft is local — nothing here touches the tab until Apply, and Cancel
 * discards it whole, presentation included.
 *
 * The draft is ONE object holding both halves rather than a staged query here and a staged
 * presentation somewhere else, which is what makes "Cancel discards every staged change"
 * Structural rather than a rule two pieces of state have to keep.
 *
 * **No field submits on Enter.** `FormDialog` suppresses the browser's implicit submission
 * for every input and `<select>`, and this dialog designates no field
 * to submit from: every field in it is a criteria row, and a criteria row mid-edit filing
 * the whole dialog is exactly what that suppression exists to prevent. Enter on the Apply
 * button still submits, natively.
 *
 * **A refused Show, Sort or Filter is `aria-disabled`, never `disabled`,** and is described by
 * its reason, printed in the row. A `disabled` one is skipped by Tab and can only explain itself
 * in a `title`, which a phone never shows — and on a phone, Record view has no column header, so
 * this dialog is where its sort and criteria live. Each handler checks the refusal itself, and
 * the controlled value puts the control back.
 */
export function OrderFilterDialog({columns, queryRefusalOf, query, onApply, onCancel}: OrderFilterDialogProps) {
  const [draft, setDraft] = useState<OrderFilterSettings>({
    query,
    hiddenColumns: columns.filter((c) => c.hidden).map((c) => c.name),
    pinnedColumns: columns.filter((c) => c.pinned).map((c) => c.name)
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const reasonId = useId();
  // The multi-line field's RAW text, per column, held apart from the staged query: a list
  // is `string[]`, which cannot represent a blank line the user has just opened or a
  // duplicate they are half way through typing. It is parsed once, on Apply.
  // Seeded AT MOUNT from the applied filters, not only when the operator changes: this
  // dialog unmounts on Cancel, so an empty start meant every reopen showed a blank field
  // for a list that was still applied — and then refused Apply for a column the user had
  // not touched, with the list only reappearing if they cycled the operator dropdown.
  const [listText, setListText] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      query.filters
        .filter((f) => operatorTakesValues(f.operator))
        .map((f) => [f.column, filterValuesText(f.values ?? [])])
    )
  );

  const editQuery = (update: (q: ExplorationQuery) => ExplorationQuery) =>
    setDraft((d) => ({...d, query: update(d.query)}));

  const toggle = (list: string[], name: string): string[] =>
    list.includes(name) ? list.filter((n) => n !== name) : [...list, name];

  const visibleCount = columns.length - draft.hiddenColumns.length;

  const changeOperator = (column: string, operator: FilterOperator | '') => {
    setErrors((e) => ({...e, [column]: ''}));
    // Seeded OUTSIDE the query updater: a `setState` call inside another one runs twice
    // under StrictMode, and an updater that is not pure is a bug that only shows up there.
    // Moving between the two list operators keeps the list, so `is one of` to `is not one
    // of` is one click rather than a retype. Moving between a list and a single value
    // carries nothing across: `setFilter` writes only the field the new operator reads.
    if (operator !== '' && operatorTakesValues(operator)) {
      const stored = filterOf(draft.query, column)?.values ?? [];
      setListText((t) => ({...t, [column]: t[column] ?? filterValuesText(stored)}));
    }
    editQuery((q) => {
      if (operator === '') return clearFilter(q, column);
      const existing = filterOf(q, column);
      return setFilter(q, {
        column,
        operator,
        // The value survives an operator change (`= 5` to `> 5` is one keystroke's worth
        // of intent) and is dropped for the tests that must carry none.
        value: operatorTakesValue(operator) ? (existing?.value ?? '') : undefined,
        values: operatorTakesValues(operator) ? (existing?.values ?? []) : undefined,
        valueKind: filterValueKind(columns.find((c) => c.name === column)?.type ?? '')
      });
    });
  };

  const submit = () => {
    // Refused HERE, at the field, for the reason `FilterValueDialog` gives: the renderer's
    // refusal is an `ExplorationRenderError` naming a column and an operator, which
    // the error-wording rule forbids showing anyone. Same predicate, so the two cannot disagree.
    const bad: Record<string, string> = {};
    let query = draft.query;
    for (const filter of draft.query.filters) {
      if (operatorTakesValues(filter.operator)) {
        // Parsed HERE and nowhere else in this dialog, through the same reader the value
        // dialog uses — the two surfaces must refuse the same lists, and the way they
        // would come to disagree is a second parser.
        const parsed = parseFilterValues(listText[filter.column] ?? '', filter.valueKind ?? 'string');
        if ('refusal' in parsed) bad[filter.column] = parsed.refusal;
        else query = setFilter(query, {...filter, values: parsed.values});
        continue;
      }
      if (!operatorTakesValue(filter.operator)) continue;
      // The numeric refusal follows the OPERATOR, not the column: the four text operators
      // quote their value whatever the column holds, so refusing text typed into one of
      // them here would turn back a filter the renderer accepts.
      if (!operatorUsesValueKind(filter.operator)) {
        if ((filter.value ?? '') === '') bad[filter.column] = EMPTY_TEXT_REFUSAL;
        continue;
      }
      if (filter.valueKind === 'number' && !isBareNumeric((filter.value ?? '').trim())) {
        bad[filter.column] = NUMERIC_VALUE_REFUSAL;
      }
    }
    if (Object.keys(bad).length > 0) {
      setErrors(bad);
      return;
    }
    onApply({...draft, query});
  };

  return (
    <FormDialog
      title="Order and filter"
      ariaLabel="Order and filter"
      submitLabel="Apply"
      className="max-w-3xl"
      scrollBody
      onSubmit={submit}
      onCancel={onCancel}>
      <p className="mt-2 text-sm text-text-2">
        Changes apply together when you press Apply — one query, however many you make.
      </p>

      <ul className="mt-4 flex flex-col gap-2">
        {columns.map((column, index) => {
          const hidden = draft.hiddenColumns.includes(column.name);
          // The grid needs a column to draw; the same refusal the panel makes, over the
          // STAGED state rather than the applied one.
          const lastVisible = !hidden && visibleCount <= 1;
          const sort = sortOf(draft.query, column.name);
          const filter = filterOf(draft.query, column.name);
          // Show and Pin stay available on a calculated column — geometry applies to it
          // like any other; only the two controls that would reach the SQL are refused.
          const refusal = queryRefusalOf(column.name);
          const showReasonId = `${reasonId}-${index}-show`;
          const queryReasonId = `${reasonId}-${index}-query`;
          return (
            <li
              key={column.name}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2">
              <span className="min-w-0 flex-1 basis-40">
                <span className="block truncate text-sm text-text">{column.name}</span>
                <span className="block truncate font-mono text-[10px] text-text-3">{column.type}</span>
              </span>

              <label className="flex items-center gap-1.5 text-xs text-text-2">
                <input
                  type="checkbox"
                  aria-label={`Show ${column.name}`}
                  checked={!hidden}
                  className={REFUSED}
                  aria-disabled={lastVisible || undefined}
                  aria-describedby={lastVisible ? showReasonId : undefined}
                  onChange={() => {
                    if (lastVisible) return;
                    setDraft((d) => ({...d, hiddenColumns: toggle(d.hiddenColumns, column.name)}));
                  }}
                />
                Show
              </label>

              <label className="flex items-center gap-1.5 text-xs text-text-2">
                <input
                  type="checkbox"
                  aria-label={`Pin ${column.name}`}
                  checked={draft.pinnedColumns.includes(column.name)}
                  onChange={() => setDraft((d) => ({...d, pinnedColumns: toggle(d.pinnedColumns, column.name)}))}
                />
                Pin
              </label>

              <select
                aria-label={`Sort ${column.name}`}
                className={cx(SELECT_CLASS, REFUSED)}
                aria-disabled={refusal !== null || undefined}
                aria-describedby={refusal !== null ? queryReasonId : undefined}
                value={sort?.direction ?? ''}
                onChange={(e) => {
                  if (refusal !== null) return;
                  const direction = e.target.value;
                  editQuery((q) =>
                    direction === '' ? clearSort(q, column.name) : setSort(q, column.name, direction as 'asc' | 'desc')
                  );
                }}>
                <option value="">No sort</option>
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>

              {sort && (
                <span className="flex items-center gap-1">
                  <span className="text-xs text-text-3">{sort.position}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Sort ${column.name} earlier`}
                    disabledReason={moveSortRefusal(draft.query, column.name, -1) ?? undefined}
                    onClick={() => editQuery((q) => moveSortPriority(q, column.name, -1))}>
                    ↑
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Sort ${column.name} later`}
                    disabledReason={moveSortRefusal(draft.query, column.name, 1) ?? undefined}
                    onClick={() => editQuery((q) => moveSortPriority(q, column.name, 1))}>
                    ↓
                  </Button>
                </span>
              )}

              <select
                aria-label={`Filter ${column.name}`}
                className={cx(SELECT_CLASS, REFUSED)}
                aria-disabled={refusal !== null || undefined}
                aria-describedby={refusal !== null ? queryReasonId : undefined}
                value={filter?.operator ?? ''}
                onChange={(e) => {
                  if (refusal === null) changeOperator(column.name, e.target.value as FilterOperator | '');
                }}>
                <option value="">No filter</option>
                {operatorsFor(column.type).map((operator) => (
                  <option
                    key={operator}
                    value={operator}>
                    {FILTER_OPERATOR_LABELS[operator]}
                  </option>
                ))}
              </select>

              {filter && operatorTakesValue(filter.operator) && (
                <span className="basis-40">
                  <Input
                    aria-label={`Value for ${column.name}`}
                    value={filter.value ?? ''}
                    error={errors[column.name] || null}
                    onChange={(e) => {
                      setErrors((errs) => ({...errs, [column.name]: ''}));
                      editQuery((q) => setFilter(q, {...filter, value: e.target.value}));
                    }}
                  />
                </span>
              )}

              {filter && operatorTakesValues(filter.operator) && (
                <FilterValuesField
                  className="basis-full"
                  label={`Values for ${column.name}, one per line`}
                  labelHidden
                  value={listText[column.name] ?? ''}
                  error={errors[column.name] || null}
                  onChange={(next) => {
                    setErrors((errs) => ({...errs, [column.name]: ''}));
                    setListText((t) => ({...t, [column.name]: next}));
                  }}
                />
              )}

              {lastVisible && (
                <p
                  id={showReasonId}
                  className="basis-full text-xs text-text-3">
                  {LAST_COLUMN_REFUSAL}
                </p>
              )}
              {refusal !== null && (
                <p
                  id={queryReasonId}
                  className="basis-full text-xs text-text-3">
                  {refusal}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </FormDialog>
  );
}
