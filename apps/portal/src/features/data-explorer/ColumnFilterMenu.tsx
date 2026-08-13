import {useState} from 'react';
import {Menu, type MenuItem} from '../../components/Menu';
import {cx} from '../../lib/cx';
import {FilterValueDialog} from './FilterValueDialog';
import {FILTER_OPERATOR_LABELS, operatorTakesValue} from './explorationQueryOps';
import type {ColumnFilter, FilterOperator, FilterValueKind} from './dataExplorer.types';

/**
 * What a per-column surface can do to the query description.
 *
 * One object, built once from `useExplorationQuery`, rather than a handful of callbacks
 * threaded through the grid: the header menu, the settings dialog and the cell action all
 * make the same four edits, and they must make them the same way (SPEC-181 FR-002 AC4's
 * "replaces rather than accumulates" is a property of `setFilter`, not of a caller).
 */
export type ColumnQueryActions = {
  sortOf: (column: string) => {direction: 'asc' | 'desc'; position: number} | null;
  /** How many columns the ordering has, so a lone sort need not show a priority. */
  sortCount: number;
  filterOf: (column: string) => ColumnFilter | null;
  /** The kind a filter on this column must carry, from its declared type. */
  valueKindOf: (column: string) => FilterValueKind;
  sort: (column: string, direction: 'asc' | 'desc') => void;
  clearSort: (column: string) => void;
  filter: (column: string, operator: FilterOperator, value?: string) => void;
  clearFilter: (column: string) => void;
};

export type ColumnFilterMenuProps = {
  column: string;
  actions: ColumnQueryActions;
};

/**
 * The per-column header menu: ordering, the six comparisons, and the two null tests
 * (SPEC-181 FR-001).
 *
 * Composed on the `Menu` primitive, and its accessible name **names its column** — two
 * columns' menus are otherwise indistinguishable to anything that queries by name, which
 * is every test and every screen reader.
 *
 * A comparison opens `FilterValueDialog`; the null tests apply straight away, because
 * there is nothing to ask for. Either way exactly one description change reaches the tab,
 * so exactly one execution is minted (AC5).
 */
export function ColumnFilterMenu({column, actions}: ColumnFilterMenuProps) {
  const [pending, setPending] = useState<FilterOperator | null>(null);
  const sort = actions.sortOf(column);
  const filter = actions.filterOf(column);

  const items: MenuItem[] = [
    {kind: 'action', label: 'Sort ascending', onSelect: () => actions.sort(column, 'asc')},
    {kind: 'action', label: 'Sort descending', onSelect: () => actions.sort(column, 'desc')},
    {kind: 'action', label: 'Clear sort', disabled: !sort, onSelect: () => actions.clearSort(column)},
    {kind: 'separator'},
    ...(['=', '<>', '>', '>=', '<', '<='] as FilterOperator[]).map(
      (operator): MenuItem => ({
        kind: 'action',
        label: `Filter: ${FILTER_OPERATOR_LABELS[operator]}…`,
        onSelect: () => setPending(operator)
      })
    ),
    {kind: 'action', label: 'Filter: is null', onSelect: () => actions.filter(column, 'isNull')},
    {kind: 'action', label: 'Filter: is not null', onSelect: () => actions.filter(column, 'isNotNull')},
    {kind: 'action', label: 'Clear filter', disabled: !filter, onSelect: () => actions.clearFilter(column)}
  ];

  // The whole state of the column in one string, because the trigger's glyphs are
  // decoration: `aria-label` on the header cell already suppresses everything inside it,
  // so anything a screen reader is to hear about this column's sort has to be here.
  const name = [
    `Column options: ${column}`,
    sort ? `sorted ${sort.direction === 'asc' ? 'ascending' : 'descending'}, sort ${sort.position}` : null,
    filter ? 'filtered' : null
  ]
    .filter(Boolean)
    .join(', ');

  return (
    // `data-column-menu` marks everything the menu owns, so the header cell's own click
    // handler (which selects the whole column) can tell a menu gesture from a header one.
    <div
      data-column-menu="true"
      className="absolute right-1 top-1">
      <Menu
        ariaLabel={`Column options: ${column}`}
        align="left"
        trigger={({open, toggle, ref, menuId}) => (
          <button
            ref={ref}
            type="button"
            aria-label={name}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            onClick={toggle}
            className={cx(
              'flex h-6 items-center gap-0.5 rounded px-1 text-[11px] text-text-3 hover:bg-surface hover:text-text',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'
            )}>
            {sort && (
              <span aria-hidden="true">
                {sort.direction === 'asc' ? '▲' : '▼'}
                {actions.sortCount > 1 ? sort.position : ''}
              </span>
            )}
            {filter && <span aria-hidden="true">•</span>}
            <span aria-hidden="true">⋯</span>
          </button>
        )}
        items={items}
      />

      {pending && (
        <FilterValueDialog
          column={column}
          operator={pending}
          valueKind={actions.valueKindOf(column)}
          initialValue={filter && operatorTakesValue(filter.operator) ? (filter.value ?? '') : ''}
          onApply={(value) => {
            setPending(null);
            actions.filter(column, pending, value);
          }}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
