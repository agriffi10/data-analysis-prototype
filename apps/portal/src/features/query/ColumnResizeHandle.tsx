import {useCallback} from 'react';
import {COLUMN_RESIZE_STEP_PX} from './query.constants';

type ColumnResizeHandleProps = {
  columnIndex: number;
  columnName: string;
  /** Current width of the column this handle resizes. */
  width: number;
  /** Sets the column width in px (caller clamps to the minimum). */
  onResize: (index: number, px: number) => void;
  /** Resets the column to the default width (double-click). */
  onReset: (index: number) => void;
};

/**
 * Focusable separator on a data-column header's right edge. Pointer drag
 * resizes live (clamping lives in the caller); double-click resets to the
 * default; Arrow Left/Right nudge by COLUMN_RESIZE_STEP_PX. role="separator" +
 * aria-orientation="vertical" + a column-naming aria-label keep it accessible.
 */
export function ColumnResizeHandle({columnIndex, columnName, width, onResize, onReset}: ColumnResizeHandleProps) {
  // The drag's window listeners are self-contained in the closure below so the
  // move handler always sees the gesture origin (not a stale prop between
  // events) and the up handler can unbind both without a forward-reference.
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault(); // don't start a text selection / steal header focus
      const startX = e.clientX;
      const startWidth = width;

      const onMove = (move: PointerEvent) => {
        onResize(columnIndex, startWidth + (move.clientX - startX));
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    },
    [columnIndex, width, onResize]
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        onResize(columnIndex, width + COLUMN_RESIZE_STEP_PX);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        onResize(columnIndex, width - COLUMN_RESIZE_STEP_PX);
      }
    },
    [columnIndex, width, onResize]
  );

  return (
    <span
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={`Resize column ${columnName}`}
      onPointerDown={onPointerDown}
      onDoubleClick={() => onReset(columnIndex)}
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
