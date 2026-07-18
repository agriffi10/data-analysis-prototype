import {useQueries, useQuery, type QueryClient} from '@tanstack/react-query';
import {getDatabase, listTables} from './glue.service';
import {unwrap} from '../../lib/serviceResult';
import {queryKeys} from './queryKeys';
import type {GlueTableSummary} from './query.types';
import type {DatabaseSchema} from './sqlCompletions';

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
    queryKey: queryKeys.schema(databaseName ?? '__none__'),
    enabled: databaseName !== null,
    queryFn: () => fetchSchema(databaseName as string)
  });
}

/**
 * Loads the schemas of every accessible database at once (SPEC-077) so the
 * editor's autocomplete can offer fully-qualified table names across all of
 * them. Shares the per-database query keys with {@link useSchema}, so a schema
 * already loaded by an expanded rail node is reused (and vice versa), and DDL
 * invalidation refreshes both. Databases that fail to load are omitted.
 */
export function useAllSchemas(databaseNames: string[]): DatabaseSchema[] {
  const results = useQueries({
    queries: databaseNames.map((db) => ({
      queryKey: queryKeys.schema(db),
      queryFn: () => fetchSchema(db)
    }))
  });
  return databaseNames
    .map((database, i) => (results[i].data ? {database, tables: results[i].data.tables} : null))
    .filter((s): s is DatabaseSchema => s !== null);
}

/** Refreshes a database's cached schema after schema-changing DDL runs. */
export async function invalidateSchema(client: QueryClient, databaseName: string): Promise<void> {
  await client.invalidateQueries({queryKey: queryKeys.schema(databaseName)});
}
