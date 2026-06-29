import {useCallback} from 'react';
import {COLUMN_RESIZE_STEP_PX} from './query.constants';

type ColumnResizeHandleProps = {
  columnIndex: number;
  columnName: string;
  width: number; // current width of the column this handle resizes
  onResize: (index: number, px: number) => void; // setWidth (clamps at MIN)
  onReset: (index: number) => void; // resetColumn (double-click)
};

// SPEC-064 FR-001/FR-006: a focusable separator on a data-column header's right
// edge. Pointer drag resizes live (clamp lives in setWidth); double-click resets
// to the default; Arrow Left/Right nudge by COLUMN_RESIZE_STEP_PX. role="separator"
// + aria-orientation="vertical" + a column-naming aria-label keep it accessible.
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
      className="group/handle absolute right-0 top-0 z-10 flex h-full w-2 cursor-col-resize touch-none select-none items-stretch justify-center focus:outline-none">
      {/* The visible 1px rule; tints to accent when the handle is hovered/focused. */}
      <span
        aria-hidden="true"
        className="h-full w-px bg-transparent transition-colors group-hover/handle:bg-accent group-focus/handle:w-0.5 group-focus/handle:bg-accent"
      />
    </span>
  );
}
