import {Button} from '../../components/Button';
import {CellValue} from './CellValue';
import type {GridColumn} from './useColumnGeometry';

export type ExplorationRecordViewProps = {
  /** Visible columns in display order — hidden ones are absent, as in the grid. */
  columns: GridColumn[];
  /** The current page's rows, in the EXECUTION's column order. */
  rows: (string | null)[][];
  /** Which row of the page is shown, 0-based. */
  rowIndex: number;
  /** 1-based row number of the first row on this page, for the label. */
  rangeStart: number;
  onRowIndexChange: (next: number) => void;
  /** Focuses a column, so the Value panel follows the record too. */
  onFocusColumn: (column: string) => void;
};

/**
 * One row, transposed: a line per column, name beside value (SPEC-180 FR-004).
 *
 * The natural way to read a wide row, and below `tablet` the natural way to read any row —
 * which is why FR-007 opens there rather than shipping a horizontally-scrolling grid onto
 * a 400px screen. Next/Previous walk the loaded page without going back to the grid; the
 * pager below still owns moving between pages.
 */
export function ExplorationRecordView({
  columns,
  rows,
  rowIndex,
  rangeStart,
  onRowIndexChange,
  onFocusColumn
}: ExplorationRecordViewProps) {
  // The stored index outlives the page it was taken on (a tab switch, a restore), so it is
  // clamped where it is READ rather than corrected where it is written — the row it named
  // may simply not exist on the page in view.
  const at = Math.min(Math.max(rowIndex, 0), Math.max(rows.length - 1, 0));
  const row = rows[at] ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex flex-none items-center gap-2">
        <Button
          size="sm"
          disabledReason={at === 0 ? 'This is the first row on this page.' : undefined}
          onClick={() => onRowIndexChange(at - 1)}>
          Previous row
        </Button>
        <Button
          size="sm"
          disabledReason={at >= rows.length - 1 ? 'This is the last row on this page.' : undefined}
          onClick={() => onRowIndexChange(at + 1)}>
          Next row
        </Button>
        <p
          role="status"
          className="text-xs text-text-3">
          Row {rangeStart + at}
        </p>
      </div>

      {/* The name lives on a `section` (a landmark with a name) rather than on the `dl`:
          a description list is not a named region to a screen reader, so a label there is
          announced by nothing. */}
      <section
        aria-label={`Row ${rangeStart + at}`}
        className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-surface">
        <dl>
          {columns.map((column) => (
            <div
              key={column.name}
              onClick={() => onFocusColumn(column.name)}
              className="flex gap-3 border-b border-border-2 px-3 py-2 text-sm last:border-b-0">
              <dt className="w-2/5 flex-none truncate text-text-3">
                {column.name}
                <span className="block truncate font-mono text-[10px] text-text-3">{column.type}</span>
              </dt>
              <dd className="min-w-0 flex-1 break-words font-mono text-text">
                <CellValue value={row[column.index] ?? null} />
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
