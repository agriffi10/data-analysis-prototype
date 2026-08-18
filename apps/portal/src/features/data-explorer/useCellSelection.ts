import {useCallback, useEffect, useMemo, useRef, useState, type RefObject} from 'react';
import type {CellRange, CellRef, CellSelection} from './dataExplorer.types';

export type UseCellSelectionResult = {
  selection: CellSelection;
  /** True when the cell is inside any selected range. */
  isSelected: (row: number, column: string) => boolean;
  /** True for the one cell that carries DOM focus and `tabIndex={0}`. */
  isCursor: (row: number, column: string) => boolean;
  /** How many cells are selected — always over the LOADED page, never the whole result. */
  selectedCount: number;
  /** Pointer selection. Shift extends, Ctrl/Cmd toggles a discontiguous cell. */
  selectCell: (cell: CellRef, modifiers: {shiftKey?: boolean; metaKey?: boolean; ctrlKey?: boolean}) => void;
  /** Whole-column selection from a header click. */
  selectColumn: (column: string) => void;
  /** Whole-row selection from a row-number click. */
  selectRow: (row: number) => void;
  /** The grid's key handler: cursor movement, extension, Ctrl/Cmd+A and the Space selectors. */
  onKeyDown: (event: React.KeyboardEvent) => void;
};

/** Marks the cursor cell in the DOM, so focus can find it without a per-cell ref. */
export const CURSOR_CELL_ATTRIBUTE = 'data-cursor';

function sameCell(a: CellRef, b: CellRef): boolean {
  return a.row === b.row && a.column === b.column;
}

function clamp(value: number, max: number): number {
  return Math.min(Math.max(value, 0), Math.max(max, 0));
}

/**
 * The grid's cell cursor and rectangular selection.
 *
 * The substrate the Calc panel aggregates over and the copy reads, so the
 * model is deliberately explicit rather than emergent: `ranges` is a list of inclusive
 * rectangles in selection order, and **the last one is always the live one** — its `from`
 * is the anchor a Shift gesture extends from and its `to` is the cursor. A discontiguous
 * Ctrl/Cmd+click appends a new single-cell rectangle, which then becomes the live one.
 *
 * Everything is addressed by (row within the CURRENT PAGE, column name). Coordinates are
 * therefore meaningless across a page change, which is why paging resets rather than
 * carrying them onto different rows — and why Ctrl/Cmd+A can only ever mean "this
 * page", a claim the caller has to make out loud.
 *
 * @param rowCount - Rows on the loaded page.
 * @param columns - Visible column names, in display order.
 * @param resetKey - Changes whenever the page or the column set does; resets the selection.
 * @param grid - The grid element, so DOM focus can be moved to the cursor cell inside it.
 * @returns The selection, the predicates the cells render from, and the gestures.
 */
