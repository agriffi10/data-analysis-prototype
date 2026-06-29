import {Pager} from '../../components/Pager';
import {ColumnResizeHandle} from './ColumnResizeHandle';
import {useColumnWidths} from './useColumnWidths';
import type {QueryColumn} from './query.types';

// The leading row-number (`#`) column is a fixed, non-resizable width (FR-001).
const ROW_NUMBER_COLUMN_WIDTH = 56; // px (matches the old w-14)

type QueryResultsTableProps = {
  columns: QueryColumn[];
  rows: string[][]; // current page only (≤ page size)
  pageIndex: number; // 0-based
  rangeStart: number; // 1-based row number of the first row on this page
  rangeEnd: number; // 1-based row number of the last row on this page
  totalRowCount: number | null; // known only once the last page is loaded
  hasPrev: boolean;
  hasNext: boolean;
  isFetchingNext: boolean;
  isLoading: boolean; // first page in flight
  queryExecutionId: string | null; // SPEC-064: width reset key (FR-002/003)
  onPrev: () => void;
  onNext: () => void;
};

// SPEC-035 FR-006 / SPEC-038 FR-002: results table reusing the file-table visual
// language (surface, border, rounded-lg, surface-2 uppercase header, monospace
// rows, hover). SPEC-064: columns are user-resizable — a <colgroup> of explicit
// widths drives table-layout:fixed, each data-column header carries a drag/keyboard
// resize handle, cells/headers truncate with an ellipsis (full text on hover via
// `title`), and the body scrolls horizontally for wide (20+ column) results.
// Widths persist across Prev/Next within one execution and reset on a new query
// (keyed by queryExecutionId). A successful DDL / zero-row SELECT renders the
// friendly empty state, not an error. Navigating REPLACES the visible rows
// (SPEC-038), unlike the file browser's append-style "Load more" (SPEC-037).
export function QueryResultsTable({
  columns,
  rows,
  pageIndex,
  rangeStart,
  rangeEnd,
  totalRowCount,
  hasPrev,
  hasNext,
  isFetchingNext,
  isLoading,
  queryExecutionId,
  onPrev,
  onNext
}: QueryResultsTableProps) {
  const {widths, setWidth, resetColumn} = useColumnWidths(queryExecutionId, columns.length);

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold">Results</h2>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface p-8 text-center text-sm text-text-3">
          {isLoading ? 'Loading results…' : 'No rows returned.'}
        </div>
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <div className="overflow-x-auto">
              <table className="w-full table-fixed border-collapse text-left">
                <colgroup>
                  <col style={{width: ROW_NUMBER_COLUMN_WIDTH}} />
                  {columns.map((_column, index) => (
                    <col
                      key={index}
                      style={{width: widths[index] ?? undefined}}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr className="h-10 border-b border-border bg-surface-2">
                    <th
                      scope="col"
                      className="px-3 text-xs font-semibold uppercase tracking-wide text-text-3">
                      #
                    </th>
                    {columns.map((column, index) => (
                      <th
                        key={index}
                        scope="col"
                        className="relative px-3 text-xs font-semibold uppercase tracking-wide text-text-3">
                        <span
                          className="block truncate"
                          title={column.name}>
                          {column.name}
                        </span>
                        <span
                          className="block truncate font-mono text-[10px] normal-case tracking-normal text-text-3"
                          title={column.type}>
                          {column.type}
                        </span>
                        <ColumnResizeHandle
                          columnIndex={index}
                          columnName={column.name}
                          width={widths[index] ?? 0}
                          onResize={setWidth}
                          onReset={resetColumn}
                        />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIndex) => (
                    <tr
                      key={rowIndex}
                      className="h-12 border-b border-border-2 font-mono text-sm last:border-0 hover:bg-surface-2">
                      {/* Absolute row number across pages, not the in-page index. */}
                      <td className="truncate px-3 text-text-3">{rangeStart + rowIndex}</td>
                      {row.map((cell, cellIndex) => (
                        <td
                          key={cellIndex}
                          className="truncate px-3"
                          title={cell}>
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Prev/Next pager (FR-002), below the horizontal scroll region so it
              stays usable with a wide, scrolled result. Range indicator shows
              "Rows X–Y"; the definitive total appears only at the last page. */}
          <Pager
            className="py-4"
            hasPrev={hasPrev}
            hasNext={hasNext}
            nextBusy={isFetchingNext}
            onPrev={onPrev}
            onNext={onNext}
            label={
              <>
                Rows {rangeStart}–{rangeEnd}
                {totalRowCount !== null ? ` of ${totalRowCount}` : ''}
                <span className="sr-only"> (page {pageIndex + 1})</span>
              </>
            }
          />
        </>
      )}
    </div>
  );
}
