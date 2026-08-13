import {useRef} from 'react';
import {ColumnResizeHandle} from '../catalog/ColumnResizeHandle';
import {cx} from '../../lib/cx';
import {ROW_NUMBER_COLUMN_WIDTH} from './dataExplorer.constants';
import type {GridColumn} from './useColumnGeometry';

export type ExplorationGridHeaderProps = {
  /** Visible columns in display order — the pinned block first. */
  columns: GridColumn[];
  /** Left offset in px per visible column, for the sticky pinned block. */
  offsets: number[];
  onResize: (name: string, px: number) => void;
  onResetWidth: (name: string) => void;
  /** Drag-drop reorder: `name` takes `target`'s place. */
  onDropColumn: (name: string, target: string) => void;
  /** Clicking the header selects the whole column (FR-002 AC3). */
  onSelectColumn: (name: string) => void;
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
 * A column header is NOT a button here: SPEC-181 gives it a menu and SPEC-180's own
 * selection model gives clicking it a meaning, so it stays a `columnheader` with controls
 * inside it rather than becoming one control.
 */
export function ExplorationGridHeader({
  columns,
  offsets,
  onResize,
  onResetWidth,
  onDropColumn,
  onSelectColumn
}: ExplorationGridHeaderProps) {
  const dragging = useRef<string | null>(null);

  return (
    <thead>
      <tr className="h-11">
        <th
          scope="col"
          style={{width: ROW_NUMBER_COLUMN_WIDTH}}
          className="sticky left-0 top-0 z-30 border-b border-border bg-surface-2 px-3 text-xs font-semibold uppercase tracking-wide text-text-3">
          #
        </th>
        {columns.map((column, position) => (
          <th
            key={column.name}
            scope="col"
            aria-label={column.name}
            style={column.pinned ? {left: offsets[position]} : undefined}
            className={cx(
              'relative top-0 border-b border-border bg-surface-2 px-3 text-left text-xs font-semibold uppercase tracking-wide text-text-3',
              column.pinned ? 'sticky z-30' : 'z-20'
            )}
            // The resize handle lives INSIDE the header, so a drag of its edge would
            // otherwise finish as a click that selects the column the user was sizing.
            onClick={(e) => {
              if (!(e.target as HTMLElement).closest('[role="separator"]')) onSelectColumn(column.name);
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
                e.dataTransfer?.setData('text/plain', column.name);
              }}
              onDragEnd={() => {
                dragging.current = null;
              }}
              className="block cursor-grab truncate active:cursor-grabbing"
              title={column.name}>
              {column.name}
            </span>
            <span
              className="block truncate font-mono text-[10px] normal-case tracking-normal text-text-3"
              title={column.type}>
              {column.type}
            </span>
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
