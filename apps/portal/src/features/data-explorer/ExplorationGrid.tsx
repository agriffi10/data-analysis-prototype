import {useMemo, type RefObject} from 'react';
import {cx} from '../../lib/cx';
import {CellValue} from './CellValue';
import {cellText} from './cellText';
import {ROW_NUMBER_COLUMN_WIDTH} from './dataExplorer.constants';
import {ExplorationGridHeader} from './ExplorationGridHeader';
import type {ColumnQueryActions} from './ColumnFilterMenu';
import type {FilterOperator} from './dataExplorer.types';
import type {GridColumn, UseColumnGeometryResult} from './useColumnGeometry';
import {CURSOR_CELL_ATTRIBUTE} from './useCellSelection';
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
  /** Ordering and filtering, for each column header's menu (SPEC-181). */
  actions: ColumnQueryActions;
  /** A comparison was chosen and needs a value; the REGION raises the dialog, not the header. */
  onRequestFilterValue: (column: string, operator: FilterOperator) => void;
  /** A header drag started (the column) or ended (null) — for drop targets outside the grid. */
  onColumnDrag?: (name: string | null) => void;
  /** The grid element, shared with `useCellSelection` so focus can find the cursor cell. */
  gridRef: RefObject<HTMLTableElement | null>;
};

/**
 * The results grid (SPEC-180), replacing SPEC-179's placeholder table.
 *
 * A cell is addressed by its column's NAME and its row's position on the page, so the
 * display order the geometry resolves is free to differ from the execution's — every cell
 * reads `row[column.index]` rather than assuming the two agree.
 *
 * `role="grid"` is explicit on the table and on its cells: SPEC-180's cursor makes this a
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
  onRequestFilterValue,
  onColumnDrag,
  gridRef
}: ExplorationGridProps) {
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
    <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-surface">
      <table
        ref={gridRef}
        role="grid"
        aria-label="Results"
        aria-multiselectable="true"
        onKeyDown={selection.onKeyDown}
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
                className="sticky left-0 z-10 cursor-pointer truncate border-b border-border-2 bg-surface px-3 text-left text-xs font-normal text-text-3 group-last:border-0 group-hover:bg-surface-2">
                {rangeStart + rowIndex}
              </th>
              {columns.map((column, position) => {
                const selected = selection.isSelected(rowIndex, column.name);
                const cursor = selection.isCursor(rowIndex, column.name);
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
                    style={column.pinned ? {left: offsets[position]} : undefined}
                    className={cx(
                      'truncate border-b border-border-2 px-3 group-last:border-0 focus:outline-none',
                      column.pinned && 'sticky z-10 bg-surface group-hover:bg-surface-2',
                      selected && 'bg-accent-soft',
                      cursor && 'ring-2 ring-inset ring-accent'
                    )}
                    title={cellText(row[column.index] ?? null)}>
                    <CellValue value={row[column.index] ?? null} />
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
