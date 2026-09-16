import {useEffect, useMemo, useRef, type RefObject} from 'react';
import {cx} from '../../lib/cx';
import {CellValue} from './CellValue';
import {cellText} from './cellText';
import {ROW_NUMBER_COLUMN_WIDTH} from './dataExplorer.constants';
import {ExplorationGridHeader} from './ExplorationGridHeader';
import {COLUMN_MENU_TRIGGER_ATTRIBUTE, type ColumnQueryActions} from './ColumnFilterMenu';
import type {FilterOperator} from './dataExplorer.types';
import type {GridColumn, UseColumnGeometryResult} from './useColumnGeometry';
import type {PageFormatting} from './formatting';
import {CURSOR_CELL_ATTRIBUTE} from './useCellSelection';
import {GRID_SCROLL_BOX_ATTRIBUTE} from './menuAlign';
import type {UseCellSelectionResult} from './useCellSelection';

export type ExplorationGridProps = {
  /** Visible columns in display order. */
  columns: GridColumn[];
  /** The current page's rows, in the EXECUTION's column order — indexed by `column.index`. */
  rows: (string | null)[][];
  /** 1-based row number of the first row on this page. */
  rangeStart: number;
  geometry: UseColumnGeometryResult;
  selection: UseCellSelectionResult;
  /** Ordering and filtering, for each column header's menu. */
  actions: ColumnQueryActions;
  /** Resolved colours and bands for this page. Costs nothing and changes no rows. */
  formatting: PageFormatting;
  /** A comparison was chosen and needs a value; the REGION raises the dialog, not the header. */
  onRequestFilterValue: (column: string, operator: FilterOperator) => void;
  /** A header drag started (the column) or ended (null) — for drop targets outside the grid. */
  onColumnDrag?: (name: string | null) => void;
  /**
   * Ctrl/Cmd+C over the grid.
   *
   * Handled here rather than inside `useCellSelection` because copying is not a selection
   * gesture: the hook answers what is selected, and the region owns what a selection is
   * worth doing with. The grid intercepts the chord before the hook sees it — Ctrl/Cmd+A is
   * the hook's, and the two must not fall through to each other.
   */
  onCopy?: () => void;
  /** The grid element, shared with `useCellSelection` so focus can find the cursor cell. */
  gridRef: RefObject<HTMLTableElement | null>;
};

/**
 * The results grid, replacing the placeholder table.
 *
 * A cell is addressed by its column's NAME and its row's position on the page, so the
 * display order the geometry resolves is free to differ from the execution's — every cell
 * reads `row[column.index]` rather than assuming the two agree.
 *
 * `role="grid"` is explicit on the table and on its cells: The cursor makes this a
 * composite widget rather than a static table, and the roles have to be in place before
 * the selection model lands on them.
 */
