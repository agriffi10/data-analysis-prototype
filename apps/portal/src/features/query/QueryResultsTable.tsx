import type { QueryColumn } from './query.types';

type QueryResultsTableProps = {
  columns: QueryColumn[];
  rows: string[][];
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
};

// SPEC-035 FR-006: results table reusing the file-table visual language (surface,
// border, rounded-lg, surface-2 uppercase header, 48px monospace rows, hover).
// Dynamic columns scroll horizontally without breaking the shell. A successful
// DDL / zero-row SELECT renders the friendly empty state, not an error.
// Pagination is the centered "Load more" (SPEC-034 NextToken); SPEC-038 replaces
// it with a 20-row Prev/Next pager.
export function QueryResultsTable({
  columns,
  rows,
  hasMore,
  isLoadingMore,
  onLoadMore,
}: QueryResultsTableProps) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-base font-semibold">Results</h2>
        <span className="text-sm text-text-2">
          {rows.length}
          {hasMore ? '+' : ''} {rows.length === 1 ? 'row' : 'rows'}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface p-8 text-center text-sm text-text-3">
          No rows returned.
        </div>
      ) : (
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
                    <td className="px-3 text-text-3">{rowIndex + 1}</td>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="whitespace-nowrap px-3"
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {hasMore && (
        <div className="py-4 text-center">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="h-9 rounded-md border border-border px-4 text-sm font-medium text-text-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            {isLoadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}
