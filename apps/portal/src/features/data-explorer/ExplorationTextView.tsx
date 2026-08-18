import {useMemo} from 'react';
import {cellText} from './cellText';
import {TEXT_VIEW_MAX_COLUMN_CHARS} from './dataExplorer.constants';
import type {GridColumn} from './useColumnGeometry';

export type ExplorationTextViewProps = {
  /** Visible columns in display order — hidden ones are absent, as in the grid. */
  columns: GridColumn[];
  /** The current page's rows, in the EXECUTION's column order. */
  rows: (string | null)[][];
  /** 1-based inclusive row range of the page being rendered. */
  rangeStart: number;
  rangeEnd: number;
};

function pad(value: string, width: number): string {
  return value.length >= width ? value : value + ' '.repeat(width - value.length);
}

/**
 * The current page as fixed-width text — the shape people paste into a ticket.
 *
 * A single `<pre>` rather than a table, because the point is that a drag-select and a
 * copy produce exactly what is on screen, alignment included. Column widths are measured
 * from the page in view and capped, so one 4 KB JSON cell cannot push every other column
 * off the end of the line.
 *
 * It renders the LOADED page and says so: there is no honest way to render a result set
 * whose size Athena has not reported.
 */
export function ExplorationTextView({columns, rows, rangeStart, rangeEnd}: ExplorationTextViewProps) {
  const text = useMemo(() => {
    const widths = columns.map((column) =>
      Math.min(
        TEXT_VIEW_MAX_COLUMN_CHARS,
        rows.reduce((width, row) => Math.max(width, cellText(row[column.index] ?? null).length), column.name.length)
      )
    );
    const line = (cells: string[]) => cells.map((cell, i) => pad(cell.slice(0, widths[i]), widths[i])).join('  ');
    const header = line(columns.map((column) => column.name));
    const rule = widths.map((width) => '-'.repeat(width)).join('  ');
    const body = rows.map((row) => line(columns.map((column) => cellText(row[column.index] ?? null))));
    return [header, rule, ...body].join('\n');
  }, [columns, rows]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <p
        role="status"
        className="flex-none text-xs text-text-3">
        Rows {rangeStart}–{rangeEnd} of this page
      </p>
      <pre className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs text-text">
        {text}
      </pre>
    </div>
  );
}
