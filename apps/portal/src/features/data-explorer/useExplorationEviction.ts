import {useEffect} from 'react';
import {useQueryClient, type QueryClient} from '@tanstack/react-query';
import {onCatalogChange} from '../catalog/useSchema';
import {explorerKeys} from './explorerKeys';

/**
 * Drops the cached exploration executions that could be reading a database whose catalog just
 * changed — the ones **nothing is currently watching**.
 *
 * **THE OBSERVER FILTER IS THE WHOLE SAFETY PROPERTY.** `useExploration` already records why:
 * removing a query that has an observer attached makes it refetch immediately. For a cached
 * execution id that means a second `StartQueryExecution` against the same bytes — a real bill,
 * for a catalog change that may have nothing to do with the rows on screen. Creating a view
 * from the exploration you are looking at invalidates its own database and would have paid for
 * the exploration twice.
 *
 * What it costs: the tab in front of you keeps its rows until you change something or come back
 * to it. That is the narrow residue of the bug this closes, and it is the cheap side of the
 * trade — the wide case is every OTHER cached exploration, which is where a dropped-and-rebuilt
 * table's old rows used to wait for the rest of the session.
 *
 * @param client - The query client.
 * @param database - The database whose schema was invalidated.
 * @returns Nothing.
 */
export function evictExplorations(client: QueryClient, database: string): void {
  for (const queryKey of [explorerKeys.database(database), explorerKeys.sqlSources()]) {
    client.removeQueries({queryKey, predicate: (query) => query.getObserversCount() === 0});
  }
}

/**
 * Keeps the Data Explorer's execution cache honest when the catalog changes underneath it.
 *
 * **THE CACHE IS `staleTime: Infinity, gcTime: Infinity` ON PURPOSE** — it is the cost
 * control, and re-running an identical statement would scan the same bytes for the same rows.
 * What it cannot see is a table dropped and rebuilt under the same name over different data:
 * the SQL renders byte-identical, so the entry stays a hit and the Explorer serves the old
 * execution's rows for the whole session. Weakening the cache would bill every gesture; the
 * answer is to evict on the one signal that says the catalog moved.
 *
 * Subscribing to `invalidateSchema` rather than calling beside each of its five call sites:
 * the reasoning, and why it is a registration and not a query-cache subscription, is on
 * `onCatalogChange`.
 *
 * The residual is worth stating: this fires on invalidations raised **in this browser**. A
 * table rebuilt entirely in another session evicts nothing here until something invalidates
 * that database's schema locally, which the rail's own refresh control does.
 *
 * Mount once, in the authenticated shell. Mounting it inside the Explorer would miss the
 * ordinary case, which is a table dropped from the Query workspace with the Explorer's tabs
 * open behind it.
 */
export function useExplorationEviction(): void {
  const client = useQueryClient();
  useEffect(() => onCatalogChange((_client, database) => evictExplorations(client, database)), [client]);
}