export function ExplorationGrid({
  columns,
  rows,
  rangeStart,
  geometry,
  selection,
  actions,
  formatting,
  onRequestFilterValue,
  onColumnDrag,
  onCopy,
  gridRef
}: ExplorationGridProps) {
  // Hiding a column from its own menu unmounts the button focus was just returned to, which
  // would leave it on the page body; the neighbour's menu button takes it instead.
  const refocusColumn = useRef<string | null>(null);
  const hideColumn = (name: string) => {
    const at = columns.findIndex((column) => column.name === name);
    refocusColumn.current = (columns[at + 1] ?? columns[at - 1])?.name ?? null;
    geometry.toggleHidden(name);
  };
  // Keyed on the columns, so it runs after the commit that removed the hidden one.
  useEffect(() => {
    const target = refocusColumn.current;
    if (target === null) return;
    refocusColumn.current = null;
    const triggers = gridRef.current?.querySelectorAll<HTMLElement>(`[${COLUMN_MENU_TRIGGER_ATTRIBUTE}]`) ?? [];
    Array.from(triggers)
      .find((trigger) => trigger.getAttribute(COLUMN_MENU_TRIGGER_ATTRIBUTE) === target)
      ?.focus();
  }, [columns, gridRef]);

  // Sticky offsets for the pinned block: each pinned column sits after the row-number
  // column and every pinned column before it. Computed from widths rather than measured,
  // because the widths ARE the layout here (`table-fixed` + an explicit `<colgroup>`).
  const offsets = useMemo(
    () =>
      columns.map((column, position) =>
        column.pinned
          ? columns
              .slice(0, position)
              .reduce((left, before) => (before.pinned ? left + before.width : left), ROW_NUMBER_COLUMN_WIDTH)
          : 0
      ),
    [columns]
  );

  return (
    <div
      {...{[GRID_SCROLL_BOX_ATTRIBUTE]: 'true'}}
      className="max-h-[70dvh] min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-surface [scrollbar-gutter:stable] tablet:max-h-none">
      <table
        ref={gridRef}
        role="grid"
        aria-label="Results"
        aria-multiselectable="true"
        onKeyDown={(event) => {
          // The browser's own copy would take the DOM selection, which in a grid of
          // truncated cells is whatever text happens to be highlighted — not the cells the
          // user selected. `preventDefault` is what makes the rendered copy the one that
          // reaches the clipboard.
          // `toLowerCase`, as `useCellSelection`'s own Ctrl/Cmd+A does: with Caps Lock on the
          // key is `'C'`, the branch would miss, and the browser's copy would take whatever
          // DOM text happened to be highlighted in the truncated cells — the exact outcome
          // this intercept exists to prevent.
          if (
            onCopy &&
            (event.metaKey || event.ctrlKey) &&
            !event.shiftKey &&
            !event.altKey &&
            event.key.toLowerCase() === 'c'
          ) {
            event.preventDefault();
            onCopy();
            return;
          }
          selection.onKeyDown(event);
        }}
        className="w-full table-fixed border-separate border-spacing-0 text-left">
        <colgroup>
          <col style={{width: ROW_NUMBER_COLUMN_WIDTH}} />
          {columns.map((column) => (
            <col
              key={column.name}
              style={{width: column.width}}
            />
          ))}
        </colgroup>
        <ExplorationGridHeader
          columns={columns}
          offsets={offsets}
          onResize={geometry.setWidth}
          onResetWidth={geometry.resetWidth}
          onDropColumn={geometry.moveTo}
          onColumnDrag={onColumnDrag}
          onSelectColumn={selection.selectColumn}
          actions={actions}
          onRequestFilterValue={onRequestFilterValue}
          onHideColumn={hideColumn}
          hideRefusal={geometry.hideRefusal}
        />
        {/* Array-index keys: result rows are plain strings with no identity, and the whole
            body is replaced on every page and every execution. */}
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr
              key={rowIndex}
              className="group h-10 font-mono text-sm hover:bg-surface-2">
              <th
                scope="row"
                onClick={() => selection.selectRow(rowIndex)}
                className={cx(
                  'sticky left-0 z-10 cursor-pointer truncate border-b border-border-2 bg-surface px-3 text-left text-xs font-normal text-text-3 group-last:border-0 group-hover:bg-surface-2',
                  // The band's own tint is faint by design (it is the hover shade), so the
                  // BOUNDARY carries a rule as well — colour is never the only thing marking
                  // it. Suppressed on the first row, where it would only double the header's
                  // own border.
                  rowIndex > 0 && formatting.bandStarts[rowIndex] && 'border-t-2 border-t-border'
                )}>
                {rangeStart + rowIndex}
              </th>
              {columns.map((column, position) => {
                const selected = selection.isSelected(rowIndex, column.name);
                const cursor = selection.isCursor(rowIndex, column.name);
                const format = formatting.formats[rowIndex]?.[column.name];
                return (
                  <td
                    key={column.name}
                    // Explicit, though a `td` inside `role="grid"` maps to `gridcell`
                    // anyway: the mapping is one HTML-AAM lookup deep and several
                    // accessibility APIs (and the test renderer) resolve `td` statically
                    // as `cell`, which is a different role with no selected state.
                    role="gridcell"
                    // The grid is a SINGLE tab stop: only the cursor cell is tabbable and
                    // the Arrow keys move within, which is what `role="grid"` promises —
                    // a hundred cells in the tab order is not a grid, it is a maze.
                    tabIndex={cursor ? 0 : -1}
                    {...{[CURSOR_CELL_ATTRIBUTE]: cursor ? 'true' : undefined}}
                    aria-selected={selected}
                    onMouseDown={(e) =>
                      selection.selectCell(
                        {row: rowIndex, column: column.name},
                        {shiftKey: e.shiftKey, metaKey: e.metaKey, ctrlKey: e.ctrlKey}
                      )
                    }
                    style={{
                      ...(column.pinned ? {left: offsets[position]} : {}),
                      color: format?.color,
                      // THE SELECTION WINS. An inline background beats the class that
                      // paints a selected cell, so a formatted grid would be one a user
                      // cannot see their own selection in — and the selection is what the
                      // Calc panel aggregates. `aria-selected` says so either way.
                      backgroundColor: selected ? undefined : format?.backgroundColor
                    }}
                    className={cx(
                      'truncate border-b border-border-2 px-3 group-last:border-0 focus:outline-none',
                      rowIndex > 0 && formatting.bandStarts[rowIndex] && 'border-t-2 border-t-border',
                      column.pinned && 'sticky z-10 bg-surface group-hover:bg-surface-2',
                      selected && 'bg-accent-soft',
                      cursor && 'ring-2 ring-inset ring-accent'
                    )}
                    title={cellText(row[column.index] ?? null)}>
                    <CellValue
                      value={row[column.index] ?? null}
                      transformed={formatting.transformed[rowIndex]?.[column.name]}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
