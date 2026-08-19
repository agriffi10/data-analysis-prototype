import {useQueries, useQuery, type QueryClient} from '@tanstack/react-query';
import {getDatabase, listTables} from './glue.service';
import {unwrap} from '../../lib/serviceResult';
import {catalogKeys} from './catalogKeys';
import {NO_KEY} from '../../lib/queryKeys';
import type {GlueTableSummary} from './catalog.types';
import type {DatabaseSchema} from './catalog.types';

export type SchemaData = {
  database: {name: string};
  tables: GlueTableSummary[];
};

async function fetchSchema(db: string): Promise<SchemaData> {
  const database = unwrap(await getDatabase(db));
  const tables = unwrap(await listTables(db));
  return {database, tables};
}

/**
 * Loads a database + its tables for the schema browser. Disabled while the
 * database name is null. Keyed by database so DDL runs can refresh it via
 * {@link invalidateSchema}.
 */
export function useSchema(databaseName: string | null) {
  return useQuery({
    queryKey: catalogKeys.schema(databaseName ?? NO_KEY),
    enabled: databaseName !== null,
    queryFn: () => fetchSchema(databaseName as string)
  });
}

/**
 * Loads the schemas of every accessible database at once so the
 * editor's autocomplete can offer fully-qualified table names across all of
 * them. Shares the per-database query keys with {@link useSchema}, so a schema
 * already loaded by an expanded rail node is reused (and vice versa), and DDL
 * invalidation refreshes both. Databases that fail to load are omitted.
 */
export function useAllSchemas(databaseNames: string[]): DatabaseSchema[] {
  const results = useQueries({
    queries: databaseNames.map((db) => ({
      queryKey: catalogKeys.schema(db),
      queryFn: () => fetchSchema(db)
    }))
  });
  return databaseNames
    .map((database, i) => (results[i].data ? {database, tables: results[i].data.tables} : null))
    .filter((s): s is DatabaseSchema => s !== null);
}

/**
 * Something that must be re-read when a database's catalog changes, over and above this
 * module's own schema query.
 */
export type CatalogChangeListener = (client: QueryClient, databaseName: string) => void;

const listeners = new Set<CatalogChangeListener>();

/**
 * Registers a listener for "this database's catalog changed".
 *
 * **THE SHARED LAYER MUST NOT IMPORT THE LEAF FEATURE**, which is the whole reason this is a
 * registration rather than a call. The Data Explorer caches an Athena execution forever, keyed
 * by the SQL it rendered — so a table dropped and rebuilt under the same name goes on
 * answering from the old execution. It has to hear about {@link invalidateSchema}, and
 * `features/catalog/` reaching into `features/data-explorer/` to tell it would be the
 * undeclared shared layer this directory exists to prevent, pointing the other way.
 *
 * A registration rather than a call beside each of the five existing `invalidateSchema` sites,
 * too: each of those is a place a future author would have to remember, and the sixth would be
 * written by someone who had never heard of the cache it silently invalidates.
 *
 * Not a query-cache subscription: TanStack emits no event for invalidating a key nothing has
 * cached, and the rail's schema is not always loaded when a DDL statement runs.
 *
 * @param listener - Called after the schema invalidation, with the same client and database.
 * @returns The unsubscribe function.
 */
export function onCatalogChange(listener: CatalogChangeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Refreshes a database's cached schema after schema-changing DDL runs, and tells every
 * registered listener the same thing.
 *
 * @param client - The query client.
 * @param databaseName - The database whose catalog changed.
 * @returns Nothing, once the invalidation has settled.
 */
export async function invalidateSchema(client: QueryClient, databaseName: string): Promise<void> {
  await client.invalidateQueries({queryKey: catalogKeys.schema(databaseName)});
  for (const listener of listeners) listener(client, databaseName);
}
