import {useState} from 'react';
import {Button} from '../../components/Button';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {LAST_COLUMN_REFUSAL} from './useColumnGeometry';
import {NUMERIC_VALUE_REFUSAL} from './FilterValueDialog';
import {SELECT_CLASS} from './dataExplorer.constants';
import {
  FILTER_OPERATORS,
  FILTER_OPERATOR_LABELS,
  clearFilter,
  clearSort,
  filterOf,
  filterValueKind,
  moveSortPriority,
  moveSortRefusal,
  operatorTakesValue,
  setFilter,
  setSort,
  sortOf
} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import type {ExplorationQuery, FilterOperator} from './dataExplorer.types';
import type {GridColumn} from './useColumnGeometry';

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
   * The same reader the header menu asks (SPEC-182). It matters most HERE: below `tablet`
   * the header menu is unreachable, so this dialog is the only way to sort or filter — and
   * a calculated column offered a sort here would be refused by the renderer, not by
   * Athena, taking the whole exploration to an error banner.
   */
  queryRefusalOf: (column: string) => string | null;
  /** The applied description — the starting point for the staged one. */
  query: ExplorationQuery;
  onApply: (settings: OrderFilterSettings) => void;
  onCancel: () => void;
};

/**
 * Every column's visibility, pinning, sort and criteria in one staged form (SPEC-181 FR-005).
 *
 * The point of the dialog is the STAGING: several changes made here become **one**
 * execution on Apply, where the same changes made from the header would be one execution
 * each. So the draft is local — nothing here touches the tab until Apply, and Cancel
 * discards it whole, presentation included.
 *
 * The draft is ONE object holding both halves rather than a staged query here and a staged
 * presentation somewhere else, which is what makes "Cancel discards every staged change"
 * (AC3) structural rather than a rule two pieces of state have to keep.
 *
 * **No field submits on Enter.** `FormDialog` suppresses the browser's implicit submission
 * for every input and `<select>` (SPEC-155, SPEC-175), and this dialog designates no field
 * to submit from: every field in it is a criteria row, and a criteria row mid-edit filing
 * the whole dialog is exactly what that suppression exists to prevent. Enter on the Apply
 * button still submits, natively.
 */
export function OrderFilterDialog({columns, queryRefusalOf, query, onApply, onCancel}: OrderFilterDialogProps) {
  const [draft, setDraft] = useState<OrderFilterSettings>({
    query,
    hiddenColumns: columns.filter((c) => c.hidden).map((c) => c.name),
    pinnedColumns: columns.filter((c) => c.pinned).map((c) => c.name)
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const editQuery = (update: (q: ExplorationQuery) => ExplorationQuery) =>
    setDraft((d) => ({...d, query: update(d.query)}));

  const toggle = (list: string[], name: string): string[] =>
    list.includes(name) ? list.filter((n) => n !== name) : [...list, name];

  const visibleCount = columns.length - draft.hiddenColumns.length;

  const changeOperator = (column: string, operator: FilterOperator | '') => {
    setErrors((e) => ({...e, [column]: ''}));
    editQuery((q) => {
      if (operator === '') return clearFilter(q, column);
      const existing = filterOf(q, column);
      return setFilter(q, {
        column,
        operator,
        // The value survives an operator change (`= 5` to `> 5` is one keystroke's worth
        // of intent) and is dropped for the null tests, which must carry none.
        value: operatorTakesValue(operator) ? (existing?.value ?? '') : undefined,
        valueKind: filterValueKind(columns.find((c) => c.name === column)?.type ?? '')
      });
    });
  };

  const submit = () => {
    // Refused HERE, at the field, for the reason `FilterValueDialog` gives: the renderer's
    // refusal is an `ExplorationRenderError` naming a column and an operator, which
    // SPEC-106 forbids showing anyone. Same predicate, so the two cannot disagree.
    const bad: Record<string, string> = {};
    for (const filter of draft.query.filters) {
      if (!operatorTakesValue(filter.operator)) continue;
      if (filter.valueKind === 'number' && !isBareNumeric((filter.value ?? '').trim())) {
        bad[filter.column] = NUMERIC_VALUE_REFUSAL;
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
        {columns.map((column) => {
          const hidden = draft.hiddenColumns.includes(column.name);
          const sort = sortOf(draft.query, column.name);
          const filter = filterOf(draft.query, column.name);
          // Show and Pin stay available on a calculated column — geometry applies to it
          // like any other; only the two controls that would reach the SQL are refused.
          const refusal = queryRefusalOf(column.name);
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
                  // The grid needs a column to draw; the same refusal SPEC-180's panel
                  // makes, over the STAGED state rather than the applied one.
                  disabled={!hidden && visibleCount <= 1}
                  title={!hidden && visibleCount <= 1 ? LAST_COLUMN_REFUSAL : undefined}
                  onChange={() => setDraft((d) => ({...d, hiddenColumns: toggle(d.hiddenColumns, column.name)}))}
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
                className={SELECT_CLASS}
                disabled={refusal !== null}
                title={refusal ?? undefined}
                value={sort?.direction ?? ''}
                onChange={(e) =>
                  editQuery((q) =>
                    e.target.value === ''
                      ? clearSort(q, column.name)
                      : setSort(q, column.name, e.target.value as 'asc' | 'desc')
                  )
                }>
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
                className={SELECT_CLASS}
                disabled={refusal !== null}
                title={refusal ?? undefined}
                value={filter?.operator ?? ''}
                onChange={(e) => changeOperator(column.name, e.target.value as FilterOperator | '')}>
                <option value="">No filter</option>
                {FILTER_OPERATORS.map((operator) => (
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
            </li>
          );
        })}
      </ul>
    </FormDialog>
  );
}
