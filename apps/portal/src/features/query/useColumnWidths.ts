import {useCallback, useState} from 'react';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './query.constants';

export type UseColumnWidthsResult = {
  widths: number[]; // px per data column; default DEFAULT_COLUMN_WIDTH
  setWidth: (index: number, px: number) => void; // clamped to >= MIN_COLUMN_WIDTH
  resetColumn: (index: number) => void; // back to DEFAULT_COLUMN_WIDTH
};

function defaults(columnCount: number): number[] {
  return Array.from({length: columnCount}, () => DEFAULT_COLUMN_WIDTH);
}

// SPEC-064: in-memory per-column widths for the *current* result (FR-002/003).
// Resets to defaults whenever resetKey (the query execution id) OR the column
// count changes — done as a render-phase reset tracking the previous key+count,
// mirroring useQueryResults's pageIndex reset (no effect, no extra render). Keyed
// by column index, not name: a SELECT can return duplicate/blank column names, so
// index is the stable identity within a single result.
export function useColumnWidths(resetKey: string | null, columnCount: number): UseColumnWidthsResult {
  const [widths, setWidths] = useState<number[]>(() => defaults(columnCount));
  const [prevKey, setPrevKey] = useState(resetKey);
  const [prevCount, setPrevCount] = useState(columnCount);

  if (resetKey !== prevKey || columnCount !== prevCount) {
    setPrevKey(resetKey);
    setPrevCount(columnCount);
    setWidths(defaults(columnCount));
  }

  const setWidth = useCallback((index: number, px: number) => {
    setWidths((prev) => {
      if (index < 0 || index >= prev.length) return prev;
      const next = [...prev];
      next[index] = Math.max(MIN_COLUMN_WIDTH, Math.round(px));
      return next;
    });
  }, []);

  const resetColumn = useCallback((index: number) => {
    setWidths((prev) => {
      if (index < 0 || index >= prev.length) return prev;
      const next = [...prev];
      next[index] = DEFAULT_COLUMN_WIDTH;
      return next;
    });
  }, []);

  return {widths, setWidth, resetColumn};
}
