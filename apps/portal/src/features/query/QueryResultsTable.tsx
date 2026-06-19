import type { QueryColumn } from './query.types';

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
  onPrev: () => void;
  onNext: () => void;
};

const pagerButton =
  'h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40';

// SPEC-035 FR-006 / SPEC-038 FR-002: results table reusing the file-table visual
// language (surface, border, rounded-lg, surface-2 uppercase header, 48px
// monospace rows, hover). Dynamic columns scroll horizontally without breaking
// the shell. A successful DDL / zero-row SELECT renders the friendly empty state,
// not an error. Pagination is a Prev/Next pager that shows exactly one page
// (≤ page size rows) at a time — navigating REPLACES the visible rows (SPEC-038),
// unlike the file browser's append-style "Load more" (SPEC-037).
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
  onPrev,
  onNext,
}: QueryResultsTableProps) {
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
              <table className="w-full min-w-max border-collapse text-left">
                <thead>
                  <tr className="h-10 border-b border-border bg-surface-2">
                    <th className="w-14 px-3 text-xs font-semibold uppercase tracking-wide text-text-3">
                      #
                    </th>
                    {columns.map((column) => (
                      <th
                        key={column.name}
                        className="whitespace-nowrap px-3 text-xs font-semibold uppercase tracking-wide text-text-3"
                      >
                        <span className="block">{column.name}</span>
                        <span className="block font-mono text-[10px] normal-case tracking-normal text-text-3">
                          {column.type}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIndex) => (
                    <tr
                      key={rowIndex}
                      className="h-12 border-b border-border-2 font-mono text-sm last:border-0 hover:bg-surface-2"
                    >
                      {/* Absolute row number across pages, not the in-page index. */}
                      <td className="px-3 text-text-3">{rangeStart + rowIndex}</td>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="whitespace-nowrap px-3">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Prev/Next pager (FR-002). Range indicator shows "Rows X–Y"; the
              definitive total appears only once the last page is reached. */}
          <div className="flex items-center justify-between gap-3 py-4">
            <button
              type="button"
              onClick={onPrev}
              disabled={!hasPrev}
              className={pagerButton}
            >
              Prev
            </button>
            <span className="text-sm text-text-2" aria-live="polite">
              Rows {rangeStart}–{rangeEnd}
              {totalRowCount !== null ? ` of ${totalRowCount}` : ''}
              <span className="sr-only"> (page {pageIndex + 1})</span>
            </span>
            <button
              type="button"
              onClick={onNext}
              disabled={!hasNext || isFetchingNext}
              className={pagerButton}
            >
              {isFetchingNext ? 'Loading…' : 'Next'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
