import {useEffect} from 'react';
import {useQueryClient, type QueryClient} from '@tanstack/react-query';
import {onCatalogChange} from '../catalog/useSchema';
import {explorerKeys} from './explorerKeys';

/**
 * Drops every cached exploration execution that could be reading a database whose catalog just
 * changed.
 *
 * @param client - The query client.
 * @param database - The database whose schema was invalidated.
 * @returns Nothing.
 */
export function evictExplorations(client: QueryClient, database: string): void {
  client.removeQueries({queryKey: explorerKeys.database(database)});
  client.removeQueries({queryKey: explorerKeys.sqlSources()});
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
