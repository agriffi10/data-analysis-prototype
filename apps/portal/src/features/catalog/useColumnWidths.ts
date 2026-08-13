import {useCallback, useState} from 'react';
import {DEFAULT_COLUMN_WIDTH, MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './catalog.constants';

export type UseColumnWidthsResult = {
  /** Px per data column for the current execution; defaults to DEFAULT_COLUMN_WIDTH. */
  widths: number[];
  /** Sets a column's width, clamped to >= MIN_COLUMN_WIDTH. */
  setWidth: (index: number, px: number) => void;
  /** Resets a column back to DEFAULT_COLUMN_WIDTH. */
  resetColumn: (index: number) => void;
};

function defaults(columnCount: number): number[] {
  return Array.from({length: columnCount}, () => DEFAULT_COLUMN_WIDTH);
}

/**
 * Per-result column widths, keyed by query execution id so a user's resizes
 * survive both Prev/Next paging and query-tab switches within the session. A
 * new query is a new execution id, so its columns start from defaults; a
 * column-count mismatch under the same id also re-defaults (defensive).
 * Widths are keyed by column index since a SELECT can return duplicate/blank
 * names. In-memory only — a reload or leaving the route clears it.
 *
 * Must be called ABOVE the QueryResultsTable mount boundary (the table
 * unmounts when the active tab has no results yet): call it in
 * QueryWorkspace and pass the outputs down.
 */
export function useColumnWidths(executionId: string | null, columnCount: number): UseColumnWidthsResult {
  // execution id -> px per data column. Entries are tiny, so never pruned.
  const [byExec, setByExec] = useState<Record<string, number[]>>({});

  // Lazily seed (or re-seed on a column-count change) the current execution's
  // widths during render — React's "adjust state when a prop changes" pattern,
  // no effect / extra paint. Bails out once the entry matches columnCount.
  const stored = executionId !== null ? byExec[executionId] : undefined;
  if (executionId !== null && (stored === undefined || stored.length !== columnCount)) {
    setByExec((prev) => ({...prev, [executionId]: defaults(columnCount)}));
  }

  const widths = (executionId !== null ? byExec[executionId] : undefined) ?? defaults(columnCount);

  const setWidth = useCallback(
    (index: number, px: number) => {
      if (executionId === null) return;
      setByExec((prev) => {
        const cur = prev[executionId] ?? defaults(columnCount);
        if (index < 0 || index >= cur.length) return prev;
        const next = [...cur];
        next[index] = Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, Math.round(px)));
        return {...prev, [executionId]: next};
      });
    },
    [executionId, columnCount]
  );

  const resetColumn = useCallback(
    (index: number) => {
      if (executionId === null) return;
      setByExec((prev) => {
        const cur = prev[executionId] ?? defaults(columnCount);
        if (index < 0 || index >= cur.length) return prev;
        const next = [...cur];
        next[index] = DEFAULT_COLUMN_WIDTH;
        return {...prev, [executionId]: next};
      });
    },
    [executionId, columnCount]
  );

  return {widths, setWidth, resetColumn};
}
