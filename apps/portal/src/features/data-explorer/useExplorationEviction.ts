import {useEffect} from 'react';
import {useQueryClient, type QueryClient} from '@tanstack/react-query';
import {onCatalogChange} from '../catalog/useSchema';
import {explorerKeys, readsFromSqlBody} from './explorerKeys';

/**
 * Drops the cached exploration executions that could be reading a catalog that just changed.
 *
 * **IT EVICTS WHAT IS ON SCREEN TOO, AND THAT IS THE POINT.** A stale execution must not be
 * served at all — not until the user changes a filter, not until they come back to the tab. So
 * an observed query is removed like any other, and TanStack refetches it immediately: the tab
 * in front of the user re-runs and shows the rebuilt table's rows.
 *
 * That refetch is a second billed `StartQueryExecution`, which is why the eviction is as narrow
 * as the signal allows. A caller that knows WHICH table changed evicts only explorations of
 * that table, so creating a view next to an exploration — a catalog change that touches no rows
 * of it — costs nothing. Only a change that names no table falls back to the whole database,
 * and those are the two cases where re-reading everything is what the user asked for: an
 * arbitrary DDL statement they typed, and the rail's own refresh button.
 *
 * Saved-query sources are evicted on every change, whichever database moved: the body is
 * arbitrary SQL over any number of databases and this app has no parser.
 *
 * @param client - The query client.
 * @param database - The database whose catalog changed.
 * @param table - The one table that changed, when the caller knows it.
 * @returns Nothing.
 */
export function evictExplorations(client: QueryClient, database: string, table?: string): void {
  // `resetQueries`, not `removeQueries`. Removing an entry only re-runs an observed query if
  // something re-renders afterwards — in the app something usually does (a toast, a dialog
  // closing), which is exactly the kind of accident this must not depend on. Reset clears the
  // entry AND refetches every query with an observer, by contract.
  client.resetQueries({queryKey: table ? explorerKeys.table(database, table) : explorerKeys.database(database)});
  client.resetQueries({queryKey: explorerKeys.sqlSources()});
}

/**
 * Drops every cached execution over one statement source, whatever it was filtered, sorted or
 * grouped by — so the statement, and each description over it, runs again the next time it is
 * shown.
 *
 * A statement handed over from a Query result calls this once its tab exists: executions are
 * cached by rendered SQL for the session, and without it exploring the same statement after an
 * `INSERT` would show the earlier rows, as would every filter re-applied over them. Only this
 * body's executions go; another statement's tab must not re-run.
 *
 * `removeQueries`, not the catalog eviction's `resetQueries`: a reset refetches every OBSERVED
 * match at once, so a tab over the same body still mounted behind the new one would be billed
 * again for a result nobody is looking at. The new tab's own read finds no entry and fetches.
 *
 * @param client - The query client.
 * @param body - The statement source's body.
 * @returns Nothing.
 */
export function evictSqlSource(client: QueryClient, body: string): void {
  client.removeQueries({
    queryKey: explorerKeys.sqlSources(),
    predicate: (query) => readsFromSqlBody(query.queryKey, body)
  });
}

/**
 * Keeps the Data Explorer's execution cache honest when the catalog changes underneath it.
 *
 * **THE CACHE IS `staleTime: Infinity, gcTime: Infinity` ON PURPOSE** — it is the cost control,
 * and re-running an identical statement would scan the same bytes for the same rows. What it
 * cannot see is a table dropped and rebuilt under the same name over different data: the SQL
 * renders byte-identical, so the entry stays a hit and the Explorer serves the old execution's
 * rows. Weakening the cache would bill every gesture; the answer is to evict on the signal that
 * says the catalog moved, and to make that signal name a table wherever the caller knows one.
 *
 * Subscribing to `invalidateSchema` rather than calling beside each of its call sites: the
 * reasoning, and why it is a registration and not a query-cache subscription, is on
 * `onCatalogChange`.
 *
 * The residual is worth stating: this fires on invalidations raised **in this browser**. The
 * async table build would otherwise slip through entirely — it completes long after the enqueue
 * — so `useCatalogCatchUp` re-reads that catalog on the next window focus. Its own residual is
 * on its docstring: a user who never leaves the window gets no catch-up until they do.
 *
 * Mount once, in the authenticated shell. Mounting it inside the Explorer would miss the
 * ordinary case, which is a table dropped from the Query workspace with the Explorer's tabs
 * open behind it.
 */
export function useExplorationEviction(): void {
  const client = useQueryClient();
  useEffect(() => onCatalogChange((_client, database, table) => evictExplorations(client, database, table)), [client]);
}
