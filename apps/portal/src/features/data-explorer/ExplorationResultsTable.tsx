import {ErrorBanner} from '../../components/ErrorBanner';
import {Pager} from '../../components/Pager';
import {useQueryResults} from '../catalog/useQueryResults';
import {EXPLORATION_PAGE_SIZE} from './dataExplorer.constants';

export type ExplorationResultsTableProps = {
  queryExecutionId: string | null;
  /** The exploration is starting or still running. */
  isPending: boolean;
  /** A render refusal, a failed start, or a failed poll. Rendered through `toUserMessage`. */
  error: unknown;
};

/**
 * **A PLACEHOLDER, replaced wholesale by SPEC-180's grid.**
 *
 * Rows have to render somewhere for the route to be verifiable, so this is a plain table
 * over SPEC-176's pager and nothing more: no resize, no reorder, no pinning, no hiding, no
 * cell selection, no Value panel. None of that is missing — it has not been built yet, and
 * nothing about this component is a contract for the one that replaces it.
 *
 * Errors go through `ErrorBanner` (SPEC-106): Athena's own text never reaches a user, and
 * neither does an `ExplorationRenderError`, whose message names a column for an operator.
 */
export function ExplorationResultsTable({queryExecutionId, isPending, error}: ExplorationResultsTableProps) {
  const results = useQueryResults(queryExecutionId, EXPLORATION_PAGE_SIZE);

  if (error) {
    return (
      <div className="p-4">
        <ErrorBanner error={error} />
      </div>
    );
  }

  if (isPending || !queryExecutionId) {
    return (
      <p
        role="status"
        className="p-4 text-sm text-text-3">
        Running&hellip;
      </p>
    );
  }

  if (results.isError) {
    return (
      <div className="p-4">
        <ErrorBanner error={results.error} />
      </div>
    );
  }

  if (results.isPending) {
    return (
      <p
        role="status"
        className="p-4 text-sm text-text-3">
        Loading rows&hellip;
      </p>
    );
  }

  // A query that succeeded over no matching rows is an ANSWER, not a fault — the friendly
  // empty state, never the error banner.
  if (results.rows.length === 0) {
    return <p className="p-4 text-sm text-text-2">No rows returned.</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-surface-2">
            <tr>
              {results.columns.map((column) => (
                <th
                  key={column.name}
                  scope="col"
                  className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-semibold text-text-2">
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.rows.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className="odd:bg-surface even:bg-surface-2/40">
                {results.columns.map((column, cellIndex) => (
                  <td
                    key={column.name}
                    className="max-w-[24rem] truncate border-b border-border px-3 py-1.5 text-text">
                    {row[cellIndex]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager
        hasPrev={results.hasPrev}
        hasNext={results.hasNext}
        onPrev={results.goPrev}
        onNext={results.goNext}
        nextBusy={results.isFetchingNext}
        label={`Rows ${results.rangeStart}–${results.rangeEnd}`}
        className="flex-none border-t border-border px-3 py-2"
      />
    </div>
  );
}
