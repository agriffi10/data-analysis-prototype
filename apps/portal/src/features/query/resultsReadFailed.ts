import type {UseQueryResultsResult} from '../catalog/useQueryResults';

/**
 * Whether a run's results could not be read at all — the case the empty state must not speak for.
 *
 * A re-read that fails keeps the page already loaded, and TanStack still reports that as an error.
 * A loaded page always carries its columns, so an error with no columns is a read that never
 * produced anything; one with columns is a result the user has already seen, rows or none.
 *
 * @param results - The results hook's state for the run on screen.
 * @returns True when the error, not "no rows", is the answer to show.
 *
 * @example
 * <QueryResultsTable loadError={resultsReadFailed(results) ? results.error : null} />
 */
export function resultsReadFailed(results: Pick<UseQueryResultsResult, 'isError' | 'columns'>): boolean {
  return results.isError && results.columns.length === 0;
}