export function useCellSelection(
  rowCount: number,
  columns: string[],
  resetKey: string,
  grid: RefObject<HTMLElement | null>
): UseCellSelectionResult {
  const empty = useMemo((): CellSelection => ({cursor: {row: 0, column: columns[0] ?? ''}, ranges: []}), [columns]);
  const [stored, setSelection] = useState<CellSelection>(empty);

  // Focus follows the cursor by LOOKING THE CELL UP in the committed DOM, not by holding a
  // ref to the cell. A per-cell `ref` callback detaches the old cell and attaches the new
  // one in an order React does not promise, so the first keyboard move could read a ref
  // that had just been nulled — the cursor moved and DOM focus stayed behind, on exactly
  // the path a keyboard-only user takes (found in review).
  const pendingFocus = useRef(false);

  // Reset during render (React's "adjust state when a prop changes" pattern, as
  // `useColumnWidths` and `useQueryResults` do) rather than in an effect: an effect would
  // paint one frame of the OLD selection over the new page's rows, which is precisely the
  // stale-coordinates state AC8 forbids.
  const [previousKey, setPreviousKey] = useState(resetKey);
  if (previousKey !== resetKey) {
    setPreviousKey(resetKey);
    setSelection(empty);
  }
  const selection = previousKey === resetKey ? stored : empty;

  // Keyed on the selection, so it runs in the commit that rendered the new cursor cell —
  // and only when a gesture asked for focus, never when a page of results simply arrived.
  useEffect(() => {
    if (!pendingFocus.current) return;
    pendingFocus.current = false;
    grid.current?.querySelector<HTMLElement>(`[${CURSOR_CELL_ATTRIBUTE}="true"]`)?.focus();
  }, [grid, selection]);

  const columnIndex = useCallback((column: string) => columns.indexOf(column), [columns]);

  const isSelected = useCallback(
    (row: number, column: string): boolean => {
      const index = columnIndex(column);
      if (index === -1) return false;
      return selection.ranges.some((range) => {
        const from = columnIndex(range.from.column);
        const to = columnIndex(range.to.column);
        if (from === -1 || to === -1) return false;
        return (
          row >= Math.min(range.from.row, range.to.row) &&
          row <= Math.max(range.from.row, range.to.row) &&
          index >= Math.min(from, to) &&
          index <= Math.max(from, to)
        );
      });
    },
    [columnIndex, selection.ranges]
  );

  const isCursor = useCallback(
    (row: number, column: string) => sameCell(selection.cursor, {row, column}),
    [selection.cursor]
  );

  const selectedCount = useMemo(() => {
    // Counted over a set of coordinates, not summed per rectangle: overlapping ranges are
    // easy to make (Ctrl/Cmd+click inside an existing rectangle) and a sum would report
    // more cells than exist.
    const cells = new Set<string>();
    for (const range of selection.ranges) {
      const from = columnIndex(range.from.column);
      const to = columnIndex(range.to.column);
      if (from === -1 || to === -1) continue;
      for (let row = Math.min(range.from.row, range.to.row); row <= Math.max(range.from.row, range.to.row); row += 1) {
        for (let col = Math.min(from, to); col <= Math.max(from, to); col += 1) cells.add(`${row}:${col}`);
      }
    }
    return cells.size;
  }, [columnIndex, selection.ranges]);

  const moveCursor = useCallback((cell: CellRef, extend: boolean) => {
    pendingFocus.current = true;
    setSelection((s) => {
      if (!extend) return {cursor: cell, ranges: [{from: cell, to: cell}]};
      const live: CellRange = s.ranges[s.ranges.length - 1] ?? {from: s.cursor, to: s.cursor};
      return {cursor: cell, ranges: [...s.ranges.slice(0, -1), {from: live.from, to: cell}]};
    });
  }, []);

  const selectCell = useCallback<UseCellSelectionResult['selectCell']>(
    (cell, modifiers) => {
      if (modifiers.shiftKey) {
        moveCursor(cell, true);
        return;
      }
      if (modifiers.metaKey || modifiers.ctrlKey) {
        pendingFocus.current = true;
        setSelection((s) => {
          // Toggling OFF only removes a rectangle that is exactly this cell — a
          // Ctrl/Cmd+click inside a larger rectangle adds, because punching a hole in a
          // rectangle is not something this model can represent.
          const existing = s.ranges.findIndex((r) => sameCell(r.from, cell) && sameCell(r.to, cell));
          if (existing !== -1) {
            const ranges = s.ranges.filter((_, i) => i !== existing);
            return {cursor: cell, ranges};
          }
          return {cursor: cell, ranges: [...s.ranges, {from: cell, to: cell}]};
        });
        return;
      }
      moveCursor(cell, false);
    },
    [moveCursor]
  );

  const selectColumn = useCallback(
    (column: string) => {
      if (columnIndex(column) === -1 || rowCount === 0) return;
      pendingFocus.current = true;
      setSelection({
        cursor: {row: 0, column},
        ranges: [{from: {row: 0, column}, to: {row: rowCount - 1, column}}]
      });
    },
    [columnIndex, rowCount]
  );

  const selectRow = useCallback(
    (row: number) => {
      if (columns.length === 0) return;
      pendingFocus.current = true;
      const cell = {row, column: columns[0]};
      setSelection({cursor: cell, ranges: [{from: cell, to: {row, column: columns[columns.length - 1]}}]});
    },
    [columns]
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (rowCount === 0 || columns.length === 0) return;
      // The handler sits on the grid, and the grid contains other keyboard widgets — a
      // focusable resize separator per column. Without this, an Arrow that widened a
      // column ALSO moved the cell cursor and threw focus into the body, so the second
      // press resized nothing (found in review).
      if (!(event.target as HTMLElement).closest('[role="gridcell"]')) return;
      const {cursor} = selection;
      const col = Math.max(columnIndex(cursor.column), 0);
      const extend = event.shiftKey;
      const at = (row: number, column: number): CellRef => ({
        row: clamp(row, rowCount - 1),
        column: columns[clamp(column, columns.length - 1)]
      });

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        setSelection((s) => ({
          cursor: s.cursor,
          ranges: [{from: {row: 0, column: columns[0]}, to: {row: rowCount - 1, column: columns[columns.length - 1]}}]
        }));
        return;
      }

      // The keyboard half of "click a header selects the column, click a row number
      // selects the row" (the WAI-ARIA grid pattern's own bindings) — without them those
      // two gestures would be pointer-only.
      if (event.key === ' ' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        selectColumn(cursor.column);
        return;
      }
      if (event.key === ' ' && event.shiftKey) {
        event.preventDefault();
        selectRow(cursor.row);
        return;
      }

      switch (event.key) {
        case 'ArrowUp':
          event.preventDefault();
          moveCursor(at(cursor.row - 1, col), extend);
          return;
        case 'ArrowDown':
          event.preventDefault();
          moveCursor(at(cursor.row + 1, col), extend);
          return;
        case 'ArrowLeft':
          event.preventDefault();
          moveCursor(at(cursor.row, col - 1), extend);
          return;
        case 'ArrowRight':
          event.preventDefault();
          moveCursor(at(cursor.row, col + 1), extend);
          return;
        case 'Home':
          event.preventDefault();
          moveCursor(at(event.ctrlKey || event.metaKey ? 0 : cursor.row, 0), extend);
          return;
        case 'End':
          event.preventDefault();
          moveCursor(at(event.ctrlKey || event.metaKey ? rowCount - 1 : cursor.row, columns.length - 1), extend);
          return;
        // Page keys move within the LOADED page — there is no "next screen" to scroll to
        // that the pager has not already fetched, so they go to its first and last row.
        case 'PageUp':
          event.preventDefault();
          moveCursor(at(0, col), extend);
          return;
        case 'PageDown':
          event.preventDefault();
          moveCursor(at(rowCount - 1, col), extend);
          return;
        default:
      }
    },
    [columnIndex, columns, moveCursor, rowCount, selectColumn, selectRow, selection]
  );

  return {
    selection,
    isSelected,
    isCursor,
    selectedCount,
    selectCell,
    selectColumn,
    selectRow,
    onKeyDown
  };
}
