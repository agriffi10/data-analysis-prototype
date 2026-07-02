import {useQuery, type QueryClient} from '@tanstack/react-query';
import {getDatabase, listTables} from './glue.service';
import {queryKeys} from './queryKeys';
import type {GlueTableSummary} from './query.types';

export type SchemaData = {
  database: {name: string};
  tables: GlueTableSummary[];
};

/**
 * Loads a database + its tables for the schema browser. Disabled while the
 * database name is null. Keyed by database so DDL runs can refresh it via
 * {@link invalidateSchema}.
 */
export function useSchema(databaseName: string | null) {
  return useQuery({
    queryKey: queryKeys.schema(databaseName ?? '__none__'),
    enabled: databaseName !== null,
    queryFn: async (): Promise<SchemaData> => {
      const db = databaseName as string;
      const dbResult = await getDatabase(db);
      if (!dbResult.success) throw new Error(dbResult.error.message);
      const tablesResult = await listTables(db);
      if (!tablesResult.success) throw new Error(tablesResult.error.message);
      return {database: dbResult.data, tables: tablesResult.data};
    }
  });
}

/** Refreshes a database's cached schema after schema-changing DDL runs. */
export async function invalidateSchema(client: QueryClient, databaseName: string): Promise<void> {
  await client.invalidateQueries({queryKey: queryKeys.schema(databaseName)});
}
