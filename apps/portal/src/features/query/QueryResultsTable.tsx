import {Pager} from '../../components/Pager';
import {ColumnResizeHandle} from '../catalog/ColumnResizeHandle';
import type {QueryColumn} from '../catalog/catalog.types';
import {SECTION_CAPTION} from '../../components/fieldStyles';

// The leading row-number (`#`) column is a fixed, non-resizable width.
const ROW_NUMBER_COLUMN_WIDTH = 56; // px (matches the old w-14)

type QueryResultsTableProps = {
  columns: QueryColumn[];
  // Current page only (≤ page size). A null cell is SQL NULL and renders blank here —
  // this surface makes nothing of the distinction (the Data Explorer's grid does).
  rows: (string | null)[][];
  pageIndex: number; // 0-based
  rangeStart: number; // 1-based row number of the first row on this page
  rangeEnd: number; // 1-based row number of the last row on this page
  totalRowCount: number | null; // known only once the last page is loaded
  hasPrev: boolean;
  hasNext: boolean;
  isFetchingNext: boolean;
  isLoading: boolean; // first page in flight
  // Controlled column widths (px per data column), owned by the parent's
  // useColumnWidths so they survive paging AND tab switches; handlers clamp/reset.
  widths: number[];
  onResize: (index: number, px: number) => void;
  onResetColumn: (index: number) => void;
  onPrev: () => void;
  onNext: () => void;
};

// Results table reusing the file-table visual
// language (surface, border, rounded-lg, surface-2 uppercase header, monospace
// rows, hover). Columns are user-resizable — a <colgroup> of explicit
// widths drives table-layout:fixed, each data-column header carries a drag/keyboard
// resize handle, cells/headers truncate with an ellipsis (full text on hover via
// `title`), and the body scrolls horizontally for wide (20+ column) results.
// Widths are supplied by the parent (useColumnWidths, keyed by execution id) so
// they persist across Prev/Next and tab switches and reset on a new query. A
// successful DDL / zero-row SELECT renders the friendly empty state, not an error.
// Navigating REPLACES the visible rows, unlike the file browser's
// append-style "Load more".
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
  widths,
  onResize,
  onResetColumn,
  onPrev,
  onNext
}: QueryResultsTableProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {rows.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface p-8 text-center text-sm text-text-3">
          {isLoading ? 'Loading results…' : 'No rows returned.'}
        </div>
      ) : (
        <>
          {/* Single scroll container: the result body scrolls in BOTH axes HERE
              rather than scrolling the whole page. `border-separate` (not
              `collapse`) so per-cell borders travel with the sticky header/column
              instead of detaching. The header row sticks to the top (survives
              vertical scroll) and the row-number column sticks to the left
              (survives horizontal scroll); the top-left corner outranks both.
              The box hugs its content (no `flex-1`) so a short result doesn't
              leave an empty bordered gap below the rows; when the rows overflow
              the available height, `min-h-0` lets it shrink and scroll instead. */}
          <div className="min-h-0 overflow-auto rounded-lg border border-border bg-surface">
            <table className="w-full table-fixed border-separate border-spacing-0 text-left">
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
                <tr className="h-10">
                  <th
                    scope="col"
                    className={`sticky left-0 top-0 z-30 border-b border-border bg-surface-2 px-3 ${SECTION_CAPTION}`}>
                    #
                  </th>
                  {columns.map((column, index) => (
                    <th
                      key={index}
                      scope="col"
                      className={`sticky top-0 z-20 border-b border-border bg-surface-2 px-3 ${SECTION_CAPTION}`}>
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
                        column={index}
                        columnName={column.name}
                        width={widths[index] ?? 0}
                        onResize={onResize}
                        onReset={onResetColumn}
                      />
                    </th>
                  ))}
                </tr>
              </thead>
              {/* Array-index keys are intentional here: result
                  rows/cells are plain strings with no stable identity, columns can
                  share a name (e.g. SELECT a, a), and the table is FULLY replaced on
                  every page/query with no per-cell focus or local state to preserve —
                  so index keys can't reuse a node across logically-different content. */}
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr
                    key={rowIndex}
                    className="group h-12 font-mono text-sm hover:bg-surface-2">
                    {/* Absolute row number across pages, not the in-page index.
                        Sticky-left so it stays pinned while scrolling the X axis;
                        its own bg tracks the row hover so it never goes transparent. */}
                    <td className="sticky left-0 z-10 truncate border-b border-border-2 bg-surface px-3 text-text-3 group-last:border-0 group-hover:bg-surface-2">
                      {rangeStart + rowIndex}
                    </td>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="truncate border-b border-border-2 px-3 group-last:border-0"
                        title={cell ?? ''}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Prev/Next pager, below the scroll region so it stays usable
              with a wide/tall, scrolled result. Range indicator shows "Rows X–Y";
              the definitive total appears only at the last page. */}
          <Pager
            className="flex-none py-4"
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
