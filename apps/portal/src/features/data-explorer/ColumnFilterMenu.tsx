import {useState} from 'react';
import {Menu, type MenuItem} from '../../components/Menu';
import {cx} from '../../lib/cx';
import {contentBottomOf, contentRightOf, GRID_SCROLL_BOX_ATTRIBUTE, menuAlignFor, menuMaxHeightFor} from './menuAlign';
import {FILTER_OPERATOR_LABELS, operatorTakesValue, operatorTakesValues} from './explorationQueryOps';
import type {ColumnFilter, FilterOperator, FilterValueKind} from './dataExplorer.types';
import type {FilterValueResult} from './FilterValueDialog';

/**
 * What a per-column surface can do to the query description.
 *
 * One object, built once from `useExplorationQuery`, rather than a handful of callbacks
 * threaded through the grid: the header menu, the settings dialog and the cell action all
 * make the same four edits, and they must make them the same way (the shared-edit rule's
 * "replaces rather than accumulates" is a property of `setFilter`, not of a caller).
 */
export type ColumnQueryActions = {
  /**
   * Why this column takes no filter and no sort, or null when it does.
   *
   * The percentage column is the first that is **not part of the query**: the grouped
   * result's percentage, computed in the browser and appended to the result. It is a real
   * grid column — it sizes, hides, pins and reorders — but there is no such column in the
   * SQL, so an `ORDER BY` on it is a description the renderer REFUSES (taking the whole
   * exploration to an error banner) and a `WHERE` on it is a `COLUMN_NOT_FOUND` at Athena.
   * Every surface that offers a filter or a sort asks this first.
   */
  queryRefusalOf: (column: string) => string | null;
  sortOf: (column: string) => {direction: 'asc' | 'desc'; position: number} | null;
  /** How many columns the ordering has, so a lone sort need not show a priority. */
  sortCount: number;
  filterOf: (column: string) => ColumnFilter | null;
  /** The kind a filter on this column must carry, from its declared type. */
  valueKindOf: (column: string) => FilterValueKind;
  /**
   * The operators this column's type offers, in offer order.
   *
   * Asked rather than listed, so the header menu and the settings dialog cannot come to
   * disagree about which columns take a `LIKE` — and so neither offers one against a type
   * Trino would reject it on.
   */
  operatorsOf: (column: string) => FilterOperator[];
  sort: (column: string, direction: 'asc' | 'desc') => void;
  clearSort: (column: string) => void;
  filter: (column: string, operator: FilterOperator, input?: FilterValueResult) => void;
  clearFilter: (column: string) => void;
};

/** Marks each header's menu button with its column, so focus can land on a neighbour's after a hide. */
export const COLUMN_MENU_TRIGGER_ATTRIBUTE = 'data-column-menu-trigger';

export type ColumnFilterMenuProps = {
  column: string;
  actions: ColumnQueryActions;
  /** Asks the REGION to open the value dialog — see below for why it is not opened here. */
  onRequestValue: (column: string, operator: FilterOperator) => void;
  /** Hides the column from the grid; it comes back from the Columns panel. */
  onHide: (column: string) => void;
  /** Why this column cannot be hidden (the last one visible), or null when it can. */
  hideRefusal: string | null;
};

/**
 * The per-column header menu: ordering, every filter operator the column's type offers, and Hide.
 *
 * Composed on the `Menu` primitive, and its accessible name **names its column** — two
 * columns' menus are otherwise indistinguishable to anything that queries by name, which
 * is every test and every screen reader.
 *
 * An operator that needs something typed ASKS THE REGION for it; the null and empty tests
 * apply straight away, because there is nothing to ask for. Either way exactly one
 * description change reaches the tab, so exactly one execution is minted.
 *
 * The dialog is raised by the region rather than rendered here because `Modal` does not
 * portal: opened from inside a header cell it would be confined to that cell's stacking
 * context (`z-20`) and paint UNDER the sticky pinned headers (`z-30`), with the scrim
 * punched through. Nothing in jsdom can see that.
 */
export function ColumnFilterMenu({column, actions, onRequestValue, onHide, hideRefusal}: ColumnFilterMenuProps) {
  const [placement, setPlacement] = useState<{align: 'left' | 'right'; maxHeight?: number}>({align: 'left'});
  const sort = actions.sortOf(column);
  const filter = actions.filterOf(column);
  const refusal = actions.queryRefusalOf(column);

  // A column the query cannot address keeps its menu and offers ONE disabled item saying
  // why — rather than a menu of controls that would each take the exploration down, or no
  // menu at all, which would leave the user to discover the difference by clicking.
  const queryItems: MenuItem[] = refusal
    ? [{kind: 'action', label: refusal, disabled: true, onSelect: () => {}}]
    : [
        {kind: 'action', label: 'Sort ascending', onSelect: () => actions.sort(column, 'asc')},
        {kind: 'action', label: 'Sort descending', onSelect: () => actions.sort(column, 'desc')},
        {kind: 'action', label: 'Clear sort', disabled: !sort, onSelect: () => actions.clearSort(column)},
        {kind: 'separator'},
        // Derived from the operator table rather than re-listed, and in ITS order: a
        // hand-written array cast to `FilterOperator[]` type-checks with half of them
        // missing, and a second list here is one that can offer what the settings dialog
        // does not. An operator that needs something typed opens the dialog and keeps the
        // trailing ellipsis; one that applies at once does not.
        ...actions.operatorsOf(column).map((operator): MenuItem => {
          const asks = operatorTakesValue(operator) || operatorTakesValues(operator);
          return {
            kind: 'action',
            label: `Filter: ${FILTER_OPERATOR_LABELS[operator]}${asks ? '…' : ''}`,
            onSelect: () => (asks ? onRequestValue(column, operator) : actions.filter(column, operator))
          };
        }),
        {kind: 'action', label: 'Clear filter', disabled: !filter, onSelect: () => actions.clearFilter(column)}
      ];
  // Offered whether or not the query can address the column: a column the SQL does not have
  // still sizes, hides and pins like any other.
  const items: MenuItem[] = [
    ...queryItems,
    {kind: 'separator'},
    {kind: 'action', label: 'Hide column', disabledReason: hideRefusal ?? undefined, onSelect: () => onHide(column)}
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
      className="absolute right-3 top-1">
      <Menu
        ariaLabel={`Column options: ${column}`}
        align={placement.align}
        maxHeight={placement.maxHeight}
        trigger={({open, toggle, ref, menuId}) => (
          <button
            ref={ref}
            type="button"
            {...{[COLUMN_MENU_TRIGGER_ATTRIBUTE]: column}}
            aria-label={name}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            onClick={(event) => {
              // Placed when it opens, inside the grid's scroll box, which would clip it otherwise.
              const box = event.currentTarget.closest(`[${GRID_SCROLL_BOX_ATTRIBUTE}]`);
              const button = event.currentTarget.getBoundingClientRect();
              setPlacement({
                align: menuAlignFor(button.left, contentRightOf(box)),
                maxHeight: menuMaxHeightFor(button.bottom, contentBottomOf(box))
              });
              toggle();
            }}
            className={cx(
              'flex h-[24px] min-w-[24px] items-center justify-center gap-0.5 rounded px-1 text-[11px] text-text-3 hover:bg-surface hover:text-text',
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
    </div>
  );
}
