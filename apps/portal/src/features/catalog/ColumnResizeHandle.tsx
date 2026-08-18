import {useCallback} from 'react';
import {COLUMN_RESIZE_STEP_PX, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './catalog.constants';

type ColumnResizeHandleProps<K extends string | number> = {
  /** Whatever identifies the column to the caller — an index in one surface, a name in another. */
  column: K;
  columnName: string;
  /** Current width of the column this handle resizes. */
  width: number;
  /** Sets the column width in px (caller clamps to the minimum). */
  onResize: (column: K, px: number) => void;
  /** Resets the column to the default width (double-click). */
  onReset: (column: K) => void;
};

/**
 * Focusable separator on a data-column header's right edge. Pointer drag
 * resizes live (clamping lives in the caller); double-click resets to the
 * default; Arrow Left/Right nudge by COLUMN_RESIZE_STEP_PX. role="separator" +
 * aria-orientation="vertical" + a column-naming aria-label keep it accessible.
 *
 * Lives in `features/catalog/` because two sibling features draw
 * result grids and neither may import the other. The column identifier is
 * generic for the same reason: the Query workspace keys widths by index (a
 * SELECT may return duplicate names), the Data Explorer by name (its geometry
 * persists across executions, so a position is not an identity).
 */
export function ColumnResizeHandle<K extends string | number>({
  column,
  columnName,
  width,
  onResize,
  onReset
}: ColumnResizeHandleProps<K>) {
  // The drag's window listeners are self-contained in the closure below so the
  // move handler always sees the gesture origin (not a stale prop between
  // events) and the up handler can unbind both without a forward-reference.
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault(); // don't start a text selection / steal header focus
      const startX = e.clientX;
      const startWidth = width;

      const onMove = (move: PointerEvent) => {
        onResize(column, startWidth + (move.clientX - startX));
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    },
    [column, width, onResize]
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      e.preventDefault();
      // The Data Explorer's grid listens for Arrow keys on an ANCESTOR of this handle, so
      // an un-stopped event resized the column AND moved the cell cursor, taking focus off
      // the handle with it — the second press then resized nothing (found in review).
      e.stopPropagation();
      onResize(column, width + (e.key === 'ArrowRight' ? COLUMN_RESIZE_STEP_PX : -COLUMN_RESIZE_STEP_PX));
    },
    [column, width, onResize]
  );

  return (
    <span
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={`Resize column ${columnName}`}
      // A FOCUSABLE separator is a widget, not a divider, so ARIA requires a value —
      // caught by axe once a grid with these handles was driven into a live state
      // (SPEC-180). The pixel width is the value the Arrow keys move.
      aria-valuenow={Math.round(width)}
      aria-valuemin={MIN_COLUMN_WIDTH}
      aria-valuemax={MAX_COLUMN_WIDTH}
      aria-valuetext={`${Math.round(width)} pixels`}
      onPointerDown={onPointerDown}
      onDoubleClick={() => onReset(column)}
      onKeyDown={onKeyDown}
      className="group/handle absolute right-0 top-0 z-10 flex h-full w-3 cursor-col-resize touch-none select-none items-stretch justify-end focus:outline-none">
      {/* A divider that's visible at rest (so users see the column edge is
          grabbable) and thickens to the accent color on hover/focus. */}
      <span
        aria-hidden="true"
        className="h-full w-0.5 rounded-full bg-border transition-all group-hover/handle:w-1 group-hover/handle:bg-accent group-focus/handle:w-1 group-focus/handle:bg-accent"
      />
    </span>
  );
}
