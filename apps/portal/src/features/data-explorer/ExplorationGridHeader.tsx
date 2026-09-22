import {useRef} from 'react';
import {ColumnResizeHandle} from '../catalog/ColumnResizeHandle';
import {cx} from '../../lib/cx';
import {ROW_NUMBER_COLUMN_WIDTH} from './dataExplorer.constants';
import {ColumnFilterMenu, type ColumnQueryActions} from './ColumnFilterMenu';
import type {FilterOperator} from './dataExplorer.types';
import type {GridColumn} from './useColumnGeometry';
import {SECTION_CAPTION} from '../../components/fieldStyles';

export type ExplorationGridHeaderProps = {
  /** Visible columns in display order — the pinned block first. */
  columns: GridColumn[];
  /** Left offset in px per visible column, for the sticky pinned block. */
  offsets: number[];
  onResize: (name: string, px: number) => void;
  onResetWidth: (name: string) => void;
  /** Drag-drop reorder: `name` takes `target`'s place. */
  onDropColumn: (name: string, target: string) => void;
  /**
   * The column a drag is carrying, or null when it ends — for drop targets OUTSIDE the
   * header (the Grouping panel).
   *
   * A callback rather than the panel reading `dataTransfer`, for the reason the local ref
   * below already exists: `DataTransfer` is not implemented everywhere, and a drop handler
   * that depends on it works in a browser and nowhere else.
   */
  onColumnDrag?: (name: string | null) => void;
  /** Clicking the header selects the whole column. */
  onSelectColumn: (name: string) => void;
  /** Ordering and filtering, for each column's own menu. */
  actions: ColumnQueryActions;
  /** A comparison needs a value; the region raises the dialog (`Modal` does not portal). */
  onRequestFilterValue: (column: string, operator: FilterOperator) => void;
  /** Hides a column from its own menu. */
  onHideColumn: (name: string) => void;
  /** Why a column cannot be hidden, or null when it can. */
  hideRefusal: (name: string) => string | null;
};

/**
 * The grid's header row: a name, a type, a resize handle and a drag grip per column.
 *
 * The dragged column is held in a ref rather than read back out of `dataTransfer`, because
 * the drop handler needs it in environments where `DataTransfer` is not implemented — and
 * because the grip is the only thing on this page that starts a drag, so there is no other
 * payload it could be confused with. `dataTransfer` is still populated where it exists, so
 * the browser draws its own drag image.
 *
 * A column header is NOT a button: it carries the menu and the own
 * selection model gives clicking it a meaning, so it stays a `columnheader` with controls
 * inside it rather than becoming one control.
 */
export function ExplorationGridHeader({
  columns,
  offsets,
  onResize,
  onResetWidth,
  onDropColumn,
  onColumnDrag,
  onSelectColumn,
  actions,
  onRequestFilterValue,
  onHideColumn,
  hideRefusal
}: ExplorationGridHeaderProps) {
  const dragging = useRef<string | null>(null);

  return (
    <thead>
      <tr className="h-11">
        <th
          scope="col"
          style={{width: ROW_NUMBER_COLUMN_WIDTH}}
          className={`sticky left-0 top-0 z-30 border-b border-border bg-surface-2 px-3 ${SECTION_CAPTION}`}>
          #
        </th>
        {columns.map((column, position) => (
          <th
            key={column.name}
            scope="col"
            aria-label={column.name}
            style={column.pinned ? {left: offsets[position]} : undefined}
            // Sticky whether pinned or not, so the names stay above the rows they label while the
            // grid scrolls. The right padding clears the 24px resize handle and the menu button
            // beside it: 24px bare, 44px with a one-digit sort position and a filter mark.
            className={cx(
              `sticky top-0 border-b border-border bg-surface-2 py-1 pl-3 text-left ${SECTION_CAPTION}`,
              column.pinned ? 'z-30' : 'z-20',
              actions.sortOf(column.name) || actions.filterOf(column.name) ? 'pr-[74px]' : 'pr-[54px]'
            )}
            // The resize handle and the menu live INSIDE the header, so a drag of the edge
            // — or a click anywhere in the menu — would otherwise finish as a click that
            // selects the column the user was sizing or filtering.
            onClick={(e) => {
              const target = e.target as HTMLElement;
              if (!target.closest('[role="separator"]') && !target.closest('[data-column-menu]')) {
                onSelectColumn(column.name);
              }
            }}
            onDragOver={(e) => {
              if (dragging.current && dragging.current !== column.name) e.preventDefault();
            }}
            onDrop={(e) => {
              e.preventDefault();
              const dragged = dragging.current;
              dragging.current = null;
              if (dragged) onDropColumn(dragged, column.name);
            }}>
            <span
              draggable
              role="presentation"
              onDragStart={(e) => {
                dragging.current = column.name;
                onColumnDrag?.(column.name);
                e.dataTransfer?.setData('text/plain', column.name);
              }}
              onDragEnd={() => {
                dragging.current = null;
                onColumnDrag?.(null);
              }}
              // A column name is the user's data — shown as they spelled it. The borrowed
              // caption style is uppercase, which suits a fixed label and misrepresents this.
              className="block cursor-grab truncate normal-case tracking-normal active:cursor-grabbing"
              title={column.name}>
              {column.name}
            </span>
            <span
              className="block truncate font-mono text-[10px] normal-case tracking-normal text-text-3"
              title={column.type}>
              {column.type}
            </span>
            <ColumnFilterMenu
              column={column.name}
              actions={actions}
              onRequestValue={onRequestFilterValue}
              onHide={onHideColumn}
              hideRefusal={hideRefusal(column.name)}
            />
            <ColumnResizeHandle
              column={column.name}
              columnName={column.name}
              width={column.width}
              onResize={onResize}
              onReset={onResetWidth}
            />
          </th>
        ))}
      </tr>
    </thead>
  );
}
