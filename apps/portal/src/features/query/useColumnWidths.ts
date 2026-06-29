import {useCallback, useState} from 'react';
import {DEFAULT_COLUMN_WIDTH, MIN_COLUMN_WIDTH} from './query.constants';

export type UseColumnWidthsResult = {
  widths: number[]; // px per data column for the current execution; default DEFAULT_COLUMN_WIDTH
  setWidth: (index: number, px: number) => void; // clamped to >= MIN_COLUMN_WIDTH
  resetColumn: (index: number) => void; // back to DEFAULT_COLUMN_WIDTH
};

function defaults(columnCount: number): number[] {
  return Array.from({length: columnCount}, () => DEFAULT_COLUMN_WIDTH);
}

// SPEC-064: per-result column widths, keyed by query execution id so a user's
// resizes survive BOTH Prev/Next paging AND query-tab switches within the session
// — returning to a still-cached result keeps its widths. A new query is always a
// new execution id, so its columns start from defaults (FR-003). A result whose
// column count differs from a prior entry under the same id also re-defaults
// (defensive); widths are keyed by column index since a SELECT can return
// duplicate/blank names. In-memory for the workspace's lifetime — a reload or
// leaving the route clears it (still out of scope, per spec).
//
// This hook must live ABOVE the QueryResultsTable mount boundary (the table
// unmounts when the active tab has no results yet), so it is called in
// QueryWorkspace and its outputs are passed down.
export function useColumnWidths(executionId: string | null, columnCount: number): UseColumnWidthsResult {
  // execution id -> px per data column. Grows by one entry per executed query for
  // the session; entries are tiny (a handful of numbers) so we don't prune them.
  const [byExec, setByExec] = useState<Record<string, number[]>>({});

  // Lazily seed (or re-seed on a column-count change) the current execution's
  // widths during render — React's "adjust state when a prop changes" pattern, no
  // effect / extra paint. Bails out once the entry already matches columnCount.
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
        next[index] = Math.max(MIN_COLUMN_WIDTH, Math.round(px));
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
